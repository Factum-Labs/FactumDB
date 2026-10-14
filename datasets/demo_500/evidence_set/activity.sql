USE demo_market;
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
