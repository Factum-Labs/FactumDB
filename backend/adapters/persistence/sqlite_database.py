"""Opening and setting up the SQLite case database.

Everything FactumDB extracts goes into one SQLite file per case. This module
is the only place that knows how to open it, so the two PRAGMAs below cannot
be forgotten by accident.

Both PRAGMAs have to be set on every single connection, not once on the file:

  foreign_keys - SQLite has foreign keys turned OFF by default. Every
  REFERENCES clause in schema.sql is parsed and then ignored unless this is
  on, which means the schema would look correct while enforcing nothing.

  journal_mode - WAL behaves better when something reads while something else
  writes. This one is actually stored in the file, but setting it again is
  harmless.

The tables themselves live in schema.sql next to this file. That file is the
executable copy of docs/sqlite-schema.md, and is the one the code runs.
"""

import sqlite3
from pathlib import Path

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def connect(db_path):
    """Open the case database with the settings the schema depends on.

    Returns a normal sqlite3.Connection. Rows come back as sqlite3.Row so
    columns can be read by name instead of by position - row["case_name"]
    rather than row[1], which stops a column reorder from silently changing
    what the code reads.
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialise(connection):
    """Create the tables if they are not there yet.

    schema.sql uses CREATE TABLE IF NOT EXISTS style statements via
    executescript, so running this on an existing database is safe.
    """
    connection.executescript(SCHEMA_FILE.read_text())
    connection.commit()


def open_case_database(db_path):
    """Open a case database and make sure the schema exists. Most callers
    want this rather than connect() and initialise() separately."""
    connection = connect(db_path)
    initialise(connection)
    return connection
