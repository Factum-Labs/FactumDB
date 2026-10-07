"""Generate real, fictional MySQL 8 evidence; never connects to an existing server.

Usage: py -3.11 datasets/attack_lab/generate.py --mysql-bin ".../MySQL Server 8.0/bin"
Only standard-library Python and the MySQL utilities are required.
An isolated loopback server and private data directory are used for each run.
Existing output is refused; choose --output for another run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import shutil
import socket
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parent
SUBJECTS = [
    ("01_marketplace_fraud", "harbor_market", "Harbor Market", "customers", "orders", "order_lines", "payments", "staff"),
    ("02_credit_union_log_erasure", "cedar_credit", "Cedar Credit Union", "members", "accounts", "account_products", "transfers", "employees"),
    ("03_clinic_interrupted_coverup", "maple_clinic", "Maple Clinic", "patients", "visits", "visit_services", "billing", "operators"),
    ("04_payroll_page_damage", "summit_payroll", "Summit Payroll", "workers", "payslips", "pay_components", "disbursements", "administrators"),
    ("05_logistics_scope_gaps", "meridian_freight", "Meridian Freight", "clients", "shipments", "shipment_items", "invoices", "dispatchers"),
    ("06_clean_marketplace", "willow_market", "Willow Market (clean control)", "customers", "orders", "order_lines", "payments", "staff"),
]
FIRST = ["Amara", "Nilan", "Maya", "Owen", "Priya", "Leah", "Arun", "Sofia", "Noah", "Dina", "Theo", "Isha"]
LAST = ["Perera", "Silva", "Fernando", "Chen", "Patel", "Morgan", "Reed", "Khan", "Costa", "Tan", "Walker", "Jayasinghe"]
CITIES = ["Colombo", "Kandy", "Galle", "Matara", "Jaffna", "Negombo", "Kurunegala", "Badulla"]
CATALOG = {
    "harbor_market": ["Desk lamp", "Cotton towel", "Ceramic mug", "Notebook set", "Storage basket"],
    "cedar_credit": ["Savings contribution", "Term deposit", "Loan installment", "Service charge", "Interest credit"],
    "maple_clinic": ["Consultation", "Blood panel", "Ultrasound", "Physiotherapy", "Follow-up appointment"],
    "summit_payroll": ["Base salary", "Overtime", "Travel allowance", "Pension contribution", "Performance bonus"],
    "meridian_freight": ["Pallet handling", "Regional delivery", "Customs processing", "Insurance", "Storage fee"],
}


def quote(value):
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def insert(table, rows):
    return f"INSERT INTO `{table}` VALUES " + ",\n".join("(" + ",".join(map(quote, row)) + ")" for row in rows) + ";\n"


class LabServer:
    def __init__(self, binaries, scratch, port):
        self.binaries, self.scratch, self.port = binaries, scratch, port
        self.data = scratch / "mysql-data"
        self.process = None
        self.log = None

    def command(self, name):
        path = self.binaries / (name + (".exe" if (self.binaries / (name + ".exe")).exists() else ""))
        if not path.is_file():
            raise RuntimeError(f"Missing MySQL utility: {path}")
        return str(path)

    def initialize(self):
        self.scratch.mkdir(parents=True, exist_ok=False)
        self.data.mkdir()
        with (self.scratch / "initialize.log").open("wb") as log:
            subprocess.run([self.command("mysqld"), "--no-defaults", "--initialize-insecure",
                            f"--basedir={self.binaries.parent.as_posix()}", f"--datadir={self.data.as_posix()}"],
                           stdout=log, stderr=log, check=True, timeout=180)

    def start(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", self.port))
        self.log = (self.scratch / "server.log").open("ab")
        self.process = subprocess.Popen([
            self.command("mysqld"), "--no-defaults", "--console",
            f"--basedir={self.binaries.parent.as_posix()}", f"--datadir={self.data.as_posix()}",
            "--bind-address=127.0.0.1", f"--port={self.port}", "--mysqlx=0", "--server-id=771",
            f"--log-bin={(self.data / 'mysql-bin').as_posix()}", "--binlog-format=ROW",
            "--binlog-row-image=FULL", "--binlog-checksum=CRC32", "--max-binlog-size=1073741824",
            "--innodb-file-per-table=ON", "--innodb-buffer-pool-size=134217728",
            "--innodb-redo-log-capacity=67108864", "--innodb-fast-shutdown=0",
            "--default-time-zone=+00:00"],
            stdout=self.log, stderr=self.log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(120):
            if self.process.poll() is not None:
                raise RuntimeError(f"Private mysqld exited; inspect {self.scratch / 'server.log'}")
            try:
                self.sql("SELECT 1;")
                return
            except (subprocess.SubprocessError, OSError, RuntimeError):
                time.sleep(0.5)
        raise RuntimeError("Private MySQL server did not become ready")

    def sql(self, sql):
        result = subprocess.run([self.command("mysql"), "--no-defaults", "--protocol=TCP",
                                 "--host=127.0.0.1", f"--port={self.port}", "--user=root", "--connect-timeout=5", "--ssl-mode=DISABLED",
                                 "--batch", "--raw", "--skip-column-names", "--default-character-set=utf8mb4"],
                                input=sql.encode(), capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace")[:1500])
        return result.stdout.decode()

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.sql("SHUTDOWN;")
            except RuntimeError:
                # Startup failures may prevent authentication. This handle is
                # exclusively the private server spawned by this instance.
                self.process.terminate()
            self.process.wait(timeout=120)
        if self.log:
            self.log.close()
            self.log = None


def baseline(spec, scale, seed, clean):
    _, db, _, people, records, lines, ledger, staff = spec
    rng = random.Random(seed)
    sql = [f"CREATE DATABASE `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin; USE `{db}`;\n"]
    # TEXT and INT avoid the current full-type-name comparison limitation in the
    # clean control. Currency is integer minor units, not binary floating point.
    sql += [f"CREATE TABLE `{people}` (id INT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT NOT NULL, city TEXT NOT NULL, joined_on DATE NOT NULL, status TEXT NOT NULL) ENGINE=InnoDB;\n",
            f"CREATE TABLE `{records}` (id INT PRIMARY KEY, person_id INT NOT NULL, reference TEXT NOT NULL, amount_minor INT NOT NULL, status TEXT NOT NULL, destination TEXT NOT NULL, created_on DATE NOT NULL, note TEXT NULL, KEY(person_id)) ENGINE=InnoDB;\n",
            f"CREATE TABLE `{lines}` (record_id INT NOT NULL, line_no INT NOT NULL, description TEXT NOT NULL, quantity INT NOT NULL, unit_minor INT NOT NULL, PRIMARY KEY(record_id,line_no)) ENGINE=InnoDB;\n",
            f"CREATE TABLE `{ledger}` (id INT PRIMARY KEY, record_id INT NOT NULL, amount_minor INT NOT NULL, channel TEXT NOT NULL, reference TEXT NOT NULL, booked_on DATE NOT NULL, KEY(record_id)) ENGINE=InnoDB;\n",
            f"CREATE TABLE `{staff}` (id INT PRIMARY KEY, full_name TEXT NOT NULL, role TEXT NOT NULL, enabled INT NOT NULL, branch TEXT NOT NULL) ENGINE=InnoDB;\n"]
    data = {t: [] for t in (people, records, lines, ledger, staff)}
    products = CATALOG.get(db, CATALOG["harbor_market"])
    for i in range(1, scale + 1):
        name = rng.choice(FIRST) + " " + rng.choice(LAST)
        date = f"2026-{1 + (i % 9):02d}-{1 + (i % 27):02d}"
        data[people].append((i, name, f"client{i:05d}@example.invalid", rng.choice(CITIES), date, "active"))
        price_a, price_b = rng.randrange(500, 20000), rng.randrange(500, 20000)
        qty = rng.randrange(1, 5)
        total = price_a * qty + price_b
        data[records].append((i, i, f"REF-2026-{i:06d}", total, "settled", f"LOCAL-{100000+i}", date, None if i % 7 == 0 else "Processed through branch service"))
        data[lines].extend([(i, 1, products[i % 5], qty, price_a), (i, 2, products[(i+1) % 5], 1, price_b)])
        # Two genuine installment payments equal the header total.
        data[ledger].extend([(2*i-1, i, total//2, "bank", f"TX-{2*i-1:07d}", date),
                             (2*i, i, total-total//2, "card", f"TX-{2*i:07d}", date)])
    for i in range(1, max(100, scale // 5) + 1):
        data[staff].append((i, rng.choice(FIRST)+" "+rng.choice(LAST), "supervisor" if i % 20 == 0 else "clerk", 1, CITIES[i % len(CITIES)]))
    if not clean:
        sql += ["CREATE TABLE access_notes (actor TEXT, action TEXT, source_ip TEXT, recorded_at DATETIME) ENGINE=InnoDB;\n",
                "CREATE TABLE documents (id INT PRIMARY KEY, title VARCHAR(120), content BLOB, metadata JSON, amount DECIMAL(12,2), risk_score DOUBLE) ENGINE=InnoDB;\n"]
        data["access_notes"] = [(f"operator-{i%20+1}", "session opened", f"192.0.2.{i%200+1}", f"2026-09-{i%27+1:02d} 09:30:00") for i in range(1, 501)]
        # Contains only invented document text; no real credentials or PII.
        data["documents"] = [(i, f"Statement {i:04d}", f"Fictional statement for reference {i:06d}", json.dumps({"reference": i, "reviewed": True}), "125.50", "0.125") for i in range(1, 301)]
    for table, rows in data.items():
        for offset in range(0, len(rows), 250):
            sql.append(insert(table, rows[offset:offset+250]))
    return "".join(sql), {table: len(rows) for table, rows in data.items()}


def attacks(spec):
    _, db, _, people, records, lines, ledger, staff = spec
    return f"""USE `{db}`;
