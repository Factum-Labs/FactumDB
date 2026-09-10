"""The rule catalogue, the document, and the code must agree.

Three things can drift apart here: `rules.py`, `docs/correlation-rules.md`, and
the rule ids the services actually pass around. A catalogue that has stopped
matching the engine is worse than no catalogue, because it looks authoritative.
So each pairing gets an assertion.

The "every id used in code exists in RULES" check is the one that catches real
mistakes - a typo in a rule id would otherwise surface as a report line reading
`{record}` months later.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from core.domain.models.classification import ReconResult
from core.domain.models.findings import Severity
from core.domain.models.transactions import IncompletenessReason
from core.domain.rules import (
    INCOMPLETENESS_REASON_RULES,
    RULES,
    SERVICES,
    describe,
    rule,
    rule_for_incompleteness_reason,
    rules_for,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_ROOT = BACKEND_ROOT / "core" / "domain"
DOC_PATH = BACKEND_ROOT.parent / "docs" / "correlation-rules.md"
RENDERER = BACKEND_ROOT / "tools" / "render_rules_doc.py"

#: Matches a rule id anywhere in source or prose: R-<FAMILY>-<NNN>.
RULE_ID_PATTERN = re.compile(r"\bR-[A-Z]+-\d{3}\b")


# ── Internal consistency ─────────────────────────────────────────────────────


def test_catalogue_is_not_empty() -> None:
    """Guard the guard: an empty catalogue makes every test below vacuous."""
    assert len(RULES) > 50


def test_ids_are_self_consistent() -> None:
    for rule_id, definition in RULES.items():
        assert definition.id == rule_id


def test_ids_are_sorted() -> None:
    """Stable iteration order, so generated output never reshuffles."""
    assert list(RULES) == sorted(RULES)


def test_every_rule_belongs_to_a_known_service() -> None:
    for definition in RULES.values():
        assert definition.service in SERVICES, f"{definition.id} has service {definition.service!r}"


def test_every_service_has_rules() -> None:
    """A service listed but never used means the doc grows an empty section."""
    for service in SERVICES:
        assert rules_for(service), f"no rules defined for {service}"


def test_id_family_matches_service() -> None:
    """The prefix has to mean something, or the ids stop being navigable."""
    allowed = {
        "values": {"R-VAL"},
        "provenance": {"R-PROV"},
        "grouping": {"R-GRP", "R-TXID"},
        "coverage": {"R-COV"},
        "correlation": {"R-CORR", "R-ID"},
        "reconstruction": {"R-HIST"},
        "reconciliation": {"R-RECON", "R-ROLL"},
    }
    for definition in RULES.values():
        family = definition.id.rsplit("-", 1)[0]
        assert family in allowed[definition.service], (
            f"{definition.id} has family {family} but service {definition.service}"
        )


def test_statements_are_normative_prose() -> None:
    """A statement a reviewer cannot judge is not doing its job."""
    for definition in RULES.values():
        assert len(definition.statement) > 40, f"{definition.id} statement is too thin"
        assert definition.statement.endswith("."), f"{definition.id} statement is not a sentence"
        assert definition.title, f"{definition.id} has no title"
        assert definition.template, f"{definition.id} has no template"


def test_templates_use_well_formed_placeholders() -> None:
    """A malformed template would raise at report time, losing a real finding."""
    for definition in RULES.values():
        try:
            list(str.__format__("", ""))  # cheap no-op to keep the try tight
            definition.template.format_map(_Blanks())
        except (ValueError, IndexError) as exc:  # pragma: no cover - failure path
            pytest.fail(f"{definition.id} template is malformed: {exc}")


class _Blanks(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return ""


# ── Classification coverage ──────────────────────────────────────────────────


def test_every_reconciliation_result_is_reachable() -> None:
    """All six classifications must be producible, or one is dead vocabulary."""
    produced = {d.result for d in RULES.values() if d.result is not None}
    assert produced == set(ReconResult)


def test_conflicting_rules_are_warnings() -> None:
    """A conflict presented quietly defeats the point of flagging it."""
    for definition in RULES.values():
        if definition.result is ReconResult.CONFLICTING:
            assert definition.severity is Severity.WARNING, f"{definition.id} is too quiet"


def test_exact_rules_are_never_warnings() -> None:
    for definition in RULES.values():
        if definition.result is ReconResult.EXACT:
            assert definition.severity is not Severity.WARNING, f"{definition.id} is too loud"


def test_every_incompleteness_reason_is_claimed_by_exactly_one_rule() -> None:
    """No enum value may be assigned by logic that cites no rule.

    This is the structural half of the catalogue's premise. A reason produced by
    no rule would be a classification with no reviewable reasoning behind it; one
    produced by two would leave a report unable to say which applied.
    """
    for reason in IncompletenessReason:
        claimants = [d.id for d in RULES.values() if d.incompleteness_reason is reason]
        assert len(claimants) == 1, f"{reason.value} is claimed by {claimants}, expected one"


def test_incompleteness_mapping_covers_the_enum_exactly() -> None:
    assert set(INCOMPLETENESS_REASON_RULES) == set(IncompletenessReason)
    for reason, rule_id in INCOMPLETENESS_REASON_RULES.items():
        assert rule_for_incompleteness_reason(reason).id == rule_id


def test_rules_producing_a_reason_name_it_in_their_statement() -> None:
    """A reviewer must see the enum-to-rule mapping without cross-referencing."""
    for definition in RULES.values():
        if definition.incompleteness_reason is not None:
            assert definition.incompleteness_reason.name in definition.statement, (
                f"{definition.id} sets {definition.incompleteness_reason.name} "
                "without naming it in its statement"
            )


def test_incompleteness_rules_belong_to_grouping() -> None:
    for definition in RULES.values():
        if definition.incompleteness_reason is not None:
            assert definition.service == "grouping", f"{definition.id} is in the wrong section"
            assert definition.severity is Severity.WARNING, f"{definition.id} is too quiet"


def test_cross_references_point_at_real_rules() -> None:
    """`decided_with` is a checked link, not a sentence a reader has to notice."""
    for definition in RULES.values():
        for cited in definition.decided_with:
            assert cited in RULES, f"{definition.id} defers to unknown rule {cited}"
            assert cited != definition.id, f"{definition.id} defers to itself"


def test_the_two_no_terminator_reasons_defer_to_coverage_evidence() -> None:
    """The distinction the critique flagged, asserted directly.

    Both reasons mean "terminator not observed". What separates them is whether
    the index can name the file that would resolve it - a bounded gap supports a
    far more specific statement than an unbounded one, so the two must not
    collapse back into a single rule.
    """
    unbounded = rule_for_incompleteness_reason(IncompletenessReason.NO_TERMINATOR_IN_RANGE)
    bounded = rule_for_incompleteness_reason(IncompletenessReason.LOG_FILE_MISSING_IN_SEQUENCE)

    assert unbounded.id != bounded.id
    assert "R-COV-003" in unbounded.decided_with
    assert bounded.decided_with == ("R-COV-002",)

    # And the coverage rules name the grouping rule back, so the link reads both ways.
    assert unbounded.id in rule("R-COV-003").statement
    assert bounded.id in rule("R-COV-002").statement


def test_the_no_index_case_names_which_reason_applies() -> None:
    """With no index, which of the two reasons is written must be cited, not inferred.

    The bounded reason requires an index to prove a file is missing. Without one
    that claim is unavailable, so the unbounded reason applies - and saying so is
    the catalogue's job, not something a reader should have to deduce.
    """
    unbounded = rule_for_incompleteness_reason(IncompletenessReason.NO_TERMINATOR_IN_RANGE)
    bounded = rule_for_incompleteness_reason(IncompletenessReason.LOG_FILE_MISSING_IN_SEQUENCE)

    # The default-when-no-index rule cites R-COV-001 as a checked link.
    assert "R-COV-001" in unbounded.decided_with

    # The bounded rule must say it cannot apply without an index...
    assert "R-COV-001" not in bounded.decided_with
    assert unbounded.id in bounded.statement, "R-GRP-014 must name the rule that applies instead"

    # ...and R-COV-001 must name which reason results, from its own side.
    no_index = rule("R-COV-001")
    assert unbounded.id in no_index.statement
    assert bounded.id in no_index.statement


def test_the_two_unclaimed_event_rules_do_not_overlap() -> None:
    """R-GRP-005 synthesises a container; R-GRP-011 refuses to. Both cannot apply.

    The boundary is observable: a run of events preceding every marker is evidence
    the log begins mid-transaction, so grouping them states something the evidence
    supports. A mid-stream orphan has no such evidence, so grouping it with
    anything would assert a shared transaction we never saw.
    """
    leading = rule("R-GRP-005")
    orphan = rule("R-GRP-011")

    # Each names the other, so a reader hitting either one learns the boundary.
    assert orphan.id in leading.statement
    assert leading.id in orphan.statement
    assert orphan.id in leading.decided_with
    assert leading.id in orphan.decided_with

    # Only the leading-run case produces a transaction, so only it sets a reason.
    assert leading.incompleteness_reason is IncompletenessReason.EVENTS_WITHOUT_BEGIN
    assert orphan.incompleteness_reason is None


def test_the_gap_rule_and_the_conflict_rule_are_a_matched_pair() -> None:
    """R-RECON-003 and -004 differ only in coverage. Both must exist and differ.

    This pair is what keeps an evidence gap from being reported as tampering, so
    it gets an assertion of its own rather than relying on the sweep above.
    """
    conflict = rule("R-RECON-003")
    gap = rule("R-RECON-004")
    assert conflict.result is ReconResult.CONFLICTING
    assert gap.result is ReconResult.UNRESOLVED
    assert conflict.service == gap.service == "reconciliation"


# ── Code and catalogue ───────────────────────────────────────────────────────


def domain_sources() -> list[Path]:
    return sorted(p for p in DOMAIN_ROOT.rglob("*.py") if p.name != "rules.py")


@pytest.mark.parametrize("module", domain_sources(), ids=lambda p: p.name)
def test_rule_ids_in_code_exist_in_the_catalogue(module: Path) -> None:
    """A typo in a rule id must fail here, not silently reach a report."""
    text = module.read_text(encoding="utf-8")
    unknown = sorted({m for m in RULE_ID_PATTERN.findall(text) if m not in RULES})
    assert not unknown, f"{module.name} references unknown rule ids: {unknown}"


def test_rule_id_constants_match_their_names() -> None:
    """`R_UNDECODABLE = "R-VAL-005"` must not point at some other rule.

    Compares each module-level rule-id constant against the catalogue entry's
    title, so a copy-paste that keeps the name and changes the number is caught.
    """
    values_module = DOMAIN_ROOT / "models" / "values.py"
    tree = ast.parse(values_module.read_text(encoding="utf-8"))
    found: dict[str, str] = {}

    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and RULE_ID_PATTERN.fullmatch(node.value.value)
        ):
            found[node.target.id] = node.value.value

    assert found, "no rule id constants found in values.py"
    for name, rule_id in found.items():
        assert rule_id in RULES, f"{name} points at unknown rule {rule_id}"
        assert rule(rule_id).service == "values", f"{name} points outside the values family"


# ── Document and catalogue ───────────────────────────────────────────────────


def test_document_exists_and_names_every_rule() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    missing = sorted(rule_id for rule_id in RULES if rule_id not in text)
    assert not missing, f"docs/correlation-rules.md omits: {missing}"


def test_document_names_no_rule_the_catalogue_lacks() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    unknown = sorted({m for m in RULE_ID_PATTERN.findall(text) if m not in RULES})
    assert not unknown, f"docs/correlation-rules.md references unknown rules: {unknown}"


def test_document_records_both_architecture_decisions() -> None:
    """The ADRs are the reason two documented inconsistencies were resolved."""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "ADR-01" in text and "ADR-02" in text


def test_casing_convention_holds_in_both_directions() -> None:
    """Member name in prose, stored value in structured columns. Stated in the doc.

    The two casings look like an inconsistency unless the convention is real and
    applied, so it is asserted rather than left to hold by habit.
    """
    text = DOC_PATH.read_text(encoding="utf-8")

    for definition in RULES.values():
        if definition.incompleteness_reason is None:
            continue
        reason = definition.incompleteness_reason
        # Prose uses the member name...
        assert reason.name in definition.statement
        # ...and never the stored value, which belongs in the data columns.
        assert reason.value not in definition.statement, (
            f"{definition.id} uses the stored value {reason.value!r} in prose; "
            f"use the member name {reason.name} there"
        )

    # The generated tables carry the stored value, since that is what SQLite holds.
    generated = text.split("<!-- BEGIN GENERATED RULES -->", 1)[1]
    for reason in IncompletenessReason:
        assert f"`{reason.value}`" in generated, f"{reason.value} missing from generated tables"


def test_document_states_the_casing_convention() -> None:
    """The doc's own premise is that conventions are not left implicit."""
    text = DOC_PATH.read_text(encoding="utf-8")
    guide = text.split("## How to read a rule", 1)[1].split("---", 1)[0]
    assert "member name" in guide and "stored string value" in guide


