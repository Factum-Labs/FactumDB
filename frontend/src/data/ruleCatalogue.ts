// Generated from core.domain.rules; update with backend/tools/render_rules_doc.py --write.
import type { ReconResult } from './types'

export const ruleCatalogue: readonly { id: string; category: string; description: string; result: ReconResult | null }[] = [
  {
    "id": "R-VAL-001",
    "category": "Value comparison",
    "description": "Numeric values compare by value",
    "result": null
  },
  {
    "id": "R-VAL-002",
    "category": "Value comparison",
    "description": "Binary floats are not comparable",
    "result": null
  },
  {
    "id": "R-VAL-003",
    "category": "Value comparison",
    "description": "Strings compare byte-exactly",
    "result": null
  },
  {
    "id": "R-VAL-004",
    "category": "Value comparison",
    "description": "Naive timestamps are not comparable",
    "result": null
  },
  {
    "id": "R-VAL-005",
    "category": "Value comparison",
    "description": "Undecodable values are never equal",
    "result": null
  },
  {
    "id": "R-VAL-006",
    "category": "Value comparison",
    "description": "Unobserved values are never equal",
    "result": null
  },
  {
    "id": "R-VAL-007",
    "category": "Value comparison",
    "description": "Unvalidated column types are not compared",
    "result": null
  },
  {
    "id": "R-VAL-008",
    "category": "Value comparison",
    "description": "Values of different types are not compared",
    "result": null
  },
  {
    "id": "R-PROV-001",
    "category": "Provenance",
    "description": "Provenance is incomplete",
    "result": null
  },
  {
    "id": "R-GRP-001",
    "category": "Transaction grouping",
    "description": "Transaction bounded by GTID",
    "result": null
  },
  {
    "id": "R-GRP-002",
    "category": "Transaction grouping",
    "description": "Transaction committed at XID",
    "result": null
  },
  {
    "id": "R-GRP-003",
    "category": "Transaction grouping",
    "description": "Transaction rolled back",
    "result": null
  },
  {
    "id": "R-GRP-004",
    "category": "Transaction grouping",
    "description": "Terminator missing at the end of the available log",
    "result": null
  },
  {
    "id": "R-GRP-005",
    "category": "Transaction grouping",
    "description": "Log begins part-way through a transaction",
    "result": null
  },
  {
    "id": "R-GRP-006",
    "category": "Transaction grouping",
    "description": "Marker claimed no events",
    "result": null
  },
  {
    "id": "R-GRP-007",
    "category": "Transaction grouping",
    "description": "Sessions separated by GTID or thread",
    "result": null
  },
  {
    "id": "R-GRP-008",
    "category": "Transaction grouping",
    "description": "Interleaving cannot be resolved",
    "result": null
  },
  {
    "id": "R-GRP-009",
    "category": "Transaction grouping",
    "description": "Listed event was not decoded",
    "result": null
  },
  {
    "id": "R-GRP-010",
    "category": "Transaction grouping",
    "description": "Event inside range but not listed",
    "result": null
  },
  {
    "id": "R-GRP-011",
    "category": "Transaction grouping",
    "description": "Event belongs to no transaction",
    "result": null
  },
  {
    "id": "R-GRP-012",
    "category": "Transaction grouping",
    "description": "Duplicate GTID",
    "result": null
  },
  {
    "id": "R-GRP-013",
    "category": "Transaction grouping",
    "description": "Duplicate row reference",
    "result": null
  },
  {
    "id": "R-GRP-014",
    "category": "Transaction grouping",
    "description": "Terminator falls inside a log file we were not given",
    "result": null
  },
  {
    "id": "R-TXID-001",
    "category": "Transaction grouping",
    "description": "Transaction id derived from GTID",
    "result": null
  },
  {
    "id": "R-TXID-002",
    "category": "Transaction grouping",
    "description": "Transaction id derived from log position",
    "result": null
  },
  {
    "id": "R-COV-001",
    "category": "Evidence coverage",
    "description": "No binlog index available",
    "result": null
  },
  {
    "id": "R-COV-002",
    "category": "Evidence coverage",
    "description": "Binlog file missing from the evidence set",
    "result": null
  },
  {
    "id": "R-COV-003",
    "category": "Evidence coverage",
    "description": "Log ends mid-transaction",
    "result": null
  },
  {
    "id": "R-COV-004",
    "category": "Evidence coverage",
    "description": "Coverage gap spans a record",
    "result": null
  },
  {
    "id": "R-COV-005",
    "category": "Evidence coverage",
    "description": "Snapshot timing unknown",
    "result": null
  },
  {
    "id": "R-CORR-001",
    "category": "Record correlation",
    "description": "Primary key exact match",
    "result": null
  },
  {
    "id": "R-CORR-002",
    "category": "Record correlation",
    "description": "Composite primary key exact match",
    "result": null
  },
  {
    "id": "R-CORR-003",
    "category": "Record correlation",
    "description": "Key columns absent from the row image",
    "result": null
  },
  {
    "id": "R-CORR-010",
    "category": "Record correlation",
    "description": "Identity continued across a primary key update",
    "result": null
  },
  {
    "id": "R-CORR-011",
    "category": "Record correlation",
    "description": "Key continuity is ambiguous",
    "result": null
  },
  {
    "id": "R-CORR-012",
    "category": "Record correlation",
    "description": "Key reused after deletion",
    "result": null
  },
  {
    "id": "R-CORR-020",
    "category": "Record correlation",
    "description": "Table has no primary key",
    "result": "Unsupported"
  },
  {
    "id": "R-CORR-021",
    "category": "Record correlation",
    "description": "Schema not available",
    "result": "Unsupported"
  },
  {
    "id": "R-CORR-022",
    "category": "Record correlation",
    "description": "Multiple physical candidates",
    "result": "Unresolved"
  },
  {
    "id": "R-CORR-023",
    "category": "Record correlation",
    "description": "Deleted remnant present alongside a live record",
    "result": null
  },
  {
    "id": "R-CORR-030",
    "category": "Record correlation",
    "description": "Table not in the evidence scope",
    "result": "Unresolved"
  },
  {
    "id": "R-CORR-031",
    "category": "Record correlation",
    "description": "Physical record with no log events",
    "result": null
  },
  {
    "id": "R-ID-001",
    "category": "Record correlation",
    "description": "Primary key rendering",
    "result": null
  },
  {
    "id": "R-ID-002",
    "category": "Record correlation",
    "description": "Key value contains the composite separator",
    "result": null
  },
  {
    "id": "R-ID-003",
    "category": "Record correlation",
    "description": "Record id namespace collision",
    "result": null
  },
  {
    "id": "R-HIST-001",
    "category": "State reconstruction",
    "description": "Events ordered by log position",
    "result": null
  },
  {
    "id": "R-HIST-002",
    "category": "State reconstruction",
    "description": "Earliest state taken from the first observed event",
    "result": null
  },
  {
    "id": "R-HIST-003",
    "category": "State reconstruction",
    "description": "After-image applied",
    "result": null
  },
  {
    "id": "R-HIST-004",
    "category": "State reconstruction",
    "description": "Delete sets the record absent",
    "result": null
  },
  {
    "id": "R-HIST-005",
    "category": "State reconstruction",
    "description": "Rolled-back events are not applied",
    "result": null
  },
  {
    "id": "R-HIST-006",
    "category": "State reconstruction",
    "description": "Events without a known commit are not applied",
    "result": null
  },
  {
    "id": "R-HIST-007",
    "category": "State reconstruction",
    "description": "Partial row image",
    "result": null
  },
  {
    "id": "R-HIST-008",
    "category": "State reconstruction",
    "description": "Before-image disagrees with the reconstructed state",
    "result": null
  },
  {
    "id": "R-HIST-009",
    "category": "State reconstruction",
    "description": "Coverage gap inside a record history",
    "result": null
  },
  {
    "id": "R-HIST-010",
    "category": "State reconstruction",
    "description": "Undecodable value propagates",
    "result": null
  },
  {
    "id": "R-HIST-011",
    "category": "State reconstruction",
    "description": "Identity change",
    "result": null
  },
  {
    "id": "R-HIST-012",
    "category": "State reconstruction",
    "description": "Physical state appended",
    "result": null
  },
  {
    "id": "R-RECON-000",
    "category": "Reconciliation",
    "description": "Classification precedence",
    "result": null
  },
  {
    "id": "R-RECON-001",
    "category": "Reconciliation",
    "description": "Values agree",
    "result": "Exact"
  },
  {
    "id": "R-RECON-002",
    "category": "Reconciliation",
    "description": "Values agree under limited coverage",
    "result": "Strong"
  },
  {
    "id": "R-RECON-003",
    "category": "Reconciliation",
    "description": "Comparable field values differ",
    "result": "Conflicting"
  },
  {
    "id": "R-RECON-004",
    "category": "Reconciliation",
    "description": "Values differ across a coverage gap",
    "result": "Unresolved"
  },
  {
    "id": "R-RECON-005",
    "category": "Reconciliation",
    "description": "No log-derived value",
    "result": "Unresolved"
  },
  {
    "id": "R-RECON-006",
    "category": "Reconciliation",
    "description": "No physical value",
    "result": "Unresolved"
  },
  {
    "id": "R-RECON-007",
    "category": "Reconciliation",
    "description": "Undecodable value",
    "result": "Unsupported"
  },
  {
    "id": "R-RECON-008",
    "category": "Reconciliation",
    "description": "Column type outside the validated scope",
    "result": "Unsupported"
  },
  {
    "id": "R-RECON-009",
    "category": "Reconciliation",
    "description": "Physical value from a damaged tablespace",
    "result": "Unresolved"
  },
  {
    "id": "R-RECON-010",
    "category": "Reconciliation",
    "description": "Values are not type-comparable",
    "result": "Unsupported"
  },
  {
    "id": "R-RECON-011",
    "category": "Reconciliation",
    "description": "NULL matches NULL",
    "result": "Exact"
  },
  {
    "id": "R-RECON-012",
    "category": "Reconciliation",
    "description": "Correlation is ambiguous",
    "result": "Unresolved"
  },
  {
    "id": "R-RECON-020",
    "category": "Reconciliation",
    "description": "Record presence agrees",
    "result": "Exact"
  },
  {
    "id": "R-RECON-021",
    "category": "Reconciliation",
    "description": "Record presence conflicts",
    "result": "Conflicting"
  },
  {
    "id": "R-RECON-022",
    "category": "Reconciliation",
    "description": "Record presence differs across a coverage gap",
    "result": "Unresolved"
  },
  {
    "id": "R-RECON-023",
    "category": "Reconciliation",
    "description": "Deleted remnant matches a logged deletion",
    "result": "Exact"
  },
  {
    "id": "R-RECON-030",
    "category": "Reconciliation",
    "description": "Physical value matches a rolled-back value",
    "result": null
  },
  {
    "id": "R-RECON-031",
    "category": "Reconciliation",
    "description": "Physical value matches no observed value",
    "result": null
  },
  {
    "id": "R-ROLL-001",
    "category": "Reconciliation",
    "description": "Record severity is the maximum over its fields",
    "result": null
  },
  {
    "id": "R-ROLL-002",
    "category": "Reconciliation",
    "description": "All fields agree",
    "result": "Exact"
  },
  {
    "id": "R-ROLL-003",
    "category": "Reconciliation",
    "description": "Every field agrees, under limited coverage",
    "result": "Strong"
  },
  {
    "id": "R-ROLL-004",
    "category": "Reconciliation",
    "description": "Only part of the record could be compared",
    "result": "Partial"
  },
  {
    "id": "R-ROLL-005",
    "category": "Reconciliation",
    "description": "Evidence is insufficient for a conclusion",
    "result": "Unresolved"
  },
  {
    "id": "R-ROLL-006",
    "category": "Reconciliation",
    "description": "Every field is outside the validated scope",
    "result": "Unsupported"
  },
  {
    "id": "R-ROLL-007",
    "category": "Reconciliation",
    "description": "Record label rendering",
    "result": null
  }
]
