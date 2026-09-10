"""Canonical ordering, including the corrections to the frontend comparators."""

from __future__ import annotations

from core.domain.models.canonical import BinlogInventory
from core.domain.models.classification import SEVERITY, ReconResult, most_severe
from core.domain.models.identity import RecordKey, RecordRef
from core.domain.ordering import (
    FileSequence,
    basename,
    cmp_key,
    cmp_str,
    event_sort_key,
    record_sort_key,
    transaction_sort_key,
)


def ref(table: str, *values: str, database: str = "finance") -> RecordRef:
    return RecordRef.from_key(
        RecordKey(database=database, table=table, columns=("id",) * len(values), values=values)
    )


def inventory(*files: str) -> BinlogInventory:
    return BinlogInventory(
        index_file="mysql-bin.index",
        listed_files=files,
        present_files=files,
        missing_files=(),
    )


# ── Shared invariant with the frontend ───────────────────────────────────────


def test_severity_table_matches_the_frontend_exactly() -> None:
    """Asserted literally so TS and Python cannot drift apart silently.

    Mirrors `SEVERITY` in frontend/src/lib/correlation.ts.
    """
    assert {r.value: v for r, v in SEVERITY.items()} == {
        "Conflicting": 5,
        "Unresolved": 4,
        "Partial": 3,
        "Strong": 2,
        "Exact": 1,
        "Unsupported": 0,
    }


def test_unsupported_ranks_lowest_but_is_not_agreement() -> None:
    """The frontend's classify() reads severity 0 as 'agreeing'. It is not.

    A record whose every field is Unsupported was never compared, so the most
    severe result is Unsupported - and the caller must not treat that as a match.
    """
    all_unsupported = (ReconResult.UNSUPPORTED, ReconResult.UNSUPPORTED)
    assert most_severe(all_unsupported) is ReconResult.UNSUPPORTED
    assert most_severe(()) is None
    assert most_severe((ReconResult.EXACT, ReconResult.UNSUPPORTED)) is ReconResult.EXACT


# ── Strings ──────────────────────────────────────────────────────────────────


def test_cmp_str_is_codepoint_order() -> None:
    assert cmp_str("a", "b") == -1
    assert cmp_str("b", "a") == 1
    assert cmp_str("a", "a") == 0
    # Locale-aware collation would sort these together; codepoint order must not.
    assert cmp_str("Z", "a") == -1


# ── Keys: the Number() corrections ───────────────────────────────────────────


def test_numeric_keys_sort_numerically() -> None:
    assert cmp_key("9", "10") == -1


def test_composite_keys_sort_component_wise() -> None:
    """`Number("1|10")` is NaN, so the frontend falls back to lexical: 1|10 < 1|9."""
    assert cmp_key("1|9", "1|10") == -1
    assert cmp_key("2|1", "10|1") == -1


def test_bigint_keys_beyond_float_precision_order_correctly() -> None:
    assert cmp_key("9007199254740992", "9007199254740993") == -1


def test_hex_looking_string_keys_stay_lexical() -> None:
    """`Number("0x10")` is 16. These are string keys and must order as strings."""
    assert cmp_key("0x10", "0x9") == -1


def test_string_keys_order_lexically() -> None:
    assert cmp_key("alpha", "beta") == -1
    assert cmp_key("10a", "9a") == -1  # not digit strings, so lexical


def test_negative_keys_sort_numerically() -> None:
    assert cmp_key("-10", "-9") == -1
    assert cmp_key("-1", "1") == -1


# ── File sequence ────────────────────────────────────────────────────────────


def test_basename_is_host_independent() -> None:
    """os.path would split differently on Linux and Windows for the same case."""
    assert basename("/var/log/mysql/mysql-bin.000006") == "mysql-bin.000006"
    assert basename("C:\\cases\\work\\binlog.000018") == "binlog.000018"
    assert basename("binlog.000018") == "binlog.000018"


def test_files_order_by_the_servers_own_sequence_not_lexically() -> None:
    """A case whose logs changed basename mid-stream defeats lexical order."""
    seq = FileSequence(inventory("/var/log/mysql/mysql-bin.000009", "/var/log/mysql/binlog.000010"))
    assert seq.sort_key("mysql-bin.000009") < seq.sort_key("binlog.000010")
    assert not seq.used_fallback


def test_inventory_paths_are_matched_by_name() -> None:
    """The index stores absolute paths; working copies live in the case folder."""
    seq = FileSequence(inventory("/var/log/mysql/mysql-bin.000006"))
    assert seq.index("work/mysql-bin.000006") == 0
    assert not seq.used_fallback


def test_missing_inventory_is_flagged_as_a_fallback() -> None:
    """No index is never read as 'we have every log'."""
    seq = FileSequence(None)
    seq.index("binlog.000018")
    assert seq.used_fallback


def test_unlisted_file_sorts_last_and_is_reported() -> None:
    seq = FileSequence(inventory("mysql-bin.000001"))
    assert seq.sort_key("mysql-bin.000001") < seq.sort_key("stray.000099")
    assert seq.used_fallback
    assert seq.unlisted_files == ("stray.000099",)


# ── Transactions and events ──────────────────────────────────────────────────


def test_transactions_sort_on_begin_not_commit() -> None:
    """An incomplete transaction has no COMMIT, so start_position is the key."""
    seq = FileSequence(inventory("binlog.000018"))
    incomplete = transaction_sort_key(seq, "binlog.000018", 1180, "TX-000018@1180")
    committed = transaction_sort_key(seq, "binlog.000018", 2210, "TX-1449")
    assert incomplete < committed


def test_events_order_across_files_by_sequence_then_position() -> None:
    seq = FileSequence(inventory("binlog.000018", "binlog.000020"))
    assert event_sort_key(seq, "binlog.000018", 8814) < event_sort_key(seq, "binlog.000020", 12)


# ── Records ──────────────────────────────────────────────────────────────────


def test_records_sort_by_qualified_table_then_key() -> None:
    ordered = sorted(
        [ref("transfers", "9002"), ref("accounts", "205"), ref("accounts", "101")],
        key=record_sort_key,
    )
    assert [r.id for r in ordered] == ["accounts:101", "accounts:205", "transfers:9002"]


def test_same_table_name_in_two_databases_stays_separated_in_order() -> None:
    """The ids collide; the qualified table name is what keeps the order sane."""
    a = ref("accounts", "101", database="finance")
    b = ref("accounts", "101", database="hr")
    assert a.id == b.id
    assert sorted([b, a], key=record_sort_key)[0].database == "finance"
