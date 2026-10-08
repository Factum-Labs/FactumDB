"""Accounts live in the application catalog, never in exported case databases."""

import sqlite3
from pathlib import Path


class SqliteAccountStore:
    def __init__(self, connection):
        self.connection = connection
        connection.executescript(
            Path(__file__).with_name("accounts.sql").read_text(encoding="utf-8")
        )

    def find(self, key):
        row = self.connection.execute(
            "SELECT * FROM users WHERE username_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return {
            name: row[name]
            for name in ("user_id", "username", "salt", "password_hash", "device_identity")
        }

    def create(self, username, key, salt, digest, identity):
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO users "
                    "(username, username_key, salt, password_hash, device_identity) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username, key, salt, digest, identity),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("Username is already registered") from error

    def throttle(self):
        row = self.connection.execute(
            "SELECT failures, blocked_until FROM auth_throttle WHERE id = 1"
        ).fetchone()
        return row["failures"], row["blocked_until"]

    def set_throttle(self, failures, until):
        with self.connection:
            self.connection.execute(
                "UPDATE auth_throttle SET failures = ?, blocked_until = ? WHERE id = 1",
                (failures, until),
            )
