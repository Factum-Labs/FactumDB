-- FactumDB test scenario 1: one account opened, then changed twice.
--
-- Written from the row events in the scenario's copied binlog; the original
-- session was not saved. Run as root on a test server (MySQL 8.4,
-- binlog_format=ROW) it gives the same rows. File names, positions, GTIDs
-- and times will differ from the reference copy.

FLUSH BINARY LOGS;              -- the scenario starts in a fresh binlog file

DROP DATABASE IF EXISTS finance;
CREATE DATABASE finance;
USE finance;

CREATE TABLE accounts (
    account_id INT PRIMARY KEY,
    owner      VARCHAR(100),
    balance    INT,
    status     VARCHAR(20)
) ENGINE=InnoDB;

-- 1. The account as it was opened.
INSERT INTO accounts VALUES (101, 'Amal', 5000, 'active');

-- 2. and 3. The two changes under investigation: the balance lowered, then the
--    account suspended. The page keeps only the final row; the earlier values
--    survive in the binlog alone.
UPDATE accounts SET balance = 4000 WHERE account_id = 101;
UPDATE accounts SET status = 'suspended' WHERE account_id = 101;

FLUSH BINARY LOGS;              -- close the scenario's binlog file