-- Logged malicious activity: reconstructable, not itself proof of mismatch.
START TRANSACTION;
UPDATE `{records}` SET destination='EXT-887711', note='Beneficiary changed via compromised operator session' WHERE id BETWEEN 101 AND 160;
UPDATE `{staff}` SET role='administrator', enabled=1 WHERE id IN (7,19);
UPDATE `{people}` SET email='collection@example.invalid' WHERE id BETWEEN 201 AND 230;
UPDATE `{ledger}` SET channel='manual override' WHERE id BETWEEN 401 AND 420;
COMMIT;
DELETE FROM `{ledger}` WHERE id BETWEEN 601 AND 620;
UPDATE `{lines}` SET line_no=3 WHERE record_id=10 AND line_no=2;
DELETE FROM `{records}` WHERE id=50;
INSERT INTO `{records}` VALUES (50,50,'REUSED-000050',890000,'settled','EXT-887711','2026-10-06','Replacement record under a recycled key');
-- Row-image coverage limit, not evidence that MINIMAL is malicious.
SET SESSION binlog_row_image='MINIMAL';
UPDATE `{records}` SET note='Manual review bypassed' WHERE id BETWEEN 301 AND 310;
SET SESSION binlog_row_image='FULL';
-- A rolled-back InnoDB transaction is not written as durable row events.
START TRANSACTION;
UPDATE `{records}` SET amount_minor=1 WHERE id=91;
ROLLBACK;
UPDATE access_notes SET action='session opened (redacted)' WHERE actor='operator-7';
UPDATE documents SET metadata=JSON_OBJECT('reference',1,'reviewed',FALSE), content='Altered synthetic attachment' WHERE id=1;
FLUSH BINARY LOGS;
-- Privileged attacker disables logging for only this private lab session.
SET SESSION sql_log_bin=0;
UPDATE `{records}` SET amount_minor=99999999, destination='EXT-441199', status='waived' WHERE id BETWEEN 11 AND 20;
UPDATE `{staff}` SET role='administrator' WHERE id IN (8,9);
UPDATE `{people}` SET email='shadow@example.invalid' WHERE id BETWEEN 31 AND 40;
DELETE FROM `{ledger}` WHERE id BETWEEN 81 AND 90;
INSERT INTO `{records}` VALUES (900001,12,'UNLOGGED-900001',4700000,'settled','EXT-441199','2026-10-06','Off-ledger fabricated record');
UPDATE `{records}` SET amount_minor=777777 WHERE id=71;
SET SESSION sql_log_bin=1;
-- This before-image proves an unobserved transition even with a complete index.
UPDATE `{records}` SET note='Receipt reissued after manual adjustment' WHERE id=71;
"""


def event_headers(path):
    payload = path.read_bytes()
    assert payload[:4] == b"\xfebin", f"Invalid binlog magic: {path}"
    events, offset = [], 4
    while offset < len(payload):
        assert offset + 19 <= len(payload), f"Partial header in {path}"
        _, kind, _, size, _, _ = struct.unpack_from("<IBIIIH", payload, offset)
        assert size >= 19 and offset + size <= len(payload), f"Partial event in {path}"
        events.append((offset, kind, size))
        offset += size
    return events


def alter_acquisition(subject, mode, table):
    logs = sorted((subject / "binlog").glob("mysql-bin.[0-9]*"))
    mutations = []
    if mode == 2:
        missing = logs[1]
        mutations.append({"type": "omitted_binlog", "file": missing.name,
                          "original_sha256": hashlib.sha256(missing.read_bytes()).hexdigest()})
        # Only the newly generated, explicitly named lab artifact is removed.
        missing.unlink()
    elif mode == 3:
        last = logs[-1]
        xid = [e for e in event_headers(last) if e[1] == 16][-1]
        original = last.read_bytes()
        last.write_bytes(original[:xid[0]])
        mutations.append({"type": "removed_final_commit_and_tail", "file": last.name,
                          "cut_offset": xid[0], "original_size": len(original),
                          "original_sha256": hashlib.sha256(original).hexdigest()})
    elif mode == 4:
        path = subject / "ibd" / f"{table}.ibd"
        original = path.read_bytes()
        page = next(i for i in range(4, len(original)//16384)
                    if int.from_bytes(original[i*16384+24:i*16384+26], "big") == 17855)
        # Flip the stored checksum, preserving SDI and row bytes for extraction.
        damaged = bytearray(original)
        damaged[page*16384] ^= 0x80
        path.write_bytes(damaged)
        mutations.append({"type": "page_checksum_damage", "file": path.name, "page": page,
                          "byte_offset": page*16384,
                          "original_sha256": hashlib.sha256(original).hexdigest()})
    elif mode == 5:
        path = subject / "ibd" / f"{table}.ibd"
        mutations.append({"type": "omitted_tablespace", "file": path.name,
                          "original_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        path.unlink()
        index = subject / "binlog" / "mysql-bin.index"
        mutations.append({"type": "omitted_index", "file": index.name})
        index.unlink()
    return mutations


def checklist(spec, mode, counts, mutations):
    folder, db, title, people, records, lines, ledger, staff = spec
    text = f"# {title}: expected findings\n\nAll identities, addresses, documents and money are fictional. Currency is stored in minor units.\n\n"
    text += f"Database: `{db}`. Seeded rows: **{sum(counts.values()):,}**. See `manifest.json` for acquired row counts, hashes and exact acquisition mutations; `baseline.sql` and `activity.sql` contain every generated change.\n\n"
    text += "## Import\n\nCreate a separate case. Import every file in `ibd/` and `binlog/`, including `mysql-bin.index` when present. Do not import the SQL or manifests as evidence. Start with deleted-row extraction disabled; enable it in a second case to explore purge-dependent remnants.\n\n"
    if mode == 6:
        return text + f"""## Clean-control acceptance checklist