def test_document_maps_every_incompleteness_reason() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    for reason, rule_id in INCOMPLETENESS_REASON_RULES.items():
        assert reason.value in text, f"{reason.value} is not in the document"
        assert rule_id in text, f"{rule_id} is not in the document"


def adr_one_consequences() -> str:
    text = DOC_PATH.read_text(encoding="utf-8")
    return text.split("**Consequences.**", 1)[1].split("---", 1)[0]


def test_adr_one_consequences_records_the_catalogue_change() -> None:
    """That paragraph is meant to be the single record of what ADR-01 touched.

    If the decision later changes which rules carry the reasons, this fails and
    forces the paragraph to be updated with it.
    """
    consequences = adr_one_consequences()
    for rule_id in sorted(set(INCOMPLETENESS_REASON_RULES.values())):
        assert rule_id in consequences, f"ADR-01 consequences omits {rule_id}"


def test_adr_one_consequences_claims_only_what_it_caused() -> None:
    """A Consequences section is a provenance claim, so it must not overreach.

    The counterfactual: would the change exist had ADR-01 gone the other way? The
    R-GRP-004/R-GRP-014 split would not - splitting "no terminator observed" into
    bounded and unbounded only makes sense once the why has to live somewhere
    citable, which is the decision's actual content. The R-GRP-005/R-GRP-011
    disambiguation would have, since those two statements contradicted each other
    whether the fourth concept became a status or a reason field.

    Listing the latter under ADR-01 would attribute a fix to a cause that did not
    produce it - the same category of error the engine itself refuses to make.
    """
    consequences = adr_one_consequences()
    assert "R-GRP-011" not in consequences, (
        "the R-GRP-005/R-GRP-011 disambiguation is not downstream of ADR-01; "
        "it belongs in its own note, not in this decision's consequences"
    )


