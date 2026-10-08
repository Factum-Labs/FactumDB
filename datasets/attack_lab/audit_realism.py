"""Audit fixture validity and independently reproduce normal MySQL behavior.

Creates a small, unrelated commerce database with foreign keys on a private
MySQL instance. Original subjects and backend source are never modified.
Run from the repository root:
  py -3.11 datasets/attack_lab/audit_realism.py --mysql-bin ".../bin"
Scratch databases, snapshots, SQL, diagnostics and JSON go under .scratch/.
"""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from generate import LabServer, SUBJECTS, event_headers

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "backend"))
from adapters.tools.ibd2sdi_adapter import Ibd2SdiAdapter
from adapters.tools.ibd2sql_adapter import Ibd2SqlAdapter
from adapters.tools.innochecksum_adapter import InnochecksumAdapter
from adapters.tools.mysqlbinlog_adapter import MysqlBinlogAdapter
from core.domain.models.canonical import BinlogInventory
from core.domain.models.values import compare
from core.domain.ports import DEFAULT_SUPPORTED_TYPES
from core.domain.services.record_correlation import RecordCorrelationService
from core.domain.services.record_reconciliation import ReconciliationService
from core.domain.services.state_reconstruction import StateReconstructionService
from core.domain.services.transaction_grouping import TransactionGroupingService
from tests.fixtures.inmemory import (
    InMemorySchemaCatalog, InMemoryEventSource, InMemoryEvidenceContext,
    InMemoryPhysicalRecordSource,
)

SCHEMA = """CREATE DATABASE audit_shop CHARACTER SET utf8mb4;
USE audit_shop;
CREATE TABLE customers (
 id INT PRIMARY KEY, email VARCHAR(120) NOT NULL UNIQUE,
 full_name VARCHAR(80) NOT NULL
) ENGINE=InnoDB;
CREATE TABLE orders (
 id INT PRIMARY KEY, customer_id INT NOT NULL, total DECIMAL(12,2) NOT NULL,
 status VARCHAR(20) NOT NULL,
 FOREIGN KEY (customer_id) REFERENCES customers(id)
) ENGINE=InnoDB;
CREATE TABLE order_lines (
 order_id INT NOT NULL, line_no INT NOT NULL, product VARCHAR(80) NOT NULL,
 quantity INT NOT NULL, unit_price DECIMAL(12,2) NOT NULL,
 PRIMARY KEY(order_id,line_no),
 FOREIGN KEY(order_id) REFERENCES orders(id)
) ENGINE=InnoDB;
CREATE TABLE order_notes (
 id INT PRIMARY KEY, order_id INT NOT NULL, note TEXT NOT NULL,
 FOREIGN KEY(order_id) REFERENCES orders(id)
) ENGINE=InnoDB;
CREATE USER 'audit_app'@'localhost';
CREATE USER 'audit_app'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE ON audit_shop.* TO 'audit_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON audit_shop.* TO 'audit_app'@'127.0.0.1';
"""

NORMAL = """USE audit_shop;
INSERT INTO customers VALUES
 (1,'amara@example.invalid','Amara Silva'),
 (2,'maya@example.invalid','Maya Chen'),
 (3,'owen@example.invalid','Owen Morgan');
START TRANSACTION;
INSERT INTO orders VALUES (101,1,135.50,'paid'),(102,2,47.25,'paid');
INSERT INTO order_lines VALUES
 (101,1,'Desk lamp',1,100.00),(101,2,'Ceramic mug',2,17.75),
 (102,1,'Notebook',3,15.75);
INSERT INTO order_notes VALUES
 (1,101,'Delivery address checked'),(2,102,'Collect from branch'),
 (3,101,'Temporary packing instruction');
COMMIT;
"""

NORMAL_MINIMAL = "USE audit_shop; UPDATE order_notes SET note='Delivery rescheduled by customer' WHERE id=1;"

NORMAL_END = """USE audit_shop;
DELETE FROM order_notes WHERE id=3;
START TRANSACTION;
UPDATE orders SET total=1.00 WHERE id=102;
ROLLBACK;
"""

PRIVILEGED = """USE audit_shop;
SET SESSION sql_log_bin=0;
UPDATE orders SET total=777.50 WHERE id=101;
DELETE FROM order_notes WHERE id=2;
INSERT INTO order_notes VALUES (99,101,'An administrative write absent from row logs');
SET SESSION sql_log_bin=1;
START TRANSACTION;
UPDATE order_notes SET note='Packing exception approved' WHERE id=1;
COMMIT;
"""


