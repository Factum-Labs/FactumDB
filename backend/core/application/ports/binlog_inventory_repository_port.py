"""Port for the server's own list of its binary logs."""

from abc import ABC, abstractmethod
from typing import Optional

from core.domain.models.canonical import BinlogInventory


class BinlogInventoryRepositoryPort(ABC):
    """Stores what mysql-bin.index said the server had.

    Backs the `binlog_inventory` table in docs/sqlite-schema.md section 12.

    `inventory` is part of the domain layer's EvidenceContext protocol.

    This is small but it decides something important. Without it we have some
    number of binlog files and no way of knowing whether that is all of them.
    With it we can say "the server had 6 logs and we were given 5", which is
    what lets a mismatch be reported as an evidence gap rather than as
    tampering.
    """

    @abstractmethod
    def save(self, inventory: BinlogInventory, evidence_id: str) -> None:
        """Persist one inventory.

        missing_files is worked out once, when saving, rather than being
        recalculated on every read. That way the report and the screen can
        never disagree about which logs are absent.
        """
        raise NotImplementedError

    @abstractmethod
    def inventory(self) -> Optional[BinlogInventory]:
        """The inventory for the case, or None if no index file was seized.

        EvidenceContext.inventory. None is meaningful here: it means we cannot
        tell whether any logs are missing, which is weaker than knowing none
        are. The reconciliation service treats those two cases differently.
        """
        raise NotImplementedError

    @abstractmethod
    def find_by_evidence(self, evidence_id: str) -> Optional[BinlogInventory]:
        """The inventory built from one particular index file."""
        raise NotImplementedError
