"""Accounts live in the application catalog, never in exported case databases."""

import json
import sqlite3
from pathlib import Path

from core.application.preferences import DEFAULTS


class SqliteAccountStore:
    def __init__(self, connection):
        self.connection = connection
        connection.executescript(
            Path(__file__).with_name("accounts.sql").read_text(encoding="utf-8")
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        for name in ("profile_json", "preferences_json"):
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE users ADD COLUMN {name} TEXT NOT NULL DEFAULT '{{}}'"
                )
        # Keep persisted preferences aligned with the supported settings schema,
        # including when reopening a catalog restored from an older backup.
        for row in connection.execute(
            "SELECT username_key, preferences_json FROM users"
        ).fetchall():
            saved = json.loads(row["preferences_json"])
            supported = {key: value for key, value in saved.items() if key in DEFAULTS}
            if supported != saved:
                connection.execute(
                    "UPDATE users SET preferences_json = ? WHERE username_key = ?",
                    (json.dumps(supported), row["username_key"]),
                )
        connection.commit()

    def details(self, key):
        row = self.connection.execute(
            "SELECT profile_json, preferences_json FROM users WHERE username_key = ?", (key,)
        ).fetchone()
        return {"profile": json.loads(row[0]), "preferences": json.loads(row[1])}

    def save_details(self, key, *, profile=None, preferences=None):
        with self.connection:
            for column, value in (("profile_json", profile), ("preferences_json", preferences)):
                if value is not None:
                    self.connection.execute(
                        f"UPDATE users SET {column} = ? WHERE username_key = ?",
                        (json.dumps(value), key),
                    )

    def change_password(self, key, salt, digest):
        with self.connection:
            self.connection.execute(
                "UPDATE users SET salt = ?, password_hash = ? WHERE username_key = ?",
                (salt, digest, key),
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
