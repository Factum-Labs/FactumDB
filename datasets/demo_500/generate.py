"""Create genuine MySQL evidence for the five-minute evaluation demonstration.

Only uses a newly initialized private server; refuses to overwrite evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'attack_lab'))
from generate import LabServer, insert, validate


def baseline():
    sql = ["CREATE DATABASE demo_market CHARACTER SET utf8mb4 COLLATE utf8mb4_bin; USE demo_market;\n"]
    definitions = {
        'customers': 'id INT PRIMARY KEY, full_name TEXT NOT NULL, email TEXT NOT NULL, city TEXT NOT NULL',
        'orders': 'id INT PRIMARY KEY, customer_id INT NOT NULL, amount_minor INT NOT NULL, status TEXT NOT NULL, destination TEXT NOT NULL, note TEXT NULL',
        'order_lines': 'order_id INT NOT NULL, line_no INT NOT NULL, description TEXT NOT NULL, amount_minor INT NOT NULL, PRIMARY KEY(order_id,line_no)',
        'payments': 'id INT PRIMARY KEY, order_id INT NOT NULL, amount_minor INT NOT NULL, channel TEXT NOT NULL',
        'staff': 'id INT PRIMARY KEY, full_name TEXT NOT NULL, role TEXT NOT NULL',
    }
    rows = {table: [] for table in definitions}
    for i in range(1, 81):
        # Two lines and two payments each sum to the order total, in minor units.
        amount = 10000 + 100 * i
        rows['customers'].append((i, f'Fictional Customer {i:03}', f'customer{i:03}@example.invalid', ['Colombo', 'Kandy', 'Galle'][i % 3]))
        rows['orders'].append((i, i, amount, 'settled', f'LOCAL-{100000+i}', 'Branch sale'))
        rows['order_lines'].extend([(i, 1, 'Desk lamp', amount // 2), (i, 2, 'Notebook set', amount // 2)])
        rows['payments'].extend([(2*i-1, i, amount // 2, 'bank'), (2*i, i, amount // 2, 'card')])
    rows['staff'] = [(i, f'Fictional Operator {i:02}', 'supervisor' if i == 20 else 'clerk') for i in range(1, 21)]
    for table, definition in definitions.items():
        sql.append(f'CREATE TABLE `{table}` ({definition}) ENGINE=InnoDB;\n')
        sql.append(insert(table, rows[table]))
    return ''.join(sql), {table: len(data) for table, data in rows.items()}


ACTIVITY = """USE demo_market;
-- Logged changes: observable history, consistent with the final pages.
START TRANSACTION;
UPDATE orders SET destination='EXT-887711', note='Beneficiary changed' WHERE id=10;
UPDATE staff SET role='administrator' WHERE id=7;
COMMIT;
UPDATE orders SET note='Receipt verified' WHERE id=10;
DELETE FROM payments WHERE id=30;
UPDATE order_lines SET line_no=3 WHERE order_id=10 AND line_no=2;
DELETE FROM orders WHERE id=50;
INSERT INTO orders VALUES (50,50,15000,'settled','LOCAL-100050','Replacement after cancellation');
SET SESSION binlog_row_image='MINIMAL';
UPDATE orders SET note='Supervisor reviewed' WHERE id=60;
SET SESSION binlog_row_image='FULL';
-- This rolled-back attempted write leaves no durable row-binlog event.
START TRANSACTION;
UPDATE orders SET amount_minor=1 WHERE id=40;
ROLLBACK;
FLUSH BINARY LOGS;
-- Controlled hidden writes, only on this private synthetic server.
SET SESSION sql_log_bin=0;
UPDATE orders SET amount_minor=999999, destination='EXT-441199', status='waived' WHERE id=20;
UPDATE customers SET email='shadow@example.invalid' WHERE id=31;
UPDATE staff SET role='administrator' WHERE id=8;
DELETE FROM payments WHERE id=25;
INSERT INTO orders VALUES (900001,12,4700000,'settled','EXT-441199','Unlogged fabricated order');
UPDATE orders SET amount_minor=777777 WHERE id=71;
SET SESSION sql_log_bin=1;
-- The before-image exposes the unobserved transition on order 71.
UPDATE orders SET note='Receipt reissued' WHERE id=71;
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mysql-bin', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence_set')
    parser.add_argument('--port', type=int, default=34318)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error(f'Refusing to overwrite {output}; choose a fresh --output')
    output.mkdir(parents=True)
    for name in ('ibd', 'binlog'):
        (output / name).mkdir()
    server = LabServer(args.mysql_bin.resolve(), ROOT / '.scratch' / datetime.now(timezone.utc).strftime('run-%Y%m%d-%H%M%S-%f'), args.port)
    try:
        print('Initializing private MySQL server...', flush=True)
        server.initialize()
        server.start()
        server.sql('RESET MASTER;')
        sql, counts = baseline()
        assert sum(counts.values()) == 500
        (output / 'baseline.sql').write_text(sql, encoding='utf-8')
        (output / 'activity.sql').write_text(ACTIVITY, encoding='utf-8')
        server.sql(sql)
        server.sql('FLUSH BINARY LOGS;')
        server.sql(ACTIVITY)
        live = {table: int(server.sql(f'SELECT COUNT(*) FROM demo_market.`{table}`;').strip()) for table in counts}
        server.stop()
        for path in (server.data / 'demo_market').glob('*.ibd'):
            shutil.copy2(path, output / 'ibd' / path.name)
        for path in server.data.glob('mysql-bin.*'):
            shutil.copy2(path, output / 'binlog' / path.name)
        checks = validate(server, output, 1, 'payments')
        files = [{'path': p.relative_to(output).as_posix(), 'bytes': p.stat().st_size,
                  'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                 for folder in ('ibd', 'binlog') for p in sorted((output / folder).iterdir())]
        manifest = {'database': 'demo_market', 'baseline_rows': counts, 'source_live_rows': live,
                    'mysql_version': subprocess.check_output([server.command('mysqld'), '--version']).decode().strip(),
                    'acquired_at_utc': datetime.now(timezone.utc).isoformat(),
                    'acquisition': 'Clean private-server shutdown; no binary corruption or omitted logs.',
                    'binlog_format': 'ROW', 'default_row_image': 'FULL', 'include_deleted_for_demo': False,
                    'files': files, 'utility_validation': checks}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
        print(f'Generated 500 starting rows; {sum(live.values())} final live rows; {sum(f["bytes"] for f in files):,} evidence bytes. {output}', flush=True)
    finally:
        server.stop()


if __name__ == '__main__':
    main()