- [ ] Every acquired `.ibd` passes innochecksum; all binlogs decode with valid event checksums.
- [ ] The index lists exactly the supplied logs, with no missing sequence members.
- [ ] Every row event belongs to a committed transaction; no incomplete groups.
- [ ] All {sum(counts.values()):,} live rows have log histories and primary-key identities, including the composite keys in `{lines}`.
- [ ] Final live values and presence agree: no Conflicting or Unresolved records, unsupported fields, checksum failures, or unexpected warning findings when deleted-row extraction is off.
- [ ] Both installment payments sum to the associated header total. There are no injected business errors.
- [ ] Routine changes to `{records}` 401-450 are fully logged and reconcile normally; `{records}` 91 retains its original amount after a rollback.

This control intentionally uses INT/TEXT/DATE instead of parameterized VARCHAR/DECIMAL, JSON, BLOB or FLOAT because the current engine has decoding/supported-type limits for those types. Dates and names still look like a normal business database. Benign informational findings do not make the database erroneous. MySQL omits rolled-back InnoDB row events, so no rolled-back group should be invented.

If the app flags R-GRP-013 on these ordinary multi-row inserts, that is an engine defect: different rows legitimately share one event position. The current engine retains only the first row per position and reports the other rows as unresolved. `APP_VALIDATION.md`, when present, records this failing control separately from the clean database's expected outcome.
"""
    incomplete = mode in (2, 3, 5)
    comparison = "Unresolved where coverage is incomplete (R-RECON-004); never assert tampering solely from the difference" if incomplete else "Conflicting (R-RECON-003), with physical values absent from observed history (R-RECON-031)"
    text += f"""## Injected errors and attack evidence (complete list)

