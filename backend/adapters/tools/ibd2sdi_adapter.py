"""Adapter for the ibd2sdi utility.

ibd2sdi reads the SDI (serialized dictionary information) that InnoDB keeps
inside the .ibd file itself, and prints it as JSON. This adapter turns that
JSON into a Schema, which is what the rest of the system works with.

The main job here is working out the column positions. mysqlbinlog refers to
columns only by number (@1, @2, ...) and those numbers count visible columns
only, so this adapter has to drop InnoDB's hidden system columns and renumber
what is left. Getting that wrong would put one column's value under another
column's name.
"""

import json
import subprocess

from core.domain.models.canonical import Column, Schema


class Ibd2SdiAdapter:
    """Runs ibd2sdi on a .ibd file and builds a Schema from its output."""

    def __init__(self, ibd2sdi_path="ibd2sdi"):
        self.ibd2sdi_path = ibd2sdi_path

    def extract_schema(self, ibd_path):
        """Run ibd2sdi on one .ibd file and return its Schema."""
        command = [self.ibd2sdi_path, ibd_path]
        result = subprocess.run(command, capture_output=True)

        if result.returncode != 0:
            message = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"ibd2sdi failed on {ibd_path} (exit {result.returncode}): {message[:300]}"
            )

        return self.parse(result.stdout)

    @staticmethod
    def parse(raw_json):
        """Turn ibd2sdi's JSON output into a Schema.

        Kept separate from extract_schema so it can be tested against a saved
        output file without needing MySQL or running any subprocess.
        """
        data = json.loads(raw_json)

        # The output is a list that starts with the string "ibd2sdi", then one
        # entry per dictionary object. We want the Table one - there is also a
        # Tablespace entry that we do not need.
        table_entry = None
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if entry.get("object", {}).get("dd_object_type") == "Table":
                table_entry = entry
                break

        if table_entry is None:
            raise ValueError("ibd2sdi output has no Table object")

        dd = table_entry["object"]["dd_object"]
        raw_columns = dd["columns"]

        pk_indexes = Ibd2SdiAdapter._primary_key_indexes(dd)

        # Keep only the real user columns. hidden == 1 means a normal column,
        # hidden == 2 means an InnoDB system column (DB_TRX_ID, DB_ROLL_PTR,
        # and DB_ROW_ID when the table has no primary key of its own).
        # The raw position is kept because the primary key elements refer to it.
        visible = []
        for raw_index, column in enumerate(raw_columns):
            if column.get("hidden") == 1:
                visible.append((raw_index, column))

        visible.sort(key=lambda pair: pair[1]["ordinal_position"])

        # Renumber from 1 over the visible columns only. This is the number
        # mysqlbinlog uses, so @1 is the first item in this list.
        columns = []
        for position, (raw_index, column) in enumerate(visible, start=1):
            columns.append(
                Column(
                    name=column["name"],
                    position=position,
                    data_type=column.get("column_type_utf8", ""),
                    is_nullable=bool(column.get("is_nullable", False)),
                    is_primary_key=raw_index in pk_indexes,
                )
            )

        return Schema(
            database=dd.get("schema_ref", ""),
            table=dd["name"],
            columns=tuple(columns),
            mysql_version_id=dd.get("mysql_version_id"),
        )

    @staticmethod
    def _primary_key_indexes(dd):
        """Return the raw column indexes that make up the primary key.

        The PRIMARY index lists every column stored in the clustered index, not
        just the key ones, so the InnoDB internals and the ordinary columns are
        in there too. Only the elements with hidden == False are actual key
        columns. column_opx is a 0-based index into the unfiltered columns list.
        """
        pk_indexes = set()
        for index in dd.get("indexes", []):
            if index.get("name") != "PRIMARY":
                continue
            for element in index.get("elements", []):
                if element.get("hidden") is False:
                    pk_indexes.add(element["column_opx"])
        return pk_indexes
