# FactumDB Correlation Rules

Every statement the correlation engine makes about evidence carries an ID from
this catalogue. Nothing in the domain services builds a sentence of its own.

## Why a catalogue

Forensic repeatability means an examiner can re-run the analysis and get the same
conclusions **for the same stated reasons**. That is only checkable if the reasons
are enumerable and stable, so:

- every `Finding` and every field classification carries a `rule_id`;
- the human sentence lives once, here and in `backend/core/domain/rules.py`, as a
  template filled from the finding's context;
- report wording is reviewable in one place rather than scattered across services;
- output is byte-identical across runs, because no string is composed at analysis
  time;
- adding a new message means adding a catalogue entry — exactly the friction a
  forensic tool should have.

The tables below are **generated** from `backend/core/domain/rules.py`. Run
`py -3.11 tools/render_rules_doc.py --write` from `backend/` after editing the
catalogue; a test fails the build if this file goes stale. The prose sections are
hand-written and preserved.

## How to read a rule

**Statement** is normative — it says what the rule asserts about evidence, phrased
so a reviewer can judge whether it is defensible. **Produces** is the classification
the rule writes, where it writes one: either a reconciliation result (`Exact`,
`Conflicting`, …) or an `incompleteness_reason` value. **Severity** is how loudly the
finding is presented; it is *not* a confidence score. The engine has no confidence
scoring, deliberately — classification is rule-based and deterministic.

A statement ending in **Defers to:** names another rule that supplies a distinction
this one does not itself make. Those cross-references are declared as a field on
`RuleDefinition` and checked by a test, so they cannot rot into prose that points
at a rule that no longer exists.

**Casing is deliberate and load-bearing.** Enum values appear in two forms:
`NO_TERMINATOR_IN_RANGE` in prose and statements is the Python enum *member name*;
`no_terminator_in_range` in the structured columns is the *stored string value* —
what actually lands in SQLite, matching how `docs/sqlite-schema.md` stores
`rolled_back` and `committed`. So a reader can tell at a glance whether a statement
is discussing the concept or specifying the literal that gets persisted. Tests
enforce both halves: statements must name the member, generated columns must render
the value.

Every classification the engine writes is claimed by exactly one rule. That is the
mechanism behind the first bullet above: if a service assigns an enum value, some
rule has to have declared it, and the tests fail if one does not.

## Two rules that carry the most weight

`R-RECON-003` (Conflicting) and `R-RECON-004` (Unresolved) differ only in whether
the log coverage for the record is complete. That single condition is what
separates "the evidence disagrees" from "we were not given enough evidence to
say", and getting it wrong in the permissive direction would mean presenting an
evidence gap as tampering. Architecture.md §5.14 is the worked example.

`R-CORR-020` (table has no primary key) is the other one. Without a primary key
there is no identity the log and the tablespace can both express — InnoDB's
internal row id is not visible to `mysqlbinlog` — so the engine correlates
nothing rather than synthesising an identity it cannot observe.

---

## ADR-01 — Transactions have three statuses, not four

**Context.** `Architecture.md` §3.5 and the root `README.md` both say transaction
grouping yields "committed, rolled-back, incomplete, **or unresolved**". But
`docs/canonical-model.md` §5, the `CHECK` constraint on `transactions` in
`docs/sqlite-schema.md`, and `TxStatus` in `frontend/src/data/types.ts` all allow
exactly three. Three independent artefacts against one sentence.

**Decision.** Keep the three canonical statuses. Carry the fourth concept as a
separate `incompleteness_reason` field on `TransactionGroup`:

| Reason | Meaning |
|---|---|
| `NO_TERMINATOR_IN_RANGE` | the transaction began and the last available log ends with it still open, with no later file provable |
| `LOG_FILE_MISSING_IN_SEQUENCE` | the index lists a log we were not given, and it sits where the terminator would be |
| `EVENTS_WITHOUT_BEGIN` | the earliest log begins part-way through a transaction: row events precede every marker in the evidence |
| `MARKER_WITHOUT_EVENTS` | a marker whose events were not decoded, or could not be claimed |

