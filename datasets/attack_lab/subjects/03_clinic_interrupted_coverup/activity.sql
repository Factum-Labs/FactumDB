USE `maple_clinic`;
-- Logged malicious activity: reconstructable, not itself proof of mismatch.
START TRANSACTION;
UPDATE `visits` SET destination='EXT-887711', note='Beneficiary changed via compromised operator session' WHERE id BETWEEN 101 AND 160;
UPDATE `operators` SET role='administrator', enabled=1 WHERE id IN (7,19);
UPDATE `patients` SET email='collection@example.invalid' WHERE id BETWEEN 201 AND 230;
UPDATE `billing` SET channel='manual override' WHERE id BETWEEN 401 AND 420;
COMMIT;
DELETE FROM `billing` WHERE id BETWEEN 601 AND 620;
UPDATE `visit_services` SET line_no=3 WHERE record_id=10 AND line_no=2;
DELETE FROM `visits` WHERE id=50;
INSERT INTO `visits` VALUES (50,50,'REUSED-000050',890000,'settled','EXT-887711','2026-10-06','Replacement record under a recycled key');
-- Row-image coverage limit, not evidence that MINIMAL is malicious.
SET SESSION binlog_row_image='MINIMAL';
UPDATE `visits` SET note='Manual review bypassed' WHERE id BETWEEN 301 AND 310;
SET SESSION binlog_row_image='FULL';
-- A rolled-back InnoDB transaction is not written as durable row events.
START TRANSACTION;
UPDATE `visits` SET amount_minor=1 WHERE id=91;
ROLLBACK;
UPDATE access_notes SET action='session opened (redacted)' WHERE actor='operator-7';
UPDATE documents SET metadata=JSON_OBJECT('reference',1,'reviewed',FALSE), content='Altered synthetic attachment' WHERE id=1;
FLUSH BINARY LOGS;
-- Privileged attacker disables logging for only this private lab session.
SET SESSION sql_log_bin=0;
UPDATE `visits` SET amount_minor=99999999, destination='EXT-441199', status='waived' WHERE id BETWEEN 11 AND 20;
UPDATE `operators` SET role='administrator' WHERE id IN (8,9);
UPDATE `patients` SET email='shadow@example.invalid' WHERE id BETWEEN 31 AND 40;
DELETE FROM `billing` WHERE id BETWEEN 81 AND 90;
INSERT INTO `visits` VALUES (900001,12,'UNLOGGED-900001',4700000,'settled','EXT-441199','2026-10-06','Off-ledger fabricated record');
UPDATE `visits` SET amount_minor=777777 WHERE id=71;
SET SESSION sql_log_bin=1;
-- This before-image proves an unobserved transition even with a complete index.
UPDATE `visits` SET note='Receipt reissued after manual adjustment' WHERE id=71;
START TRANSACTION; UPDATE `visits` SET status='held' WHERE id BETWEEN 81 AND 85; UPDATE `operators` SET role='administrator' WHERE id=25; COMMIT;
