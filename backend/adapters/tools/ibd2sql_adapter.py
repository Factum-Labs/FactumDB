"""Adapter for ibd2sql.

ibd2sql reads a .ibd file directly and prints the rows back out as INSERT
statements. Run normally it prints the live rows. Run with --delete only it
prints rows that have been deleted but are still sitting on the page, because
InnoDB only sets a delete flag in the record header and unlinks the record - it
does not wipe the bytes until purge reclaims the space.

We always pass --complete-insert so the output carries the column names:

    INSERT INTO `finance`.`accounts`(`account_id`,`owner`,`balance`,`status`)
    VALUES (102,'Nimal',7500,'active');

Without that flag the values are positional and we would have to assume the
order matches the schema. For a forensic tool it is better to read the names
the tool actually gives us than to assume an order is correct.

ibd2sql is not installed as a program. It is a Python script we cloned, so it
has to be run as `python3 <path>/main.py`. The path differs per machine, so it
comes from the FACTUMDB_IBD2SQL_PATH environment variable.
"""

import os
import re
import subprocess
from decimal import Decimal, InvalidOperation

from adapters.tools.versions import read_version
from core.domain.models.canonical import PhysicalRecord
from core.domain.models.values import UndecodableValue

# A binary value as ibd2sql prints it, e.g. 0x89504e47.
_HEX = re.compile(r"^0x[0-9a-fA-F]*$")

# One INSERT statement: schema, table, the column list, then the values.
INSERT_LINE = re.compile(
    r"^INSERT INTO\s+`([^`]+)`\.`([^`]+)`\s*\(([^)]*)\)\s*VALUES\s*\((.*)\);\s*$"
)


class Ibd2SqlAdapter:
    """Reads rows out of a .ibd file, including deleted ones."""

    def __init__(self, ibd2sql_path=None, python_path="python3"):
        self.ibd2sql_path = ibd2sql_path or os.environ.get("FACTUMDB_IBD2SQL_PATH")
        self.python_path = python_path

    def version(self):
        self._require_path()
        return read_version([self.python_path, self.ibd2sql_path])

    def extract_records(self, ibd_path, deleted=False, *, run=None):
        """Return the rows in one .ibd file.

        deleted=False gives the live rows, deleted=True gives the rows that are
        still on the page but flagged as deleted.
        """
        self._require_path()

        command = [self.python_path, self.ibd2sql_path, ibd_path,
                   "--sql", "--complete-insert"]
        if deleted:
            command += ["--delete", "only"]

        result = (run or subprocess.run)(command, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ibd2sql failed (exit {result.returncode}): "
                f"{result.stderr.decode(errors='replace')[:300]}"
            )
        return self.parse(result.stdout.decode(errors="replace"), is_deleted=deleted)

    def _require_path(self):
        if not self.ibd2sql_path:
            raise RuntimeError(
                "FACTUMDB_IBD2SQL_PATH is not set. It must point at ibd2sql's main.py"
            )

    @staticmethod
    def parse(text, is_deleted=False):
        """Turn ibd2sql's output into PhysicalRecords.

        Separate from extract_records so it can be tested against saved output.
        Anything that is not an INSERT statement (blank lines, CREATE TABLE if
        --ddl was used, comments) is skipped.
        """
        records = []

        for line in text.splitlines():
            match = INSERT_LINE.match(line.strip())
            if match is None:
                continue

            database, table, column_part, value_part = match.groups()

            names = [c.strip().strip("`") for c in column_part.split(",")]
            raw_values = Ibd2SqlAdapter._split_values(value_part)

            if len(names) != len(raw_values):
                # Should not happen with --complete-insert, but if the value
                # splitter got confused we must not pair the wrong value with
                # the wrong column - that would be a false statement about the
                # evidence. Skip the row rather than guess.
                continue

            values = {}
            for name, raw in zip(names, raw_values):
                values[name] = Ibd2SqlAdapter._convert(raw)

            records.append(PhysicalRecord(
                database=database,
                table=table,
                values=values,
                is_deleted=is_deleted,
                # ibd2sql does not tell us where on the page the row was, so
                # these stay None until we read the pages ourselves.
                page_no=None,
                page_offset=None,
            ))

        return records

    @staticmethod
    def _split_values(text):
        """Split a VALUES list on commas, ignoring commas inside strings.

        A plain text.split(",") breaks as soon as a value contains a comma, for
        example an owner name like 'Perera, A.'. This walks the text instead and
        only treats a comma as a separator when it is outside a quoted string.

        Strings can be quoted with either character. ibd2sql normally uses
        single quotes, but switches to double quotes when the value itself
        contains an apostrophe, so a real row comes out as:

            (104,"Perera, A. O'Brien",9000,'active')

        Only the quote that opened the string closes it, otherwise the
        apostrophe inside that name would end the value early.

        Both ways of escaping a quote inside a string are handled: a doubled
        quote ('') and a backslash quote (\\').
        """
        values = []
        current = ""
        quote_char = ""
        i = 0

        while i < len(text):
            char = text[i]

            if quote_char:
                if char == "\\" and i + 1 < len(text):
                    current += char + text[i + 1]
                    i += 2
                    continue
                if char == quote_char:
                    if i + 1 < len(text) and text[i + 1] == quote_char:
                        current += char + char
                        i += 2
                        continue
                    quote_char = ""
                current += char
            elif char in ("'", '"'):
                quote_char = char
                current += char
            elif char == ",":
                values.append(current.strip())
                current = ""
            else:
                current += char

            i += 1

        values.append(current.strip())
        return values

    @staticmethod
    def _convert(raw):
        """Turn one raw token from the SQL text into a Python value."""
        if raw.upper() == "NULL":
            return None

        for quote in ("'", '"'):
            if len(raw) >= 2 and raw.startswith(quote) and raw.endswith(quote):
                return Ibd2SqlAdapter._unescape(raw[1:-1], quote)

        try:
            return int(raw)
        except ValueError:
            pass

        try:
            # DECIMAL columns are printed as plain numbers such as 4000.10. A
            # float cannot hold most of them exactly, so they become Decimals.
            return Decimal(raw)
        except InvalidOperation:
            pass

        if _HEX.match(raw):
            # Binary columns (BLOB, BINARY, VARBINARY) are printed as 0x...,
            # and mysqlbinlog prints the same bytes another way. Neither
            # spelling is real text, so both sides mark them as not decoded.
            return UndecodableValue("binary data is not decoded")

        # Anything else is kept as the exact text the tool printed rather
        # than being altered.
        return raw

    @staticmethod
    def _unescape(text, quote="'"):
        """Undo the escaping inside a quoted SQL string.

        `quote` is whichever character opened the string, since a doubled
        quote only means an escaped quote for that same character.
        """
        out = ""
        i = 0
        while i < len(text):
            char = text[i]
            if char == "\\" and i + 1 < len(text):
                nxt = text[i + 1]
                out += {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(nxt, nxt)
                i += 2
                continue
            if char == quote and i + 1 < len(text) and text[i + 1] == quote:
                out += quote
                i += 2
                continue
            out += char
            i += 1
        return out
