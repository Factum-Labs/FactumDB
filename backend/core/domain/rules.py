"""The rule catalogue: every statement the engine is allowed to make.

Forensic repeatability means an examiner must be able to re-run the analysis and
get the same conclusions *for the same stated reasons*. That is only checkable if
the reasons are enumerable, so every Finding and every classification carries an
id from this table, and nothing in the services builds a sentence of its own.

`docs/correlation-rules.md` is the readable twin of this module. A test parses
that document and asserts it matches `RULES` exactly, so the two cannot drift.

Id families:

    R-VAL     value comparison
    R-PROV    provenance completeness
    R-ID      record identity rendering
    R-GRP     transaction grouping
    R-TXID    transaction id derivation
    R-COV     evidence coverage
    R-CORR    record correlation
    R-HIST    state reconstruction
    R-RECON   per-field reconciliation
    R-ROLL    per-record roll-up
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from core.domain.models.classification import ReconResult
from core.domain.models.findings import Severity
from core.domain.models.transactions import IncompletenessReason


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """One rule.

    `statement` is the normative sentence - what the rule asserts about evidence,
    written so a reviewer can judge whether it is defensible. `template` is the
    report line, filled from a Finding's `context`.

    `result` and `incompleteness_reason` are the two classifications a rule can
    write. Both are declared here rather than left to the services, because the
    catalogue's premise is that no classification is assigned by uncited logic -
    if a service writes an enum value, some rule has to have claimed it.

    `decided_with` names another rule this one defers to for a distinction it
    does not itself make. It exists so a cross-reference is a checked link rather
    than a sentence a reader has to notice.
    """

    id: str
    service: str
    title: str
    statement: str
    template: str
    severity: Severity = Severity.INFO
    result: ReconResult | None = None
    incompleteness_reason: IncompletenessReason | None = None
    decided_with: tuple[str, ...] = ()


def _r(
    rule_id: str,
    service: str,
    title: str,
    statement: str,
    template: str,
    severity: Severity = Severity.INFO,
    result: ReconResult | None = None,
    incompleteness_reason: IncompletenessReason | None = None,
    decided_with: tuple[str, ...] = (),
) -> RuleDefinition:
    return RuleDefinition(
        rule_id,
        service,
        title,
        statement,
        template,
        severity,
        result,
        incompleteness_reason,
        decided_with,
    )


_DEFINITIONS: tuple[RuleDefinition, ...] = (
    # ── Value comparison ─────────────────────────────────────────────────────
    _r(
        "R-VAL-001",
        "values",
        "Numeric values compare by value",
        "Numeric values are compared as decimals, so representations that differ "
        "only in formatting are treated as equal. NULL compared with NULL is a "
        "match, because NULL is an observation.",
        "{left} vs {right}",
    ),
    _r(
        "R-VAL-002",
        "values",
        "Binary floats are not comparable",
        "Binary floating point values are never compared. Two values that print "
        "identically can differ in their last bits, so neither equality nor "
        "inequality can be asserted defensibly.",
        "{column} holds a binary float and cannot be compared",
        Severity.NOTICE,
    ),
    _r(
        "R-VAL-003",
        "values",
        "Strings compare byte-exactly",
        "Strings are compared byte for byte, with no case folding and no "
        "trimming. MySQL's default collation is case-insensitive, but the "
        "collation in force is not observable in the evidence, so a difference is "
        "reported rather than assumed away.",
        "{left} vs {right}",
    ),
    _r(
        "R-VAL-004",
        "values",
        "Naive timestamps are not comparable",
        "A timestamp without a timezone has no defined instant and is never "
        "compared against a UTC value.",
        "{column} holds a timestamp with no timezone",
        Severity.NOTICE,
    ),
    _r(
        "R-VAL-005",
        "values",
        "Undecodable values are never equal",
        "A value the adapter could not decode is never equal to anything, "
        "including another undecodable value. Two unreadable columns are not "
        "evidence of agreement.",
        "{column} could not be decoded: {reason}",
        Severity.NOTICE,
    ),
    _r(
        "R-VAL-006",
        "values",
        "Unobserved values are never equal",
        "A column no evidence speaks to is never equal to anything. Absence of an "
        "observation is not an observation of absence.",
        "{column} was not observed in the available evidence",
        Severity.NOTICE,
    ),
    _r(
        "R-VAL-007",
        "values",
        "Unvalidated column types are not compared",
        "A column whose declared type is outside the validated subset is not "
        "compared, because our decoding of it has not been verified.",
        "{column} has type {data_type}, which is outside the validated scope",
        Severity.NOTICE,
    ),
    _r(
        "R-VAL-008",
        "values",
        "Values of different types are not compared",
        "Two values of incompatible types are not coerced into a common type to "
        "force a comparison.",
        "{column}: {left} and {right} are not of comparable types",
        Severity.NOTICE,
    ),
    # ── Provenance ───────────────────────────────────────────────────────────
    _r(
        "R-PROV-001",
        "provenance",
        "Provenance is incomplete",
        "The adapter did not record a tool run for this evidence, so findings "
        "derived from it carry only a source file and position. The finding still "
        "stands; the chain back to the raw output does not.",
        "No tool run recorded for {source_file}",
        Severity.WARNING,
    ),
    # ── Identity ─────────────────────────────────────────────────────────────
    _r(
        "R-ID-001",
        "correlation",
        "Primary key rendering",
        "Key values are rendered exactly: integers and decimals as written, "
        "timestamps as ISO-8601 UTC, strings verbatim. A key value that cannot be "
        "rendered exactly yields no record identity at all.",
        "{record}",
    ),
    _r(
        "R-ID-002",
        "correlation",
        "Key value contains the composite separator",
        "A key value containing the composite key separator makes the rendered "
        "key ambiguous: one value containing the separator and two values joined "
        "by it produce the same text. The ambiguity is reported rather than "
        "escaped away, because it is a real reason to distrust the identity.",
        "{record}: key value contains {separator}",
        Severity.WARNING,
    ),
    _r(
        "R-ID-003",
        "correlation",
        "Record id namespace collision",
        "Two databases in this case contain a table of the same name, so their "
        "record ids collide. Records are kept separate internally by their "
        "qualified table name, but any display that shows only the id is "
        "ambiguous.",
        "Table {table} exists in more than one database: {databases}",
        Severity.WARNING,
    ),
    # ── Transaction grouping ─────────────────────────────────────────────────
    _r(
        "R-GRP-001",
        "grouping",
        "Transaction bounded by GTID",
        "A GTID identifies one transaction uniquely across the whole server, so "
        "it is the strongest available transaction boundary.",
        "{transaction} bounded by GTID {gtid}",
    ),
    _r(
        "R-GRP-002",
        "grouping",
        "Transaction committed at XID",
        "An XID event marks a committed transaction boundary.",
        "{transaction} committed at XID {xid}",
    ),
    _r(
        "R-GRP-003",
        "grouping",
        "Transaction rolled back",
        "A ROLLBACK marker means the events inside the transaction were never "
        "durable. They are retained as evidence but never applied to a "
        "reconstructed state.",
        "{transaction} was rolled back",
        Severity.NOTICE,
    ),
    _r(
        "R-GRP-004",
        "grouping",
        "Terminator missing at the end of the available log",
        "The transaction began and the last log we were given ends with it still "
        "open, with no later file listed in the index. Its outcome is unknown and "
        "the gap is unbounded - we cannot say how much is missing, only that the "
        "record stops here. Sets incompleteness_reason to NO_TERMINATOR_IN_RANGE. "
        "The evidence for that boundary is stated by R-COV-003. This rule is also "
        "the default when no index is available at all: without one, a missing "
        "file cannot be proved, so the bounded reason cannot be claimed and the "
        "unbounded reason applies. That is a statement about our evidence, not "
        "about the server - R-COV-001 separately records that coverage is "
        "unknown, and it is R-COV-001 rather than this rule that keeps later "
        "differences unresolved.",
        "{transaction} is still open where {source_file} ends",
        Severity.WARNING,
        None,
        IncompletenessReason.NO_TERMINATOR_IN_RANGE,
        ("R-COV-001", "R-COV-003"),
    ),
    _r(
        "R-GRP-014",
        "grouping",
        "Terminator falls inside a log file we were not given",
        "The transaction began and the index proves a log file between it and its "
        "terminator was not provided. Its outcome is unknown but the gap is "
        "bounded: we can name the file that would resolve it, which is a "
        "materially stronger statement than the log merely stopping. Sets "
        "incompleteness_reason to LOG_FILE_MISSING_IN_SEQUENCE. The evidence for "
        "that boundary is stated by R-COV-002. This rule requires an index and can "
        "never apply without one - naming a file we were never told existed would "
        "be asserting more than the evidence supports, so R-GRP-004 applies "
        "instead.",
        "{transaction} is still open where {source_file} ends, and {missing_files} is missing",
        Severity.WARNING,
        None,
        IncompletenessReason.LOG_FILE_MISSING_IN_SEQUENCE,
        ("R-COV-002",),
    ),
    _r(
        "R-GRP-005",
        "grouping",
        "Log begins part-way through a transaction",
        "Unclaimed row events precede every marker in the evidence set - nothing "
        "at all comes before them. That is observable evidence that the earliest "
        "log we hold begins part-way through a transaction whose opening marker "
        "lies in a region we do not have, so the events are grouped into one "
        "synthesised container to keep them together and ordered. The container "
        "is never treated as committed, and it is labelled as synthesised so no "
        "reader mistakes it for an observed transaction. Sets "
        "incompleteness_reason to EVENTS_WITHOUT_BEGIN. This rule applies only to "
        "that leading run; an unclaimed event anywhere else falls under R-GRP-011 "
        "and is not grouped with anything.",
        "{count} event(s) precede the first marker in {source_file}",
        Severity.WARNING,
        None,
        IncompletenessReason.EVENTS_WITHOUT_BEGIN,
        ("R-GRP-011",),
    ),
    _r(
        "R-GRP-006",
        "grouping",
        "Marker claimed no events",
        "A transaction marker exists but none of the events it refers to were "
        "decoded, or none could be claimed, so the transaction's content is "
        "unknown. Sets incompleteness_reason to MARKER_WITHOUT_EVENTS.",
        "{transaction} refers to events that were not decoded",
        Severity.WARNING,
        None,
        IncompletenessReason.MARKER_WITHOUT_EVENTS,
    ),
    _r(
        "R-GRP-007",
        "grouping",
        "Sessions separated by GTID or thread",
        "Concurrent sessions interleave in the log, so events are assigned to "
        "transactions by GTID or thread identity - never by adjacency of log "
        "positions.",
        "{transaction} belongs to session {session_key}",
    ),
    _r(
        "R-GRP-008",
        "grouping",
        "Interleaving cannot be resolved",
        "Events fall inside this transaction's position range but neither the "
        "marker nor the events carry a session identifier, so membership cannot "
        "be established. The events are left ungrouped rather than assigned on "
        "the assumption that the log is sequential.",
        "{transaction} overlaps {count} event(s) with no session identifier",
        Severity.WARNING,
    ),
    _r(
        "R-GRP-009",
        "grouping",
        "Listed event was not decoded",
        "The marker refers to an event position for which no decoded event "
        "exists, so part of the transaction's content is missing.",
        "{transaction} lists position {log_position} in {source_file}, not decoded",
        Severity.WARNING,
    ),
    _r(
        "R-GRP-010",
        "grouping",
        "Event inside range but not listed",
        "An event falls within a transaction's position range but the marker does "
        "not list it. It is not claimed, because it may belong to an interleaved "
        "session.",
        "Event at {source_file}:{log_position} lies inside {transaction} but is not listed",
        Severity.NOTICE,
    ),
    _r(
        "R-GRP-011",
        "grouping",
        "Event belongs to no transaction",
        "The event is claimed by no marker, and markers do exist before it, so it "
        "is not the leading run that R-GRP-005 covers. Nothing observable says "
        "which transaction it belonged to, nor that it belonged with any other "
        "unclaimed event, so it stays on the timeline as observed evidence, is "
        "never treated as durable, and is grouped with nothing. Grouping "
        "mid-stream orphans together would assert a shared transaction that no "
        "evidence supports.",
        "Event at {source_file}:{log_position} belongs to no observed transaction",
        Severity.WARNING,
        None,
        None,
        ("R-GRP-005",),
    ),
    _r(
        "R-GRP-012",
        "grouping",
        "Duplicate GTID",
        "The same GTID appears in more than one place in the evidence. Both "
        "occurrences are kept, because duplicated or relay-log evidence is itself "
        "a finding.",
        "GTID {gtid} appears in {count} transactions",
        Severity.WARNING,
    ),
    _r(
        "R-GRP-013",
        "grouping",
        "Duplicate event position",
        "Two decoded events share a source file and log position, which cannot "
        "happen in one log. The first is used and both are reported.",
        "Duplicate event at {source_file}:{log_position}",
        Severity.WARNING,
    ),
    # ── Transaction ids ──────────────────────────────────────────────────────
    _r(
        "R-TXID-001",
        "grouping",
        "Transaction id derived from GTID",
        "Transaction ids are derived from the evidence, never from a counter, so "
        "re-running the analysis over the same evidence yields the same ids.",
        "{transaction} derived from GTID {gtid}",
    ),
    _r(
        "R-TXID-002",
        "grouping",
        "Transaction id derived from log position",
        "With no GTID available, the transaction is identified by its log file "
        "and BEGIN position, which are equally reproducible.",
        "{transaction} derived from {source_file}:{start_position}",
    ),
    # ── Coverage ─────────────────────────────────────────────────────────────
    _r(
        "R-COV-001",
        "coverage",
        "No binlog index available",
        "Without mysql-bin.index there is no way to know whether the logs we were "
        "given are all the logs that existed. Coverage is therefore treated as "
        "incomplete - absence of the index is never read as proof of "
        "completeness. It also means no file can be shown to be missing, so an "
        "unterminated transaction takes the unbounded reason under R-GRP-004 and "
        "never the bounded one under R-GRP-014.",
        "No binlog index in the evidence set; log ordering falls back to file names",
        Severity.WARNING,
    ),
    _r(
        "R-COV-002",
        "coverage",
        "Binlog file missing from the evidence set",
        "The index lists a log file that was not provided. Changes recorded in it "
        "cannot be observed, and any state difference that file could explain is "
        "reported as unresolved rather than as a conflict. When such a file falls "
        "between a transaction and its terminator, this is the evidence R-GRP-014 "
        "cites for LOG_FILE_MISSING_IN_SEQUENCE.",
        "{source_file} is listed in the index but absent from the evidence set",
        Severity.WARNING,
    ),
    _r(
        "R-COV-003",
        "coverage",
        "Log ends mid-transaction",
        "The last available log ends with a transaction still open, so events "
        "after that point are not observable. This is the evidence R-GRP-004 "
        "cites for NO_TERMINATOR_IN_RANGE, and it applies only when the index "
        "lists no later file - otherwise the stronger R-COV-002 applies instead.",
        "{source_file} ends with {transaction} still open",
        Severity.WARNING,
    ),
    _r(
        "R-COV-004",
        "coverage",
        "Coverage gap spans a record",
        "A gap in the log sequence falls within this record's observed history, "
        "so its reconstructed state may be missing changes.",
        "{record} history spans a coverage gap",
        Severity.WARNING,
    ),
    _r(
        "R-COV-005",
        "coverage",
        "Snapshot timing unknown",
        "The time at which the tablespace was acquired, relative to the last "
        "observed log event, is not recorded. A note for the examiner only: it "
        "does not by itself weaken any individual comparison.",
        "Acquisition time of the tablespace relative to the last log event is unknown",
        Severity.NOTICE,
    ),
    # ── Record correlation ───────────────────────────────────────────────────
    _r(
        "R-CORR-001",
        "correlation",
        "Primary key exact match",
        "The event's primary key value matches a physical record's primary key "
        "exactly.",
        "{record} matched on {key}",
    ),
    _r(
        "R-CORR-002",
        "correlation",
        "Composite primary key exact match",
        "Every component of the composite primary key matches exactly.",
        "{record} matched on composite key {key}",
    ),
    _r(
        "R-CORR-003",
        "correlation",
        "Key columns absent from the row image",
        "A key column is missing or undecodable in the row image, so no identity "
        "can be established for this event. No partial key is guessed at.",
        "Event at {source_file}:{log_position} has no usable key: {reason}",
        Severity.WARNING,
    ),
    _r(
        "R-CORR-010",
        "correlation",
        "Identity continued across a primary key update",
        "An update changed the primary key. The before and after images link the "
        "two key values as one record, whose canonical identity is the latest "
        "key - the value the tablespace now holds.",
        "{record} was previously {previous_key}",
        Severity.NOTICE,
    ),
    _r(
        "R-CORR-011",
        "correlation",
        "Key continuity is ambiguous",
        "Two or more key changes would have to be merged into one identity in a "
        "way the evidence does not determine. The identities are kept separate "
        "and the ambiguity is reported rather than resolved by choosing one.",
        "Key continuity for {key} is ambiguous: {reason}",
        Severity.WARNING,
    ),
    _r(
        "R-CORR-012",
        "correlation",
        "Key reused after deletion",
        "The key was deleted and later inserted again. It remains one record with "
        "an interval of absence in its history, because the schema says it is one "
        "key.",
        "{record} was deleted and later re-inserted",
        Severity.NOTICE,
    ),
    _r(
        "R-CORR-020",
        "correlation",
        "Table has no primary key",
        "Without a primary key there is no identity that both the log and the "
        "tablespace can express - InnoDB's internal row id is not visible to "
        "mysqlbinlog. Events for this table are not correlated, because "
        "synthesising an identity would be fabricating one.",
        "{table} has no primary key; its events cannot be correlated",
        Severity.WARNING,
        ReconResult.UNSUPPORTED,
    ),
    _r(
        "R-CORR-021",
        "correlation",
        "Schema not available",
        "A binlog event names a table for which no schema was extracted, so its "
        "columns cannot be interpreted.",
        "No schema available for {table}",
        Severity.WARNING,
        ReconResult.UNSUPPORTED,
    ),
    _r(
        "R-CORR-022",
        "correlation",
        "Multiple physical candidates",
        "More than one live physical record carries this key, so the correlation "
        "is ambiguous. None is chosen, and every comparison for this record "
        "becomes unresolved.",
        "{record} matches {count} live physical records",
        Severity.WARNING,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-CORR-023",
        "correlation",
        "Deleted remnant present alongside a live record",
        "A deleted remnant carries the same key as the live record. The live "
        "record is used for comparison and the remnant is retained as evidence.",
        "{record} has {count} deleted remnant(s) at the same key",
        Severity.NOTICE,
    ),
    _r(
        "R-CORR-030",
        "correlation",
        "Table not in the evidence scope",
        "Events reference a table for which no tablespace was registered. Its "
        "physical side is unobserved, so differences are unresolved rather than "
        "conflicting - we were not given the file, which is not the same as the "
        "row not being there.",
        "No tablespace in the evidence set for {table}",
        Severity.WARNING,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-CORR-031",
        "correlation",
        "Physical record with no log events",
        "The row exists in the tablespace but no observed event produced it. With "
        "complete log coverage that is a conflict; with a gap it is unresolved.",
        "{record} exists physically with no observed events",
        Severity.NOTICE,
    ),
    # ── State reconstruction ─────────────────────────────────────────────────
    _r(
        "R-HIST-001",
        "reconstruction",
        "Events ordered by log position",
        "Events are replayed in log sequence and position order, never by "
        "timestamp. Binary log timestamps have one-second resolution and are "
        "converted from server-local time, so events within a transaction "
        "routinely share one. Timestamps are shown but never used to order.",
        "{record}: {count} event(s) replayed in log order",
    ),
    _r(
        "R-HIST-002",
        "reconstruction",
        "Earliest state taken from the first observed event",
        "The starting state is read from the first event's before-image, or is "
        "absence when the first event is an insert. Nothing is extrapolated "
        "backwards past the first observation.",
        "{record}: earliest observed state at {source_file}:{log_position}",
    ),
    _r(
        "R-HIST-003",
        "reconstruction",
        "After-image applied",
        "A committed event's after-image is applied to the reconstructed state.",
        "{record}: {column_count} column(s) set at {source_file}:{log_position}",
    ),
    _r(
        "R-HIST-004",
        "reconstruction",
        "Delete sets the record absent",
        "A committed delete makes the record absent from the reconstructed state.",
        "{record}: deleted at {source_file}:{log_position}",
    ),
    _r(
        "R-HIST-005",
        "reconstruction",
        "Rolled-back events are not applied",
        "Events in a rolled-back transaction never became durable, so they are "
        "recorded in the history but excluded from the reconstructed state.",
        "{record}: event at {source_file}:{log_position} was rolled back",
        Severity.NOTICE,
    ),
    _r(
        "R-HIST-006",
        "reconstruction",
        "Events without a known commit are not applied",
        "An event whose transaction was never observed to commit is not applied "
        "to the durable state, because we cannot say it took effect.",
        "{record}: event at {source_file}:{log_position} has no observed commit",
        Severity.WARNING,
    ),
    _r(
        "R-HIST-007",
        "reconstruction",
        "Partial row image",
        "The row image does not carry every column. Columns it omits keep their "
        "last observed value, or stay unobserved if they were never seen - they "
        "are never defaulted or zero-filled.",
        "{record}: {columns} not present in the row image",
        Severity.WARNING,
    ),
    _r(
        "R-HIST-008",
        "reconstruction",
        "Before-image disagrees with the reconstructed state",
        "An event's before-image does not match the state our replay had reached. "
        "That is positive evidence of a change we did not observe, detectable "
        "even when the log index shows no missing file.",
        "{record}: before-image at {source_file}:{log_position} differs on {columns}",
        Severity.WARNING,
    ),
    _r(
        "R-HIST-009",
        "reconstruction",
        "Coverage gap inside a record history",
        "A gap in the log sequence falls inside this record's history. Values "
        "already observed remain valid evidence; what the gap changes is that no "
        "later difference can be attributed with confidence.",
        "{record}: coverage gap after {source_file}:{log_position}",
        Severity.WARNING,
    ),
    _r(
        "R-HIST-010",
        "reconstruction",
        "Undecodable value propagates",
        "An undecodable value in an after-image makes the column undecodable in "
        "the reconstructed state. It never falls back to the previous value, "
        "which would report a stale value as current.",
        "{record}: {column} became undecodable at {source_file}:{log_position}",
        Severity.NOTICE,
    ),
    _r(
        "R-HIST-011",
        "reconstruction",
        "Identity change",
        "The record's primary key changed at this point in its history.",
        "{record}: key changed from {previous_key} at {source_file}:{log_position}",
        Severity.NOTICE,
    ),
    _r(
        "R-HIST-012",
        "reconstruction",
        "Physical state appended",
        "The state read from the tablespace is appended as the final step of the "
        "history, as an observation rather than as a replayed change.",
        "{record}: physical state from page {page_no} offset {page_offset}",
    ),
    # ── Reconciliation ───────────────────────────────────────────────────────
    _r(
        "R-RECON-000",
        "reconciliation",
        "Classification precedence",
        "Field classifications are decided by a fixed ladder, top down, first "
        "match wins. The ladder is total and its branches are mutually exclusive, "
        "so every field receives exactly one classification and no field falls "
        "through.",
        "Classification ladder applied to {field_count} field(s)",
    ),
    _r(
        "R-RECON-001",
        "reconciliation",
        "Values agree",
        "The reconstructed value and the physical value agree, and no coverage "
        "limitation touches this record.",
        "{record}.{field}: {log} matches physical",
        Severity.INFO,
        ReconResult.EXACT,
    ),
    _r(
        "R-RECON-002",
        "reconciliation",
        "Values agree under limited coverage",
        "The values agree, but a coverage gap or a partial row image means we "
        "cannot assert the agreement is complete.",
        "{record}.{field}: {log} matches physical, under limited coverage",
        Severity.NOTICE,
        ReconResult.STRONG,
    ),
    _r(
        "R-RECON-003",
        "reconciliation",
        "Comparable field values differ",
        "The values differ and the log coverage for this record is complete, so "
        "the difference cannot be explained by evidence we were not given.",
        "{record}.{field}: log {log} vs physical {phys}",
        Severity.WARNING,
        ReconResult.CONFLICTING,
    ),
    _r(
        "R-RECON-004",
        "reconciliation",
        "Values differ across a coverage gap",
        "The values differ, but a missing or truncated log could contain the "
        "change that explains it. The difference is reported as unresolved. This "
        "is the rule that keeps an evidence gap from being presented as "
        "tampering.",
        "{record}.{field}: log {log} vs physical {phys}, explainable by a coverage gap",
        Severity.WARNING,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-RECON-005",
        "reconciliation",
        "No log-derived value",
        "No observed event says anything about this column, so there is nothing "
        "to compare the physical value against.",
        "{record}.{field}: not observed in any event",
        Severity.NOTICE,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-RECON-006",
        "reconciliation",
        "No physical value",
        "The tablespace holds no observable value for this column - either no "
        "physical record was correlated, or the column is absent from it.",
        "{record}.{field}: no physical value observed",
        Severity.NOTICE,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-RECON-007",
        "reconciliation",
        "Undecodable value",
        "One side could not be decoded, so no comparison is possible.",
        "{record}.{field}: undecodable ({reason})",
        Severity.NOTICE,
        ReconResult.UNSUPPORTED,
    ),
    _r(
        "R-RECON-008",
        "reconciliation",
        "Column type outside the validated scope",
        "The column's declared type has not been validated by this pipeline, so "
        "any comparison of it would rest on unverified decoding.",
        "{record}.{field}: type {data_type} is outside the validated scope",
        Severity.NOTICE,
        ReconResult.UNSUPPORTED,
    ),
    _r(
        "R-RECON-009",
        "reconciliation",
        "Physical value from a damaged tablespace",
        "innochecksum reported damage in the tablespace this value came from, so "
        "the value cannot be relied on and a difference cannot be attributed.",
        "{record}.{field}: physical value read from a {integrity_status} tablespace",
        Severity.WARNING,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-RECON-010",
        "reconciliation",
        "Values are not type-comparable",
        "The two values cannot be compared without coercing a type, which would "
        "manufacture a result.",
        "{record}.{field}: {log} and {phys} are not of comparable types",
        Severity.NOTICE,
        ReconResult.UNSUPPORTED,
    ),
    _r(
        "R-RECON-011",
        "reconciliation",
        "NULL matches NULL",
        "Both sides hold SQL NULL. That is a genuine match, because NULL is a "
        "value the database stored and not an absence of evidence.",
        "{record}.{field}: NULL on both sides",
        Severity.INFO,
        ReconResult.EXACT,
    ),
    _r(
        "R-RECON-012",
        "reconciliation",
        "Correlation is ambiguous",
        "The record could not be matched to exactly one physical record, so no "
        "comparison of its fields can be attributed.",
        "{record}.{field}: correlation is ambiguous",
        Severity.WARNING,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-RECON-020",
        "reconciliation",
        "Record presence agrees",
        "The log-derived existence of the record matches what the tablespace "
        "holds.",
        "{record}: presence agrees ({presence})",
        Severity.INFO,
        ReconResult.EXACT,
    ),
    _r(
        "R-RECON-021",
        "reconciliation",
        "Record presence conflicts",
        "The log says the record should exist and the tablespace does not hold it "
        "(or the reverse), with complete log coverage.",
        "{record}: log says {log_presence}, tablespace says {phys_presence}",
        Severity.WARNING,
        ReconResult.CONFLICTING,
    ),
    _r(
        "R-RECON-022",
        "reconciliation",
        "Record presence differs across a coverage gap",
        "Presence differs, but a missing log could contain the insert or delete "
        "that explains it.",
        "{record}: presence differs, explainable by a coverage gap",
        Severity.WARNING,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-RECON-023",
        "reconciliation",
        "Deleted remnant matches a logged deletion",
        "The tablespace holds the row with its delete flag set, and the log "
        "records the deletion. The two agree.",
        "{record}: deleted in the log and flagged deleted on page {page_no}",
        Severity.INFO,
        ReconResult.EXACT,
    ),
    _r(
        "R-RECON-030",
        "reconciliation",
        "Physical value matches a rolled-back value",
        "The value in the tablespace equals one produced by an event that was "
        "rolled back. This is reported as an observation with provenance; the "
        "engine draws no conclusion about how the value came to be there.",
        "{record}.{field}: physical value {phys} equals the value from rolled-back {transaction}",
        Severity.WARNING,
    ),
    _r(
        "R-RECON-031",
        "reconciliation",
        "Physical value matches no observed value",
        "The value in the tablespace was never produced by any observed event, "
        "committed or otherwise.",
        "{record}.{field}: physical value {phys} matches no observed event value",
        Severity.WARNING,
    ),
    # ── Roll-up ──────────────────────────────────────────────────────────────
    _r(
        "R-ROLL-001",
        "reconciliation",
        "Record severity is the maximum over its fields",
        "A record is presented at the severity of its most severe field, so a "
        "single conflicting column is never hidden behind agreeing ones.",
        "{record}: most severe field result is {result}",
    ),
    _r(
        "R-ROLL-002",
        "reconciliation",
        "All fields agree",
        "Every field of the record was compared and every one agreed.",
        "{record}: all {count} field(s) agree",
        Severity.INFO,
        ReconResult.EXACT,
    ),
    _r(
        "R-ROLL-003",
        "reconciliation",
        "Every field agrees, under limited coverage",
        "Every field of the record was comparable and every one agreed, but at "
        "least one of those agreements rests on limited coverage or a partial row "
        "image, so the agreement cannot be asserted as complete. Nothing about "
        "this record was left uncompared - that is what separates it from "
        "R-ROLL-004.",
        "{record}: all {count} field(s) agree, under limited coverage",
        Severity.NOTICE,
        ReconResult.STRONG,
    ),
    _r(
        "R-ROLL-004",
        "reconciliation",
        "Only part of the record could be compared",
        "The fields that could be compared agreed and none conflicted, but at "
        "least one field lay outside the validated scope and so was never "
        "examined. The record is reported as partly compared rather than as "
        "agreeing, because a field nobody looked at cannot support agreement.",
        "{record}: {count} of {total} field(s) compared",
        Severity.NOTICE,
        ReconResult.PARTIAL,
    ),
    _r(
        "R-ROLL-005",
        "reconciliation",
        "Evidence is insufficient for a conclusion",
        "Either no field of this record could be compared at all, or at least one "
        "field's evidence was too incomplete to reach a conclusion. In both cases "
        "no verdict is drawn about the record either way.",
        "{record}: evidence is insufficient for a conclusion",
        Severity.WARNING,
        ReconResult.UNRESOLVED,
    ),
    _r(
        "R-ROLL-006",
        "reconciliation",
        "Every field is outside the validated scope",
        "Every field of this record is unsupported. The record is reported as "
        "unsupported, never as agreeing - nothing about it was examined.",
        "{record}: all {count} field(s) are outside the validated scope",
        Severity.NOTICE,
        ReconResult.UNSUPPORTED,
    ),
    _r(
        "R-ROLL-007",
        "reconciliation",
        "Record label rendering",
        "A record's summary label names the field when exactly one field carries "
        "the most severe result, and counts them otherwise.",
        "{label}",
    ),
)

RULES: Final[Mapping[str, RuleDefinition]] = MappingProxyType(
    {definition.id: definition for definition in sorted(_DEFINITIONS, key=lambda d: d.id)}
)


def rule(rule_id: str) -> RuleDefinition:
    """Look up a rule, failing loudly on an id that is not in the catalogue."""
    try:
        return RULES[rule_id]
    except KeyError:
        raise KeyError(f"unknown rule id {rule_id!r}") from None


def describe(rule_id: str, context: Mapping[str, str]) -> str:
    """Render a rule's report line from a finding's context.

    A missing placeholder is left visibly unfilled rather than raising: a report
    that shows `{record}` is obviously wrong and gets fixed, whereas an exception
    here would lose an otherwise valid finding.
    """
    definition = rule(rule_id)
    try:
        return definition.template.format(**context)
    except (KeyError, IndexError):
        return definition.template


def rules_for(service: str) -> tuple[RuleDefinition, ...]:
    return tuple(d for d in RULES.values() if d.service == service)


def rule_for_incompleteness_reason(reason: IncompletenessReason) -> RuleDefinition:
    """The single rule that writes this reason.

    Exactly one, always. A reason produced by no rule would be a classification
    assigned by uncited logic; one produced by two would leave a report unable to
    say which reasoning applied. Both are enforced by the catalogue tests, so the
    lookup below cannot legitimately fail.
    """
    matches = [d for d in RULES.values() if d.incompleteness_reason is reason]
    if len(matches) != 1:  # pragma: no cover - prevented by test_rules_catalogue
        raise KeyError(f"{reason} is produced by {len(matches)} rules, expected exactly 1")
    return matches[0]


#: Every incompleteness reason paired with the rule that writes it, in enum
#: declaration order. Rendered into the catalogue document as its own table.
INCOMPLETENESS_REASON_RULES: Final[Mapping[IncompletenessReason, str]] = MappingProxyType(
    {reason: rule_for_incompleteness_reason(reason).id for reason in IncompletenessReason}
)


#: Service names in the order they appear in the pipeline, used to lay out the
#: catalogue document.
SERVICES: Final[tuple[str, ...]] = (
    "values",
    "provenance",
    "grouping",
    "coverage",
    "correlation",
    "reconstruction",
    "reconciliation",
)
