-- FactumDB test scenario 2: scenario 1, then two more accounts and a delete.
--
-- Written from the row events in the scenario's copied binlogs; the original
-- session was not saved. Run as root on a test server (MySQL 8.4,
-- binlog_format=ROW) it gives the same rows. File names, positions, GTIDs
-- and times will differ from the reference copy, where server restarts
-- between steps 3 and 4 left the empty logs mysql-bin.000002 to 000005.

FLUSH BINARY LOGS;

DROP DATABASE IF EXISTS finance;
CREATE DATABASE finance;
USE finance;

CREATE TABLE accounts (
    account_id INT PRIMARY KEY,
    owner      VARCHAR(100),
    balance    INT,
    status     VARCHAR(20)
) ENGINE=InnoDB;

-- 1. to 3. Scenario 1.
INSERT INTO accounts VALUES (101, 'Amal', 5000, 'active');
UPDATE accounts SET balance = 4000 WHERE account_id = 101;
UPDATE accounts SET status = 'suspended' WHERE account_id = 101;

-- 4. Two more accounts.
INSERT INTO accounts VALUES (102, 'Nimal', 7500, 'active');
INSERT INTO accounts VALUES (103, 'Kamal', 3200, 'active');

-- 5. One of them deleted. InnoDB only sets a delete flag on the record, so
--    until purge runs the row is still on the page for ibd2sql --delete only.
DELETE FROM accounts WHERE account_id = 102;

FLUSH BINARY LOGS;
