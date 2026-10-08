-- Catalog-only schema: credentials must never travel with forensic case exports.
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    salt BLOB NOT NULL CHECK(length(salt) = 16),
    password_hash BLOB NOT NULL CHECK(length(password_hash) = 32),
    password_algorithm TEXT NOT NULL DEFAULT 'scrypt-n32768-r8-p3',
    device_identity TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS auth_throttle (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    failures INTEGER NOT NULL DEFAULT 0,
    blocked_until REAL NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO auth_throttle(id) VALUES (1);
