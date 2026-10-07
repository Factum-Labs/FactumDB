-- FactumDB test scenario 4: data types, multi-row changes and composite keys.
--
-- Run as root on the test server (MySQL 8.4, binlog_format=ROW), then acquire
-- the evidence as described in README.md. Each numbered step is there to test
-- one thing the adapters have to get right; README.md lists what each checks.

FLUSH BINARY LOGS;              -- the scenario starts in a fresh binlog file
SET time_zone = '+05:30';       -- fixed, so TIMESTAMP values are predictable

DROP DATABASE IF EXISTS shop;
CREATE DATABASE shop;
USE shop;

-- One column of each common type the adapters have to decode.
CREATE TABLE payments (
    payment_id INT           NOT NULL PRIMARY KEY,
    customer   VARCHAR(50)   NOT NULL,
    currency   CHAR(3)       NOT NULL,
    amount     DECIMAL(12,2) NOT NULL,
    fee        DECIMAL(6,3)  NULL,
    status     ENUM('pending', 'paid', 'refunded') NOT NULL,
    paid_on    DATE          NULL,
    updated_at DATETIME      NULL,
    created_at TIMESTAMP     NULL,
    is_flagged TINYINT(1)    NOT NULL DEFAULT 0,
    note       TEXT          NULL
) ENGINE=InnoDB;

-- A composite primary key.
CREATE TABLE order_items (
    order_id INT         NOT NULL,
    line_no  INT         NOT NULL,
    sku      VARCHAR(20) NOT NULL,
    qty      INT         NOT NULL,
    PRIMARY KEY (order_id, line_no)
) ENGINE=InnoDB;

-- Types outside the validated scope: they have to be reported, never crash anything.
CREATE TABLE attachments (
    attachment_id INT  NOT NULL PRIMARY KEY,
    content       BLOB NULL,
    meta          JSON NULL
) ENGINE=InnoDB;

-- 1. Three rows in one INSERT: one binlog event, three row images.
INSERT INTO payments VALUES
    (1, 'Amal',  'LKR', 5000.00, 1.250, 'pending', NULL,         '2026-10-03 09:15:00', '2026-10-03 09:15:00', 0, 'first payment'),
    (2, 'Nimal', 'LKR', 7500.50, NULL,  'pending', NULL,         '2026-10-03 09:16:00', '2026-10-03 09:16:00', 0, NULL),
    (3, 'Kamal', 'USD', 3200.75, 0.500, 'paid',    '2026-10-01', '2026-10-03 09:17:00', '2026-10-03 09:17:00', 0, 'paid early');

-- 2. One UPDATE changing two rows (Amal and Nimal are both pending).
UPDATE payments SET status = 'paid', paid_on = '2026-10-03' WHERE status = 'pending';

-- 3. A decimal that a float cannot hold exactly, and a flag.
UPDATE payments SET amount = 4000.10, is_flagged = 1 WHERE payment_id = 1;

-- 4. A NULL becoming a value.
UPDATE payments SET fee = 2.000 WHERE payment_id = 2;

-- 5. A primary key change: the same row under a new key.
UPDATE payments SET payment_id = 30 WHERE payment_id = 3;

-- 6. One transaction across two tables.
START TRANSACTION;
UPDATE payments SET status = 'refunded' WHERE payment_id = 30;
INSERT INTO order_items VALUES (100, 1, 'SKU-A', 2), (100, 2, 'SKU-B', 1), (101, 1, 'SKU-A', 5);
COMMIT;

-- 7. Composite key: a value change, a key change and a delete.
UPDATE order_items SET qty = 3 WHERE order_id = 100 AND line_no = 1;
UPDATE order_items SET line_no = 3 WHERE order_id = 100 AND line_no = 2;
DELETE FROM order_items WHERE order_id = 101 AND line_no = 1;

-- 8. A partial row image: MINIMAL logs only the key and the changed column.
SET SESSION binlog_row_image = 'MINIMAL';
UPDATE payments SET note = 'checked' WHERE payment_id = 1;
SET SESSION binlog_row_image = 'FULL';

-- 9. Types outside the validated scope.
INSERT INTO attachments VALUES (1, 0x89504E470D0A1A0A, '{"pages": 2, "signed": true}');
UPDATE attachments SET meta = '{"pages": 3, "signed": false}' WHERE attachment_id = 1;

-- 10. A delete last, so the remnant is still on the page when the file is copied.
DELETE FROM payments WHERE payment_id = 2;

FLUSH BINARY LOGS;              -- close the scenario's binlog file