| Check | Exact target / expected evidence | Expected handling |
|---|---|---|
| [ ] Hidden financial rewrite | `{records}` IDs 11-20: amount_minor=99999999, destination=EXT-441199, status=waived; changes made with sql_log_bin=0 | {comparison} |
| [ ] Hidden privilege escalation | `{staff}` IDs 8 and 9: clerk to administrator without row events | {comparison} |
| [ ] Hidden contact takeover | `{people}` IDs 31-40: email=shadow@example.invalid without row events | {comparison} |
| [ ] Hidden deletion | `{ledger}` IDs 81-90 physically absent but still present in committed log state | Presence conflict R-RECON-021 with complete coverage, otherwise R-RECON-022; check live records, not purge-dependent remnants |
| [ ] Fabricated record | `{records}` ID 900001 exists only in the tablespace | R-CORR-031; conflict with complete coverage, otherwise unresolved |
| [ ] Broken business totals | `{records}` IDs 11-20, 50 and 71 disagree with original line/installment totals; parent IDs 41-45 and 301-310 lost installment rows; ID 900001 has no line/payment support | Ground-truth business errors for manual review: the current engine compares forensic evidence, not arbitrary cross-table accounting rules |
| [ ] Hidden history discontinuity | `{records}` ID 71 silently changes amount_minor to 777777, then a logged note update exposes the new before-image | R-HIST-008; final values may agree, so the history warning is essential |
| [ ] Logged beneficiary diversion | `{records}` IDs 101-160: destination=EXT-887711 | Visible update history; consistent logged attacks can reconcile Exact and need examiner review |
| [ ] Logged privilege escalation | `{staff}` IDs 7 and 19: role=administrator | Visible update history; the app does not determine who was authorized |
| [ ] Logged contact harvesting/redirect | `{people}` IDs 201-230: email=collection@example.invalid | Visible mass-update history; data exfiltration itself is not proved by these files |
| [ ] Logged payment manipulation | `{ledger}` IDs 401-420: channel=manual override | Visible update history |
| [ ] Logged destructive deletion | `{ledger}` IDs 601-620 deleted | Deletion histories; a matching deletion is not a reconciliation conflict |
| [ ] Primary-key rewrite | `{lines}` key (10,2) becomes (10,3) | R-CORR-010 and R-HIST-011; composite key correlation R-CORR-002 |
| [ ] Identity reuse | `{records}` ID 50 deleted and reinserted with reference REUSED-000050 | R-CORR-012; interval of absence followed by a new row |
| [ ] Partial images | `{records}` IDs 301-310 get note-only updates under MINIMAL | R-HIST-007; omitted columns must not become NULL/zero; Strong or other conservative result where applicable |
| [ ] No primary key / audit redaction | `access_notes`: 500 rows, operator-7 actions rewritten | R-CORR-020, Unsupported identity; never invent an InnoDB hidden row ID |
| [ ] Rich/unsupported values | `documents`: 300 rows with VARCHAR(120), BLOB, JSON, DECIMAL(12,2), DOUBLE; document 1 altered | R-RECON-008 / decode warnings as applicable; do not manufacture equality for unsupported values |