def app_sql(server, sql):
    return subprocess.run([
        server.command("mysql"), "--no-defaults", "--protocol=TCP",
        "--host=127.0.0.1", f"--port={server.port}", "--user=audit_app",
        "--ssl-mode=DISABLED", "--batch", "--raw", "--skip-column-names",
    ], input=sql.encode(), capture_output=True, timeout=30)


def snapshot(server, target):
    (target / "ibd").mkdir(parents=True)
    (target / "binlog").mkdir()
    for path in (server.data / "audit_shop").glob("*.ibd"):
        shutil.copy2(path, target / "ibd" / path.name)
    for path in server.data.glob("mysql-bin.*"):
        shutil.copy2(path, target / "binlog" / path.name)


def inputs(server, target, ibd2sql):
    sdi = Ibd2SdiAdapter(server.command("ibd2sdi"))
    checks = InnochecksumAdapter(server.command("innochecksum"))
    rows = Ibd2SqlAdapter(str(ibd2sql), sys.executable)
    decoder = MysqlBinlogAdapter(server.command("mysqlbinlog"))
    schemas, physical, integrity = [], [], {}
    for path in sorted((target / "ibd").glob("*.ibd")):
        schema = sdi.extract_schema(str(path))
        schemas.append(schema)
        integrity[(schema.database, schema.table)] = checks.validate(str(path))
        assert integrity[(schema.database, schema.table)].status == "valid"
        physical.extend(rows.extract_records(str(path)))
    lookup = InMemorySchemaCatalog(*schemas)
    events, markers = [], []
    logs = sorted((target / "binlog").glob("mysql-bin.[0-9]*"))
    for path in logs:
        event_headers(path)
        checked = subprocess.run([server.command("mysqlbinlog"), "--no-defaults",
            "--verify-binlog-checksum", "-vv", "--base64-output=DECODE-ROWS", str(path)],
            capture_output=True, check=True)
        (target / (path.name + ".decoded.txt")).write_bytes(checked.stdout)
        batch, txs, warnings = decoder.decode(path.as_posix(), lookup.schema_for)
        assert not warnings, warnings
        events.extend(batch)
        markers.extend(txs)
    inventory = BinlogInventory("mysql-bin.index", tuple(p.name for p in logs),
                                tuple(p.name for p in logs), ())
    evidence = InMemoryEvidenceContext(inventory=inventory, integrity=integrity,
        physical_tables=frozenset((s.database,s.table) for s in schemas),
        extracted_tables=frozenset((s.database,s.table) for s in schemas))
    return schemas, physical, events, markers, evidence


def isolate(inputs_, key):
    """Project real decoded images onto one key to isolate later-stage defects.

    No row values, log positions, timestamps or observed commit status are changed.
    Marker membership is narrowed the same way application scope filtering works.
    """
    schemas, physical, events, markers, evidence = inputs_
    selected = [e for e in events if e.table == "order_notes" and
                ((e.before or {}).get("id") == key or (e.after or {}).get("id") == key)]
    refs = {(e.source_file,e.log_position) for e in selected}
    narrowed = [replace(m,event_positions=tuple(p for p in m.event_positions
                if (m.source_file,p) in refs)) for m in markers
                if any((m.source_file,p) in refs for p in m.event_positions)]
    source = InMemoryPhysicalRecordSource(*[p for p in physical if p.table == "order_notes" and p.values.get("id") == key])
    catalogue = InMemorySchemaCatalog(*schemas)
    grouped = TransactionGroupingService(evidence).group(InMemoryEventSource(selected,narrowed))
    correlated = RecordCorrelationService(catalogue,source,evidence).correlate(grouped)
    history = StateReconstructionService(catalogue,source,evidence).reconstruct(grouped,correlated)
    reconciled = ReconciliationService(catalogue,source,evidence).reconcile(history,correlated,grouped.coverage)
    return {
        "selected_actual_row_images":len(selected),
        "correlation_rules":sorted({f.rule_id for f in correlated.findings}),
        "fields":[{"field":r.field,"log":r.log_display,"physical":r.phys_display,
                   "result":r.result.value,"rule":r.rule_id} for r in reconciled.rows],
    }


