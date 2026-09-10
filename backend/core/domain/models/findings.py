"""Findings: every statement the engine makes about the evidence.

There is deliberately no free prose in the domain. A Finding carries a rule id
and a context dict; the human sentence lives once in `rules.py` (and its readable
twin `docs/correlation-rules.md`) as a template filled from that context.

Three things fall out of that. Report wording is reviewable in a single file
rather than scattered across services. Output is byte-identical across runs
because there is no string built at analysis time. And adding a new message means
adding a catalogue entry - exactly the friction a forensic tool should have.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from core.domain.models.canonical import ProvenanceReference


class Severity(StrEnum):
    """How loudly a finding should be presented. Not a confidence score."""

    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"


class SubjectKind(StrEnum):
    CASE = "case"
    EVIDENCE = "evidence"
    TABLE = "table"
    TRANSACTION = "transaction"
    RECORD = "record"
    FIELD = "field"
    EVENT = "event"


@dataclass(frozen=True, slots=True, order=True)
class SubjectRef:
    """What a finding is about, e.g. ``(RECORD, "accounts:101")``."""

    kind: SubjectKind
    id: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule firing against one subject."""

    rule_id: str
    severity: Severity
    subject: SubjectRef
    context: Mapping[str, str] = field(default_factory=dict)
    provenance: tuple[ProvenanceReference, ...] = ()