## Benign controls mixed into the attack

`{records}` 91 was updated inside a rolled-back transaction: its durable amount stays unchanged. MySQL does not persist those row events, so the app cannot infer the attempted write or invent a rollback history. Unaffected rows have normal names, regional branches, dates, business references and two installment entries that sum to the header amount. SQL sources are ground truth for the scenario, not evidence supplied to the app.

"""
    additions = {
        1: "Complete acquisition: all supplied files are structurally valid. The hidden-write differences should be actionable conflicts. This subject isolates semantic tampering from file corruption and coverage loss.",
        2: "`mysql-bin.000002` was intentionally withheld, while the original server index still lists it. Expect R-COV-002 (missing file) and conservative coverage/history handling. Logged diversion, escalation and deletion occurred in that withheld file, so they cannot be recovered from this acquisition; never claim to have observed them. No other file is damaged.",
        3: f"The final binlog ends immediately before the final Xid commit event, at a complete event boundary. The open multi-table transaction changes `{records}` 81-85 to status='held' and `{staff}` 25 to role='administrator'; MySQL committed them but the acquisition has no commit. Expect R-GRP-004, R-COV-003 and R-HIST-006, incomplete status and no application of these events to durable reconstructed state. mysqlbinlog may print a synthetic end-of-output ROLLBACK; the app must not mistake that utility safeguard for an observed rollback event.",
        4: f"One index page in `{ledger}.ibd` has an altered stored checksum. Row payload and SDI are intact. Expect innochecksum damage and conservative handling (R-RECON-009) for physical values from that tablespace. Other `.ibd` files must still validate. A pipeline that stops at integrity validation must expose the failure; an app that continues must preserve the damaged provenance.",
        5: f"`{ledger}.ibd` and `mysql-bin.index` were deliberately not acquired. Logs still reference `{ledger}`. Expect R-COV-001 and schema/out-of-scope warnings (R-CORR-021/R-CORR-030 or adapter schema warnings). No physical ledger values may be invented. Remaining binlogs are complete and checksummed, but their total coverage cannot be established without the index.",
    }
    text += "## Subject-specific evidence error\n\n" + additions[mode] + "\n\n"
    text += "Exact byte-level modifications / omissions:\n\n```json\n" + json.dumps(mutations, indent=2) + "\n```\n\n"
    text += "## Limits of the evidence\n\nThese fixtures cover row manipulation, fraud, privilege-field changes, audit tampering, anti-forensic log loss, transaction boundaries, page damage, schema scope, partial images and unsupported types. They do not prove SQL injection, credential theft, network exfiltration, denial of service, execution of malware, server-account GRANT changes, or an attacker's identity: those require application/access/network/host logs or system-table evidence. A row-based binlog generally cannot recover the original injected SQL. Keyless and rich-type tables are ordinary schema features; their warnings describe analysis limitations, not attacks. Purge-dependent deleted remnants are optional observations, never mandatory pass criteria.\n"
    text += "\nKnown current-engine limitation: multi-row inserts legitimately share a binlog event position. R-GRP-013 currently discards all but the first image at that position, so many baseline histories and intended attack comparisons can be missed. The checklist above states the correct acceptance behavior, not a promise that the current implementation already passes it. See the lab README and any APP_VALIDATION.md report for observed results.\n"
    return text


def validate(server, subject, mode, damaged_table):
    results = {"ibd": {}, "binlog": {}}
    for path in sorted((subject / "ibd").glob("*.ibd")):
        check = subprocess.run([server.command("innochecksum"), str(path)], capture_output=True)
        sdi = subprocess.run([server.command("ibd2sdi"), str(path)], capture_output=True)
        assert sdi.returncode == 0, sdi.stderr.decode(errors="replace")
        expected_damage = mode == 4 and path.stem == damaged_table
        assert (check.returncode != 0) == expected_damage, (path, check.stderr)
        results["ibd"][path.name] = {"checksum_valid": check.returncode == 0, "sdi_readable": True,
                                     "diagnostic": check.stderr.decode(errors="replace").strip()}
    for path in sorted((subject / "binlog").glob("mysql-bin.[0-9]*")):
        events = event_headers(path)
        decoded = subprocess.run([server.command("mysqlbinlog"), "--no-defaults", "--verify-binlog-checksum",
                                  "-vv", "--base64-output=DECODE-ROWS", str(path)], capture_output=True)
        assert decoded.returncode == 0, decoded.stderr.decode(errors="replace")
        results["binlog"][path.name] = {"checksum_valid": True, "event_count": len(events),
                                        "row_images": decoded.stdout.count(b"### INSERT INTO") + decoded.stdout.count(b"### UPDATE") + decoded.stdout.count(b"### DELETE FROM"),
                                        "diagnostic": decoded.stderr.decode(errors="replace").strip()}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "subjects")
    parser.add_argument("--scale", type=int, default=2500, help="Main business records per database (minimum 500)")
    parser.add_argument("--port", type=int, default=34317)
    args = parser.parse_args()
    if args.scale < 500:
        parser.error("--scale must be at least 500 to include all target IDs")
    output = args.output.resolve()
    if output.exists():
        parser.error(f"Refusing to overwrite existing subjects: {output}")
    output.mkdir(parents=True)
    server = LabServer(args.mysql_bin.resolve(), ROOT / ".scratch" / datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S"), args.port)
    summaries = []
    try:
        print("Initializing isolated MySQL lab...", flush=True)
        server.initialize()
        for mode, spec in enumerate(SUBJECTS, 1):
            folder, db, title, people, records, lines, ledger, staff = spec
            subject = output / folder
            (subject / "ibd").mkdir(parents=True)
            (subject / "binlog").mkdir()
            server.start()
            # RESET MASTER only affects this generator's own, newly initialized server.
            server.sql("RESET MASTER;")
            seed = 20261007 + mode
            sql, counts = baseline(spec, args.scale, seed, mode == 6)
            (subject / "baseline.sql").write_text(sql, encoding="utf-8")
            print(f"{folder}: inserting {sum(counts.values()):,} baseline rows...", flush=True)
            server.sql(sql)
            server.sql("FLUSH BINARY LOGS;")
            if mode == 6:
                activity = f"USE `{db}`; START TRANSACTION; UPDATE `{records}` SET note='Receipt checked by branch supervisor' WHERE id BETWEEN 401 AND 450; COMMIT; START TRANSACTION; UPDATE `{records}` SET amount_minor=1 WHERE id=91; ROLLBACK; FLUSH BINARY LOGS;"
            else:
                activity = attacks(spec)
                if mode == 3:
                    activity += f"START TRANSACTION; UPDATE `{records}` SET status='held' WHERE id BETWEEN 81 AND 85; UPDATE `{staff}` SET role='administrator' WHERE id=25; COMMIT;\n"
            (subject / "activity.sql").write_text(activity, encoding="utf-8")
            server.sql(activity)
            live_counts = {table: int(server.sql(f"SELECT COUNT(*) FROM `{db}`.`{table}`;").strip()) for table in counts}
            server.stop()
            # A clean shutdown gives a stable, flushed snapshot of both formats.
            for path in (server.data / db).glob("*.ibd"):
                shutil.copy2(path, subject / "ibd" / path.name)
            for path in server.data.glob("mysql-bin.*"):
                shutil.copy2(path, subject / "binlog" / path.name)
            mutations = alter_acquisition(subject, mode, ledger)
            results = validate(server, subject, mode, ledger)
            files = [{"path": path.relative_to(subject).as_posix(), "bytes": path.stat().st_size,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                     for directory in (subject / "ibd", subject / "binlog") for path in sorted(directory.iterdir())]
            manifest = {"subject": folder, "database": db, "title": title, "seed": seed,
                        "mysql_version": subprocess.check_output([server.command("mysqld"), "--version"]).decode().strip(),
                        "acquisition": "clean private-server shutdown, followed by listed acquisition mutations",
                        "acquired_at_utc": datetime.now(timezone.utc).isoformat(), "binlog_format": "ROW", "default_row_image": "FULL",
                        "page_size": 16384, "baseline_rows": counts, "source_live_rows": live_counts,
                        "acquisition_mutations": mutations, "files": files, "utility_validation": results}
            (subject / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
            (subject / "EXPECTED_FINDINGS.md").write_text(checklist(spec, mode, counts, mutations), encoding="utf-8")
            size = sum(item["bytes"] for item in files)
            summaries.append({"subject": folder, "seeded_rows": sum(counts.values()), "source_live_rows": sum(live_counts.values()),
                              "ibd_files": len(results["ibd"]), "binlog_files": len(results["binlog"]), "evidence_bytes": size})
            print(f"{folder}: validated {len(results['ibd'])} tablespaces, {len(results['binlog'])} binlogs; {size/1048576:.1f} MiB", flush=True)
    finally:
        server.stop()
    (output / "summary.json").write_text(json.dumps(summaries, indent=2)+"\n", encoding="utf-8")
    print(f"Complete: {output}", flush=True)


if __name__ == "__main__":
    main()