def audit_original_subjects(server, ibd2sql):
    results = []
    for spec in SUBJECTS:
        folder, database, _, people, headers, lines, ledger, _ = spec
        root = ROOT/"subjects"/folder
        manifest = json.loads((root/"manifest.json").read_text(encoding="utf-8"))
        checksum_failures, schemas, physical = [], {}, {}
        for item in manifest["files"]:
            path = root/item["path"]
            assert path.stat().st_size == item["bytes"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        sdi = Ibd2SdiAdapter(server.command("ibd2sdi"))
        extractor = Ibd2SqlAdapter(str(ibd2sql),sys.executable)
        checks = InnochecksumAdapter(server.command("innochecksum"))
        for path in sorted((root/"ibd").glob("*.ibd")):
            schema = sdi.extract_schema(str(path))
            schemas[(schema.database,schema.table)] = schema
            state = checks.validate(str(path))
            if state.status != "valid":
                checksum_failures.append({"file":path.name,"status":state.status,"damaged_pages":state.damaged_pages})
            batch = extractor.extract_records(str(path))
            assert len(batch) == manifest["source_live_rows"][path.stem], (folder,path,len(batch))
            physical[path.stem] = [r.values for r in batch]
        decoder = MysqlBinlogAdapter(server.command("mysqlbinlog"))
        events, markers, warnings = [], [], []
        for path in sorted((root/"binlog").glob("mysql-bin.[0-9]*")):
            event_headers(path)
            subprocess.run([server.command("mysqlbinlog"),"--no-defaults","--verify-binlog-checksum",
                "-vv","--base64-output=DECODE-ROWS",str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
            batch, txs, skipped = decoder.decode(path.as_posix(),lambda d,t:schemas.get((d,t)))
            events.extend(batch); markers.extend(txs); warnings.extend(skipped)
        people_ids={r["id"] for r in physical[people]}
        header_ids={r["id"] for r in physical[headers]}
        parent_references_ok=all(r["person_id"] in people_ids for r in physical[headers])
        parent_references_ok &= all(r["record_id"] in header_ids for r in physical[lines])
        if ledger in physical:
            parent_references_ok &= all(r["record_id"] in header_ids for r in physical[ledger])
        line_totals=Counter()
        for r in physical[lines]:
            line_totals[r["record_id"]] += r["quantity"]*r["unit_minor"]
        line_mismatches=[r["id"] for r in physical[headers] if r["amount_minor"] != line_totals[r["id"]]]
        ledger_mismatches=None
        if ledger in physical:
            totals=Counter()
            for r in physical[ledger]:totals[r["record_id"]]+=r["amount_minor"]
            ledger_mismatches=[r["id"] for r in physical[headers] if r["amount_minor"] != totals[r["id"]]]
        results.append({"subject":folder,"hashes_match":True,"sdi_readable":True,
            "live_row_counts_match_source_manifest":True,"checksum_failures":checksum_failures,
            "binlog_event_boundaries_and_checksums_valid":True,"decoded_row_images":len(events),
            "distinct_event_positions":len({e.ref[:2] for e in events}),
            "decoder_marker_statuses":dict(Counter(m.status for m in markers)),
            "decode_warning_counts":dict(Counter(w.code for w in warnings)),
            "parent_references_valid_in_acquired_scope":parent_references_ok,
            "line_total_mismatch_ids":line_mismatches,"ledger_total_mismatch_ids":ledger_mismatches,
            "declared_acquisition_mutations":manifest["acquisition_mutations"]})
        print(f"Audited original subject: {folder}",flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-bin", type=Path, required=True)
    parser.add_argument("--ibd2sql", type=Path, default=ROOT.parents[1]/"src-tauri/resources/runtime/windows/ibd2sql/main.py")
    parser.add_argument("--port", type=int, default=34319)
    args = parser.parse_args()
    scratch = ROOT/".scratch"/("realism-"+datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6])
    server = LabServer(args.mysql_bin.resolve(),scratch,args.port)
    result = {}
    print("Creating independent MySQL commerce control with foreign keys...",flush=True)
    try:
        server.initialize()
        (scratch/"schema.sql").write_text(SCHEMA,encoding="utf-8")
        (scratch/"normal_activity.sql").write_text(NORMAL,encoding="utf-8")
        (scratch/"normal_minimal_activity.sql").write_text(NORMAL_MINIMAL,encoding="utf-8")
        (scratch/"normal_final_activity.sql").write_text(NORMAL_END,encoding="utf-8")
        (scratch/"administrator_logging_configuration.sql").write_text("SET GLOBAL binlog_row_image='MINIMAL';\n-- Run normal_minimal_activity.sql as audit_app in a new session.\nSET GLOBAL binlog_row_image='FULL';\n",encoding="utf-8")
        (scratch/"privileged_activity.sql").write_text(PRIVILEGED,encoding="utf-8")
        server.start()
        server.sql(SCHEMA)
        normal = app_sql(server,NORMAL)
        assert normal.returncode == 0,normal.stderr.decode(errors="replace")
        server.sql("SET GLOBAL binlog_row_image='MINIMAL';")
        minimal = app_sql(server,NORMAL_MINIMAL)
        assert minimal.returncode == 0,minimal.stderr.decode(errors="replace")
        server.sql("SET GLOBAL binlog_row_image='FULL';")
        final = app_sql(server,NORMAL_END)
        assert final.returncode == 0,final.stderr.decode(errors="replace")
        forbidden = app_sql(server,"SET SESSION sql_log_bin=0;")
        assert forbidden.returncode != 0,"Ordinary app account unexpectedly has session-administration privileges"
        result["ordinary_account_logging_disable"] = {"denied":True,"diagnostic":forbidden.stderr.decode().strip()}
        fk = app_sql(server,"DELETE FROM audit_shop.customers WHERE id=1;")
        assert fk.returncode != 0,"Foreign-key constraint not enforced"
        result["foreign_key_control"] = {"enforced":True,"diagnostic":fk.stderr.decode().strip()}
        result["normal_business_totals"] = server.sql("SELECT o.id,o.total,SUM(l.quantity*l.unit_price) FROM audit_shop.orders o JOIN audit_shop.order_lines l ON l.order_id=o.id GROUP BY o.id,o.total ORDER BY o.id;").strip()
        server.stop()
        clean = scratch/"normal_snapshot"
        snapshot(server,clean)
        normal_inputs = inputs(server,clean,args.ibd2sql.resolve())
        schemas,physical,events,markers,evidence = normal_inputs
        grouping = TransactionGroupingService(evidence).group(InMemoryEventSource(events,markers))
        result["normal_multirow"] = {"mysql_row_images":len(events),"unique_event_positions":len({e.ref[:2] for e in events}),"backend_retained_rows":grouping.event_count,"duplicate_findings":sum(f.rule_id=="R-GRP-013" for f in grouping.findings)}
        result["normal_minimal_update"] = isolate(normal_inputs,1)
        result["normal_logged_deletion"] = isolate(normal_inputs,3)
        types=[]
        for schema in schemas:
            for col in schema.columns:
                if col.data_type.startswith(("varchar(","decimal(")):
                    row=next((p for p in physical if p.table==schema.table),None)
                    if row:
                        value=row.values[col.name]
                        check=compare(value,value,col,DEFAULT_SUPPORTED_TYPES)
                        types.append({"column":schema.table+"."+col.name,"mysql_type":col.data_type,"same_value_comparable":check.comparable,"rule":check.rule_id})
        result["normal_parameterized_types"] = types
        server.start()
        server.sql(PRIVILEGED)
        server.stop()
        attack = scratch/"privileged_snapshot"
        snapshot(server,attack)
        privileged_inputs=inputs(server,attack,args.ibd2sql.resolve())
        result["privileged_hidden_deletion"] = isolate(privileged_inputs,2)
        result["privileged_unlogged_insertion"] = isolate(privileged_inputs,99)
        logs=sorted((attack/"binlog").glob("mysql-bin.[0-9]*"))
        last=logs[-1]
        cut=[h for h in event_headers(last) if h[1]==16][-1][0]
        cut_file=scratch/"acquisition_prefix.binlog"
        cut_file.write_bytes(last.read_bytes()[:cut])
        event_headers(cut_file)
        raw=subprocess.check_output([server.command("mysqlbinlog"),"--no-defaults","--verify-binlog-checksum","-vv","--base64-output=DECODE-ROWS",str(cut_file)])
        (scratch/"acquisition_prefix.decoded.txt").write_bytes(raw)
        decoder=MysqlBinlogAdapter(server.command("mysqlbinlog"))
        _, txs, warnings=decoder.decode(cut_file.as_posix(),InMemorySchemaCatalog(*schemas).schema_for)
        result["acquisition_prefix"]={"complete_event_boundary":True,"checksum_verified":True,"mysqlbinlog_generated_rollback":b"ROLLBACK /* added by mysqlbinlog */" in raw,"backend_marker_statuses":dict(Counter(t.status for t in txs)),"cut_offset":cut,"warning_codes":[w.code for w in warnings]}
        result["normal_source_files_modified"] = False
        result["original_subject_audit"] = audit_original_subjects(server,args.ibd2sql.resolve())
        (scratch/"audit_results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(result,indent=2),flush=True)
        print(f"Independent evidence and diagnostics: {scratch}",flush=True)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