The first two are the same symptom — no terminator observed — distinguished by
whether the index can name the file that would resolve it. That distinction is
worth carrying because a bounded gap ("binlog.000019 is missing") supports a
much more specific statement to an examiner than an unbounded one ("the evidence
stops here"). Each reason is written by exactly one rule; see the generated
**Transaction incompleteness reasons** table below for the mapping.

**When there is no index at all**, the bounded claim is simply unavailable: we
cannot name a file we were never told existed. `NO_TERMINATOR_IN_RANGE` therefore
applies by default, and `LOG_FILE_MISSING_IN_SEQUENCE` can never be written. That
is a statement about the limits of our evidence, not a weaker finding —
`R-COV-001` separately records that coverage is unknown, and it is `R-COV-001`,
not the transaction's reason, that keeps later differences unresolved. All three
rules state this explicitly so the default is cited rather than inferred.

`EVENTS_WITHOUT_BEGIN` is deliberately narrow. It covers only a run of events
preceding *every* marker in the evidence, which is observable proof that the log
begins mid-transaction. An unclaimed event anywhere else is left grouped with
nothing under `R-GRP-011`: there, no evidence says which transaction it belonged
to or that it belonged with any other orphan, and grouping such events together
would assert a shared transaction nobody observed.

**Rationale.** "Unresolved" applied to a transaction always *means* "we did not
observe its terminator", which is already what `incomplete` says. What the
Architecture sentence is reaching for is the **why**, and naming the why is
strictly more informative than a fourth status would be. Keeping three also
avoids a genuine ambiguity: `Unresolved` is already one of the six reconciliation
classifications, and a report using the same word for a transaction status and a
comparison outcome would be harder to read, not easier.

**Consequences.** The SQLite `CHECK`, the adapter contract and the UI badge set
are all unchanged. `Architecture.md` §3.5 and `README.md` should drop the words
"or unresolved" — a one-line edit to each.

This catalogue was itself updated by the decision, and this paragraph is the
record of what it touched.

- `R-GRP-004` originally covered "no terminator observed" as a single symptom
  without saying why. It is now split into `R-GRP-004` (unbounded, deferring to
  `R-COV-003`) and `R-GRP-014` (bounded by a named missing file, deferring to
  `R-COV-002`).
- `R-GRP-004` additionally defers to `R-COV-001` as the no-index default, and
  `R-GRP-014` states that it can never apply without an index. `R-COV-001` names
  both from its own side, so the case is cited from every direction a reader
  might approach it.
- `R-GRP-004`, `R-GRP-005`, `R-GRP-006` and `R-GRP-014` each declare the
  `incompleteness_reason` value they write, and `R-COV-002`/`R-COV-003` name the
  grouping rule that cites them.

The declarations are fields on `RuleDefinition`, not just prose: tests assert that
every enum value is claimed by exactly one rule and that every cross-reference
resolves. That is what stops the assignment happening as uncited logic inside
`TransactionGroupingService`.

---

## ADR-02 — A record's canonical identity is its latest primary key

**Context.** An `UPDATE` may change the primary key. The record before and the
record after are the same row, so the engine must decide which key value names it.

**Decision.** The **terminal (latest)** key in the continuity chain is canonical.
Earlier keys become `identity_aliases` on the `RecordCorrelation` and produce an
`IDENTITY_CHANGE` step in the history.

**Rationale.** The tablespace holds the current key, so a latest-key identity
makes the physical match direct rather than requiring the alias chain to be walked
first. It also matches what the examiner reads on screen — the record is listed
under the key it has now.

**Rejected alternative.** Using the *earliest* key would keep record IDs stable
when a case is re-imported over a shorter log range, which is a real advantage for
comparing two analyses. It was rejected because it makes the common case (matching
against the tablespace) indirect in order to improve a rarer one.

**Ambiguity is never resolved by this rule.** If two distinct keys would have to
merge into one identity, or one key would gain two successors, or the chain is
cyclic, the identities stay separate and `R-CORR-011` is emitted. The rule picks
between defensible readings; it does not manufacture one.

---

## Note — unclaimed events: `R-GRP-005` and `R-GRP-011` narrowed

Unrelated to the decisions above. `R-GRP-005` and `R-GRP-011` previously described
overlapping conditions for an event no marker claims: one grouped such events into
a synthesised transaction, the other refused to invent a container for them. Both
could read as applying to the same event.

They are now mutually exclusive, split on observable evidence. `R-GRP-005` covers
only a run of events preceding *every* marker in the evidence — proof that the
earliest log begins part-way through a transaction. `R-GRP-011` covers an unclaimed
event anywhere else, and groups it with nothing. See their statements below; each
names the other.

This is recorded separately rather than under ADR-01 because it is not downstream
of that decision: the two statements contradicted each other regardless of whether
the fourth concept became a status or a reason field. Listing it there would have
attributed the fix to a cause that did not produce it.

---

## Rule tables

<!-- BEGIN GENERATED RULES -->

### Transaction incompleteness reasons

`incomplete` says the terminator was not observed; `incompleteness_reason` says why.
Each value is written by exactly one rule, and no other rule may write it — a test
enforces both halves of that. See ADR-01 for why this is a field rather than a fourth
transaction status.

| Reason | Written by | Defers to | Rule title |
|---|---|---|---|
| `no_terminator_in_range` | `R-GRP-004` | `R-COV-001`, `R-COV-003` | Terminator missing at the end of the available log |
| `log_file_missing_in_sequence` | `R-GRP-014` | `R-COV-002` | Terminator falls inside a log file we were not given |
| `events_without_begin` | `R-GRP-005` | `R-GRP-011` | Log begins part-way through a transaction |
| `marker_without_events` | `R-GRP-006` | — | Marker claimed no events |

### Value comparison

Every equality decision in the engine is made in one function, `core/domain/models/values.py::compare`. These rules are what it can conclude.

| ID | Title | Statement | Produces | Severity |
|---|---|---|---|---|
| `R-VAL-001` | Numeric values compare by value | Numeric values are compared as decimals, so representations that differ only in formatting are treated as equal. NULL compared with NULL is a match, because NULL is an observation. | — | info |
| `R-VAL-002` | Binary floats are not comparable | Binary floating point values are never compared. Two values that print identically can differ in their last bits, so neither equality nor inequality can be asserted defensibly. | — | notice |
| `R-VAL-003` | Strings compare byte-exactly | Strings are compared byte for byte, with no case folding and no trimming. MySQL's default collation is case-insensitive, but the collation in force is not observable in the evidence, so a difference is reported rather than assumed away. | — | info |
| `R-VAL-004` | Naive timestamps are not comparable | A timestamp without a timezone has no defined instant and is never compared against a UTC value. | — | notice |
| `R-VAL-005` | Undecodable values are never equal | A value the adapter could not decode is never equal to anything, including another undecodable value. Two unreadable columns are not evidence of agreement. | — | notice |
| `R-VAL-006` | Unobserved values are never equal | A column no evidence speaks to is never equal to anything. Absence of an observation is not an observation of absence. | — | notice |
| `R-VAL-007` | Unvalidated column types are not compared | A column whose declared type is outside the validated subset is not compared, because our decoding of it has not been verified. | — | notice |
| `R-VAL-008` | Values of different types are not compared | Two values of incompatible types are not coerced into a common type to force a comparison. | — | notice |

### Provenance

Rules about our ability to trace a finding back to raw tool output.

| ID | Title | Statement | Produces | Severity |
|---|---|---|---|---|
| `R-PROV-001` | Provenance is incomplete | The adapter did not record a tool run for this evidence, so findings derived from it carry only a source file and position. The finding still stands; the chain back to the raw output does not. | — | warning |

### Transaction grouping

`TransactionGroupingService`. Transaction markers are the authority - the adapter parses BEGIN, GTID, XID and ROLLBACK, and the domain never re-parses them.

| ID | Title | Statement | Produces | Severity |
|---|---|---|---|---|
| `R-GRP-001` | Transaction bounded by GTID | A GTID identifies one transaction uniquely across the whole server, so it is the strongest available transaction boundary. | — | info |
| `R-GRP-002` | Transaction committed at XID | An XID event marks a committed transaction boundary. | — | info |
| `R-GRP-003` | Transaction rolled back | A ROLLBACK marker means the events inside the transaction were never durable. They are retained as evidence but never applied to a reconstructed state. | — | notice |
| `R-GRP-004` | Terminator missing at the end of the available log | The transaction began and the last log we were given ends with it still open, with no later file listed in the index. Its outcome is unknown and the gap is unbounded - we cannot say how much is missing, only that the record stops here. Sets incompleteness_reason to NO_TERMINATOR_IN_RANGE. The evidence for that boundary is stated by R-COV-003. This rule is also the default when no index is available at all: without one, a missing file cannot be proved, so the bounded reason cannot be claimed and the unbounded reason applies. That is a statement about our evidence, not about the server - R-COV-001 separately records that coverage is unknown, and it is R-COV-001 rather than this rule that keeps later differences unresolved. **Defers to:** `R-COV-001`, `R-COV-003`. | `no_terminator_in_range` | warning |
| `R-GRP-005` | Log begins part-way through a transaction | Unclaimed row events precede every marker in the evidence set - nothing at all comes before them. That is observable evidence that the earliest log we hold begins part-way through a transaction whose opening marker lies in a region we do not have, so the events are grouped into one synthesised container to keep them together and ordered. The container is never treated as committed, and it is labelled as synthesised so no reader mistakes it for an observed transaction. Sets incompleteness_reason to EVENTS_WITHOUT_BEGIN. This rule applies only to that leading run; an unclaimed event anywhere else falls under R-GRP-011 and is not grouped with anything. **Defers to:** `R-GRP-011`. | `events_without_begin` | warning |
| `R-GRP-006` | Marker claimed no events | A transaction marker exists but none of the events it refers to were decoded, or none could be claimed, so the transaction's content is unknown. Sets incompleteness_reason to MARKER_WITHOUT_EVENTS. | `marker_without_events` | warning |
| `R-GRP-007` | Sessions separated by GTID or thread | Concurrent sessions interleave in the log, so events are assigned to transactions by GTID or thread identity - never by adjacency of log positions. | — | info |
| `R-GRP-008` | Interleaving cannot be resolved | Events fall inside this transaction's position range but neither the marker nor the events carry a session identifier, so membership cannot be established. The events are left ungrouped rather than assigned on the assumption that the log is sequential. | — | warning |
| `R-GRP-009` | Listed event was not decoded | The marker refers to an event position for which no decoded event exists, so part of the transaction's content is missing. | — | warning |
| `R-GRP-010` | Event inside range but not listed | An event falls within a transaction's position range but the marker does not list it. It is not claimed, because it may belong to an interleaved session. | — | notice |
| `R-GRP-011` | Event belongs to no transaction | The event is claimed by no marker, and markers do exist before it, so it is not the leading run that R-GRP-005 covers. Nothing observable says which transaction it belonged to, nor that it belonged with any other unclaimed event, so it stays on the timeline as observed evidence, is never treated as durable, and is grouped with nothing. Grouping mid-stream orphans together would assert a shared transaction that no evidence supports. **Defers to:** `R-GRP-005`. | — | warning |
| `R-GRP-012` | Duplicate GTID | The same GTID appears in more than one place in the evidence. Both occurrences are kept, because duplicated or relay-log evidence is itself a finding. | — | warning |
| `R-GRP-013` | Duplicate event position | Two decoded events share a source file and log position, which cannot happen in one log. The first is used and both are reported. | — | warning |
| `R-GRP-014` | Terminator falls inside a log file we were not given | The transaction began and the index proves a log file between it and its terminator was not provided. Its outcome is unknown but the gap is bounded: we can name the file that would resolve it, which is a materially stronger statement than the log merely stopping. Sets incompleteness_reason to LOG_FILE_MISSING_IN_SEQUENCE. The evidence for that boundary is stated by R-COV-002. This rule requires an index and can never apply without one - naming a file we were never told existed would be asserting more than the evidence supports, so R-GRP-004 applies instead. **Defers to:** `R-COV-002`. | `log_file_missing_in_sequence` | warning |
| `R-TXID-001` | Transaction id derived from GTID | Transaction ids are derived from the evidence, never from a counter, so re-running the analysis over the same evidence yields the same ids. | — | info |
| `R-TXID-002` | Transaction id derived from log position | With no GTID available, the transaction is identified by its log file and BEGIN position, which are equally reproducible. | — | info |

### Evidence coverage

What we can and cannot see. These rules decide whether a difference is reported as a conflict or as unresolved, which is the most consequential distinction the tool makes.

| ID | Title | Statement | Produces | Severity |
|---|---|---|---|---|
| `R-COV-001` | No binlog index available | Without mysql-bin.index there is no way to know whether the logs we were given are all the logs that existed. Coverage is therefore treated as incomplete - absence of the index is never read as proof of completeness. It also means no file can be shown to be missing, so an unterminated transaction takes the unbounded reason under R-GRP-004 and never the bounded one under R-GRP-014. | — | warning |
| `R-COV-002` | Binlog file missing from the evidence set | The index lists a log file that was not provided. Changes recorded in it cannot be observed, and any state difference that file could explain is reported as unresolved rather than as a conflict. When such a file falls between a transaction and its terminator, this is the evidence R-GRP-014 cites for LOG_FILE_MISSING_IN_SEQUENCE. | — | warning |
| `R-COV-003` | Log ends mid-transaction | The last available log ends with a transaction still open, so events after that point are not observable. This is the evidence R-GRP-004 cites for NO_TERMINATOR_IN_RANGE, and it applies only when the index lists no later file - otherwise the stronger R-COV-002 applies instead. | — | warning |
| `R-COV-004` | Coverage gap spans a record | A gap in the log sequence falls within this record's observed history, so its reconstructed state may be missing changes. | — | warning |
| `R-COV-005` | Snapshot timing unknown | The time at which the tablespace was acquired, relative to the last observed log event, is not recorded. A note for the examiner only: it does not by itself weaken any individual comparison. | — | notice |

### Record correlation

`RecordCorrelationService`. Linking events and physical rows to record identities.

| ID | Title | Statement | Produces | Severity |
|---|---|---|---|---|
| `R-CORR-001` | Primary key exact match | The event's primary key value matches a physical record's primary key exactly. | — | info |
| `R-CORR-002` | Composite primary key exact match | Every component of the composite primary key matches exactly. | — | info |
| `R-CORR-003` | Key columns absent from the row image | A key column is missing or undecodable in the row image, so no identity can be established for this event. No partial key is guessed at. | — | warning |
| `R-CORR-010` | Identity continued across a primary key update | An update changed the primary key. The before and after images link the two key values as one record, whose canonical identity is the latest key - the value the tablespace now holds. | — | notice |
| `R-CORR-011` | Key continuity is ambiguous | Two or more key changes would have to be merged into one identity in a way the evidence does not determine. The identities are kept separate and the ambiguity is reported rather than resolved by choosing one. | — | warning |
| `R-CORR-012` | Key reused after deletion | The key was deleted and later inserted again. It remains one record with an interval of absence in its history, because the schema says it is one key. | — | notice |
| `R-CORR-020` | Table has no primary key | Without a primary key there is no identity that both the log and the tablespace can express - InnoDB's internal row id is not visible to mysqlbinlog. Events for this table are not correlated, because synthesising an identity would be fabricating one. | Unsupported | warning |
| `R-CORR-021` | Schema not available | A binlog event names a table for which no schema was extracted, so its columns cannot be interpreted. | Unsupported | warning |
| `R-CORR-022` | Multiple physical candidates | More than one live physical record carries this key, so the correlation is ambiguous. None is chosen, and every comparison for this record becomes unresolved. | Unresolved | warning |
| `R-CORR-023` | Deleted remnant present alongside a live record | A deleted remnant carries the same key as the live record. The live record is used for comparison and the remnant is retained as evidence. | — | notice |
| `R-CORR-030` | Table not in the evidence scope | Events reference a table for which no tablespace was registered. Its physical side is unobserved, so differences are unresolved rather than conflicting - we were not given the file, which is not the same as the row not being there. | Unresolved | warning |
| `R-CORR-031` | Physical record with no log events | The row exists in the tablespace but no observed event produced it. With complete log coverage that is a conflict; with a gap it is unresolved. | — | notice |
| `R-ID-001` | Primary key rendering | Key values are rendered exactly: integers and decimals as written, timestamps as ISO-8601 UTC, strings verbatim. A key value that cannot be rendered exactly yields no record identity at all. | — | info |
| `R-ID-002` | Key value contains the composite separator | A key value containing the composite key separator makes the rendered key ambiguous: one value containing the separator and two values joined by it produce the same text. The ambiguity is reported rather than escaped away, because it is a real reason to distrust the identity. | — | warning |
| `R-ID-003` | Record id namespace collision | Two databases in this case contain a table of the same name, so their record ids collide. Records are kept separate internally by their qualified table name, but any display that shows only the id is ambiguous. | — | warning |

### State reconstruction

`StateReconstructionService`. Replaying correlated events into record histories.

| ID | Title | Statement | Produces | Severity |
|---|---|---|---|---|
| `R-HIST-001` | Events ordered by log position | Events are replayed in log sequence and position order, never by timestamp. Binary log timestamps have one-second resolution and are converted from server-local time, so events within a transaction routinely share one. Timestamps are shown but never used to order. | — | info |
| `R-HIST-002` | Earliest state taken from the first observed event | The starting state is read from the first event's before-image, or is absence when the first event is an insert. Nothing is extrapolated backwards past the first observation. | — | info |
| `R-HIST-003` | After-image applied | A committed event's after-image is applied to the reconstructed state. | — | info |
| `R-HIST-004` | Delete sets the record absent | A committed delete makes the record absent from the reconstructed state. | — | info |
| `R-HIST-005` | Rolled-back events are not applied | Events in a rolled-back transaction never became durable, so they are recorded in the history but excluded from the reconstructed state. | — | notice |
| `R-HIST-006` | Events without a known commit are not applied | An event whose transaction was never observed to commit is not applied to the durable state, because we cannot say it took effect. | — | warning |
| `R-HIST-007` | Partial row image | The row image does not carry every column. Columns it omits keep their last observed value, or stay unobserved if they were never seen - they are never defaulted or zero-filled. | — | warning |
| `R-HIST-008` | Before-image disagrees with the reconstructed state | An event's before-image does not match the state our replay had reached. That is positive evidence of a change we did not observe, detectable even when the log index shows no missing file. | — | warning |
| `R-HIST-009` | Coverage gap inside a record history | A gap in the log sequence falls inside this record's history. Values already observed remain valid evidence; what the gap changes is that no later difference can be attributed with confidence. | — | warning |
| `R-HIST-010` | Undecodable value propagates | An undecodable value in an after-image makes the column undecodable in the reconstructed state. It never falls back to the previous value, which would report a stale value as current. | — | notice |
| `R-HIST-011` | Identity change | The record's primary key changed at this point in its history. | — | notice |
| `R-HIST-012` | Physical state appended | The state read from the tablespace is appended as the final step of the history, as an observation rather than as a replayed change. | — | info |

### Reconciliation

`ReconciliationService`. Comparing reconstructed state against the tablespace, per field and then rolled up per record.

| ID | Title | Statement | Produces | Severity |
|---|---|---|---|---|
| `R-RECON-000` | Classification precedence | Field classifications are decided by a fixed ladder, top down, first match wins. The ladder is total and its branches are mutually exclusive, so every field receives exactly one classification and no field falls through. | — | info |
| `R-RECON-001` | Values agree | The reconstructed value and the physical value agree, and no coverage limitation touches this record. | Exact | info |
| `R-RECON-002` | Values agree under limited coverage | The values agree, but a coverage gap or a partial row image means we cannot assert the agreement is complete. | Strong | notice |
| `R-RECON-003` | Comparable field values differ | The values differ and the log coverage for this record is complete, so the difference cannot be explained by evidence we were not given. | Conflicting | warning |
| `R-RECON-004` | Values differ across a coverage gap | The values differ, but a missing or truncated log could contain the change that explains it. The difference is reported as unresolved. This is the rule that keeps an evidence gap from being presented as tampering. | Unresolved | warning |
| `R-RECON-005` | No log-derived value | No observed event says anything about this column, so there is nothing to compare the physical value against. | Unresolved | notice |
| `R-RECON-006` | No physical value | The tablespace holds no observable value for this column - either no physical record was correlated, or the column is absent from it. | Unresolved | notice |
| `R-RECON-007` | Undecodable value | One side could not be decoded, so no comparison is possible. | Unsupported | notice |
| `R-RECON-008` | Column type outside the validated scope | The column's declared type has not been validated by this pipeline, so any comparison of it would rest on unverified decoding. | Unsupported | notice |
| `R-RECON-009` | Physical value from a damaged tablespace | innochecksum reported damage in the tablespace this value came from, so the value cannot be relied on and a difference cannot be attributed. | Unresolved | warning |
| `R-RECON-010` | Values are not type-comparable | The two values cannot be compared without coercing a type, which would manufacture a result. | Unsupported | notice |
| `R-RECON-011` | NULL matches NULL | Both sides hold SQL NULL. That is a genuine match, because NULL is a value the database stored and not an absence of evidence. | Exact | info |
| `R-RECON-012` | Correlation is ambiguous | The record could not be matched to exactly one physical record, so no comparison of its fields can be attributed. | Unresolved | warning |
| `R-RECON-020` | Record presence agrees | The log-derived existence of the record matches what the tablespace holds. | Exact | info |
| `R-RECON-021` | Record presence conflicts | The log says the record should exist and the tablespace does not hold it (or the reverse), with complete log coverage. | Conflicting | warning |
| `R-RECON-022` | Record presence differs across a coverage gap | Presence differs, but a missing log could contain the insert or delete that explains it. | Unresolved | warning |
| `R-RECON-023` | Deleted remnant matches a logged deletion | The tablespace holds the row with its delete flag set, and the log records the deletion. The two agree. | Exact | info |
| `R-RECON-030` | Physical value matches a rolled-back value | The value in the tablespace equals one produced by an event that was rolled back. This is reported as an observation with provenance; the engine draws no conclusion about how the value came to be there. | — | warning |
| `R-RECON-031` | Physical value matches no observed value | The value in the tablespace was never produced by any observed event, committed or otherwise. | — | warning |
| `R-ROLL-001` | Record severity is the maximum over its fields | A record is presented at the severity of its most severe field, so a single conflicting column is never hidden behind agreeing ones. | — | info |
| `R-ROLL-002` | All fields agree | Every field of the record was compared and every one agreed. | Exact | info |
| `R-ROLL-003` | Every field agrees, under limited coverage | Every field of the record was comparable and every one agreed, but at least one of those agreements rests on limited coverage or a partial row image, so the agreement cannot be asserted as complete. Nothing about this record was left uncompared - that is what separates it from R-ROLL-004. | Strong | notice |
| `R-ROLL-004` | Only part of the record could be compared | The fields that could be compared agreed and none conflicted, but at least one field lay outside the validated scope and so was never examined. The record is reported as partly compared rather than as agreeing, because a field nobody looked at cannot support agreement. | Partial | notice |
| `R-ROLL-005` | Evidence is insufficient for a conclusion | Either no field of this record could be compared at all, or at least one field's evidence was too incomplete to reach a conclusion. In both cases no verdict is drawn about the record either way. | Unresolved | warning |
| `R-ROLL-006` | Every field is outside the validated scope | Every field of this record is unsupported. The record is reported as unsupported, never as agreeing - nothing about it was examined. | Unsupported | notice |
| `R-ROLL-007` | Record label rendering | A record's summary label names the field when exactly one field carries the most severe result, and counts them otherwise. | — | info |

**83 rules total.**

<!-- END GENERATED RULES -->
