"""SQLite implementation of the binlog inventory repository.

Stores what mysql-bin.index said the server had, next to what was actually
seized. This is what lets the report say "the server had 6 logs and we were
given 5" and call it an evidence gap, instead of reading a missing log as
tampering.

missing_files is worked out when saving, from listed and present, rather
than trusted from the caller. The saved value is then the only one anything
reads, so the report and the screen can never disagree about it.
"""

import json
import os
from typing import Optional, Sequence

from adapters.persistence._transactions import transaction
from core.application.ports.binlog_inventory_repository_port import (
    BinlogInventoryRepositoryPort,
)
from core.domain.models.canonical import BinlogInventory

_COLUMNS = """
    inventory_id, evidence_id, index_file, listed_files_json,
    present_files_json, missing_files_json
"""


class SqliteBinlogInventoryRepository(BinlogInventoryRepositoryPort):
    """Stores the server's own list of its binlogs."""

    def __init__(self, connection):
        self._connection = connection

    def save(self, inventory: BinlogInventory, evidence_id: str) -> None:
        """Store one inventory, replacing an earlier one from the same index.

        The index stores absolute paths such as /var/log/mysql/mysql-bin.000006
        while working copies live in the case folder, so files are compared by
        name only.
        """
        listed = _names(inventory.listed_files)
        present = _names(inventory.present_files)
        present_set = set(present)
        missing = [name for name in listed if name not in present_set]

        with transaction(self._connection):
            self._connection.execute(
                "DELETE FROM binlog_inventory WHERE evidence_id = ?", (evidence_id,)
            )
            self._connection.execute(
                f"INSERT INTO binlog_inventory ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"{evidence_id}:inventory",
                    evidence_id,
                    inventory.index_file,
                    json.dumps(listed),
                    json.dumps(present),
                    json.dumps(missing),
                ),
            )

    def inventory(self) -> Optional[BinlogInventory]:
        """The inventory for the case, or None if no index file was seized.

        None is weaker than an empty missing list: it means we cannot tell
        whether any logs are missing at all.
        """
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM binlog_inventory ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return _row_to_inventory(row) if row is not None else None

    def find_by_evidence(self, evidence_id: str) -> Optional[BinlogInventory]:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM binlog_inventory WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        return _row_to_inventory(row) if row is not None else None


def _names(paths: Sequence[str]) -> list:
    return [os.path.basename(p) for p in paths]


def _row_to_inventory(row) -> BinlogInventory:
    return BinlogInventory(
        index_file=row["index_file"],
        listed_files=tuple(json.loads(row["listed_files_json"])),
        present_files=tuple(json.loads(row["present_files_json"])),
        missing_files=tuple(json.loads(row["missing_files_json"])),
    )
