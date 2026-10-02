"""Reading mysql-bin.index, and what the analysis can say once it has.

Without the index the domain can only say "we cannot tell whether any binlog
is missing", and every record history carries that coverage gap.
"""

from __future__ import annotations

import pytest

from adapters.persistence.sqlite_binlog_inventory_repository import (
    SqliteBinlogInventoryRepository,
)
from adapters.tools.binlog_index import MysqlBinlogIndexAdapter
from core.application.errors import ConflictError, PrerequisiteError
from core.application.use_cases.analysis import GroupTransactionsUseCase
from core.application.use_cases.extraction import (
    NormalizeEvidenceUseCase,
    RecordBinlogInventoryUseCase,
)
from core.domain.models.evidence import EvidenceKind, VerificationStatus
from tests.adapters.conftest import a_binlog, an_ibd
from tests.adapters.test_sqlite_normalization import case  # noqa: F401 - fixture
from tests.application.fakes import FixedClock

# What MySQL wrote on the scenario 2 server, byte for byte.
INDEX = (
    "/var/log/mysql/mysql-bin.000001\n"
    "/var/log/mysql/mysql-bin.000005\n"
    "/var/log/mysql/mysql-bin.000006\n"
)


def an_index(tmp_path, text=INDEX, evidence_id="ev-index", verified=True):
    path = tmp_path / f"{evidence_id}.index"
    path.write_text(text)
    return an_ibd(
        "case-1", evidence_id, kind=EvidenceKind.BINLOG_INDEX,
        source_path=f"/seized/{evidence_id}/mysql-bin.index", filename="mysql-bin.index",
        verification_status=VerificationStatus.VERIFIED if verified else VerificationStatus.REGISTERED,
        working_copy_path=str(path) if verified else None,
        working_copy_sha256="a" * 64 if verified else None,
    )


def record(case):
    return RecordBinlogInventoryUseCase(
        case.evidence, MysqlBinlogIndexAdapter(), case.extraction, FixedClock()
    ).execute("case-1")


def stored(case):
    return SqliteBinlogInventoryRepository(case.extraction._connection).inventory()


# ── Reading the file ─────────────────────────────────────────────────────────


def test_server_paths_become_file_names(tmp_path) -> None:
    """The paths are where the logs were on the server, not where our copies are."""
    path = tmp_path / "mysql-bin.index"
    path.write_text(INDEX)

    assert MysqlBinlogIndexAdapter().read(str(path)) == (
        "mysql-bin.000001", "mysql-bin.000005", "mysql-bin.000006",
    )


def test_relative_paths_blank_lines_and_crlf_are_handled(tmp_path) -> None:
    path = tmp_path / "mysql-bin.index"
    path.write_bytes(b"./mysql-bin.000001\r\n\r\n./mysql-bin.000002  \r\n")

    assert MysqlBinlogIndexAdapter().read(str(path)) == ("mysql-bin.000001", "mysql-bin.000002")


def test_a_log_listed_twice_is_refused(tmp_path) -> None:
    """MySQL never writes that, so the file was edited or damaged."""
    path = tmp_path / "mysql-bin.index"
    path.write_text("./mysql-bin.000001\n./mysql-bin.000001\n")

    with pytest.raises(ValueError, match="more than once"):
        MysqlBinlogIndexAdapter().read(str(path))


# ── Recording the inventory ──────────────────────────────────────────────────


def test_without_an_index_nothing_is_recorded(case) -> None:
    """Then coverage stays unknown - never assumed complete."""
    assert record(case).item_count == 0
    assert stored(case) is None


def test_a_listed_log_that_was_not_seized_is_missing(case, tmp_path) -> None:
    """The index lists 000001, 000005 and 000006; only 000006 was seized."""
    case.evidence.save(an_index(tmp_path))

    receipt = record(case)
    inventory = stored(case)

    assert receipt.item_count == 3
    assert inventory.present_files == ("mysql-bin.000006",)
    assert inventory.missing_files == ("mysql-bin.000001", "mysql-bin.000005")


def test_two_indexes_are_refused(case, tmp_path) -> None:
    """One case is one server; two indexes could disagree about what is missing."""
    case.evidence.save(an_index(tmp_path, evidence_id="ev-index"))
    case.evidence.save(an_index(tmp_path, evidence_id="ev-index-2"))

    with pytest.raises(ConflictError, match="more than one"):
        record(case)


def test_an_unverified_index_is_not_read(case, tmp_path) -> None:
    case.evidence.save(an_index(tmp_path, verified=False))

    with pytest.raises(PrerequisiteError):
        record(case)


def test_an_inventory_must_come_from_a_binlog_index(case) -> None:
    from core.domain.models.canonical import BinlogInventory

    with pytest.raises(ConflictError, match="binlog index"):
        case.extraction.save_inventory(
            "case-1", "ev-bin", BinlogInventory("mysql-bin.index", (), (), ())
        )


# ── What the analysis can say with it ────────────────────────────────────────


def test_with_the_index_the_coverage_gap_disappears(case, tmp_path) -> None:
    """Every log the server listed was seized, so coverage is complete."""
    case.evidence.save(an_index(tmp_path, "/var/log/mysql/mysql-bin.000006\n"))
    record(case)
    NormalizeEvidenceUseCase(case.cases, case.normalizer, case.extraction, FixedClock()
                             ).execute("case-1")

    inputs = case.domain.inputs_for("case-1")
    grouping = GroupTransactionsUseCase(case.domain).execute("case-1")

    assert inputs.evidence.inventory().missing_files == ()
    assert grouping.coverage.gaps == ()


def test_without_the_index_every_result_carries_the_gap(case) -> None:
    """The same case with no index: the domain cannot rule out a missing log."""
    NormalizeEvidenceUseCase(case.cases, case.normalizer, case.extraction, FixedClock()
                             ).execute("case-1")

    grouping = GroupTransactionsUseCase(case.domain).execute("case-1")

    assert [gap.reason for gap in grouping.coverage.gaps] == ["no_index"]
