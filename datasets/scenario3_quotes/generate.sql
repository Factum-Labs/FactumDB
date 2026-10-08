-- FactumDB test scenario 3: scenario 2, then an owner name with a comma and
-- an apostrophe.
--
-- Written from the row events in the scenario's copied binlogs; the original
-- session was not saved. Run as root on a test server (MySQL 8.4,
-- binlog_format=ROW) it gives the same rows. File names, positions, GTIDs
-- and times will differ from the reference copy, where server restarts left
-- the empty logs mysql-bin.000007 to 000023 before step 6.

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

-- 1. to 5. Scenario 2.
INSERT INTO accounts VALUES (101, 'Amal', 5000, 'active');
UPDATE accounts SET balance = 4000 WHERE account_id = 101;
UPDATE accounts SET status = 'suspended' WHERE account_id = 101;
INSERT INTO accounts VALUES (102, 'Nimal', 7500, 'active');
INSERT INTO accounts VALUES (103, 'Kamal', 3200, 'active');
DELETE FROM accounts WHERE account_id = 102;

-- 6. Text a parser can easily get wrong. mysqlbinlog writes it as
--    'Perera, A. O\'Brien' and ibd2sql as "Perera, A. O'Brien"; both have to
--    come back as the same text, comma and apostrophe included.
INSERT INTO accounts VALUES (104, 'Perera, A. O''Brien', 9000, 'active');

FLUSH BINARY LOGS;