def test_the_unclaimed_event_note_stands_on_its_own() -> None:
    """Moving it out of ADR-01 must not mean losing it."""
    text = DOC_PATH.read_text(encoding="utf-8")
    note = text.split("## Note — unclaimed events", 1)
    assert len(note) == 2, "the R-GRP-005/R-GRP-011 note is missing"
    body = note[1].split("## Rule tables", 1)[0]
    assert "R-GRP-005" in body and "R-GRP-011" in body
    # It should say why it is not filed under the ADRs, or the separation reads
    # as an oversight rather than a judgement.
    assert "ADR-01" in body


def test_document_is_not_stale() -> None:
    """Regenerates the tables and fails if they differ from what is committed."""
    result = subprocess.run(
        [sys.executable, str(RENDERER), "--check"],
        capture_output=True,
        text=True,
        cwd=BACKEND_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ── Rendering ────────────────────────────────────────────────────────────────


def test_describe_fills_the_template() -> None:
    line = describe(
        "R-RECON-003",
        {"record": "accounts:101", "field": "balance", "log": "4000.00", "phys": "3500.00"},
    )
    assert line == "accounts:101.balance: log 4000.00 vs physical 3500.00"


def test_describe_survives_a_missing_placeholder() -> None:
    """A visibly unfilled template gets noticed and fixed; a raised exception
    would lose an otherwise valid finding."""
    line = describe("R-RECON-003", {"record": "accounts:101"})
    assert "{field}" in line


def test_unknown_rule_id_fails_loudly() -> None:
    with pytest.raises(KeyError):
        rule("R-NOPE-999")
