"""Render the rule tables in `docs/correlation-rules.md` from `core.domain.rules`.

The document is the reviewable form of the catalogue - it is what a supervisor or
an opposing examiner reads to judge whether our classifications are defensible.
Keeping it hand-written would guarantee it drifts from the code, and a rule
catalogue that does not match the engine is worse than none.

So the tables are generated and the prose is not. Everything between the BEGIN
and END markers is owned by this script; everything outside them - the
introduction and the architecture decisions - is written by hand and preserved.

    py -3.11 tools/render_rules_doc.py --check    # used by the test suite
    py -3.11 tools/render_rules_doc.py --write    # regenerate after editing rules.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.domain.models.transactions import IncompletenessReason
from core.domain.rules import INCOMPLETENESS_REASON_RULES, RULES, SERVICES, rule

BEGIN = "<!-- BEGIN GENERATED RULES -->"
END = "<!-- END GENERATED RULES -->"

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "correlation-rules.md"

SERVICE_TITLES = {
    "values": "Value comparison",
    "provenance": "Provenance",
    "grouping": "Transaction grouping",
    "coverage": "Evidence coverage",
    "correlation": "Record correlation",
    "reconstruction": "State reconstruction",
    "reconciliation": "Reconciliation",
}

SERVICE_INTROS = {
    "values": (
        "Every equality decision in the engine is made in one function, "
        "`core/domain/models/values.py::compare`. These rules are what it can conclude."
    ),
    "provenance": "Rules about our ability to trace a finding back to raw tool output.",
    "grouping": (
        "`TransactionGroupingService`. Transaction markers are the authority - the adapter "
        "parses BEGIN, GTID, XID and ROLLBACK, and the domain never re-parses them."
    ),
    "coverage": (
        "What we can and cannot see. These rules decide whether a difference is reported as a "
        "conflict or as unresolved, which is the most consequential distinction the tool makes."
    ),
    "correlation": (
        "`RecordCorrelationService`. Linking events and physical rows to record identities."
    ),
    "reconstruction": (
        "`StateReconstructionService`. Replaying correlated events into record histories."
    ),
    "reconciliation": (
        "`ReconciliationService`. Comparing reconstructed state against the tablespace, per field "
        "and then rolled up per record."
    ),
}


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_incompleteness_table() -> list[str]:
    """Which rule writes each `incompleteness_reason` value.

    Generated rather than written by hand for the same reason as everything else
    here, and given its own table because the four rules that produce these
    values are not adjacent in id order - a reviewer checking that all four are
    accounted for should not have to hunt through the grouping section.
    """
    lines = [
        "### Transaction incompleteness reasons",
        "",
        "`incomplete` says the terminator was not observed; `incompleteness_reason` says why.",
        "Each value is written by exactly one rule, and no other rule may write it — a test",
        "enforces both halves of that. See ADR-01 for why this is a field rather than a fourth",
        "transaction status.",
        "",
        "| Reason | Written by | Defers to | Rule title |",
        "|---|---|---|---|",
    ]
    for reason in IncompletenessReason:
        rule_id = INCOMPLETENESS_REASON_RULES[reason]
        definition = rule(rule_id)
        defers = ", ".join(f"`{r}`" for r in definition.decided_with) or "—"
        lines.append(
            f"| `{reason.value}` | `{rule_id}` | {defers} | {_escape(definition.title)} |"
        )
    lines.append("")
    return lines


def render() -> str:
    lines: list[str] = [BEGIN, ""]
    lines.extend(render_incompleteness_table())

    for service in SERVICES:
        definitions = [d for d in RULES.values() if d.service == service]
        if not definitions:
            continue

        lines.append(f"### {SERVICE_TITLES[service]}")
        lines.append("")
        intro = SERVICE_INTROS.get(service)
        if intro:
            lines.append(intro)
            lines.append("")
        lines.append("| ID | Title | Statement | Produces | Severity |")
        lines.append("|---|---|---|---|---|")
        for d in definitions:
            produces = "—"
            if d.result is not None:
                produces = d.result.value
            elif d.incompleteness_reason is not None:
                produces = f"`{d.incompleteness_reason.value}`"
            statement = _escape(d.statement)
            if d.decided_with:
                cited = ", ".join(f"`{r}`" for r in d.decided_with)
                statement = f"{statement} **Defers to:** {cited}."
            lines.append(
                f"| `{d.id}` | {_escape(d.title)} | {statement} "
                f"| {produces} | {d.severity.value} |"
            )
        lines.append("")

    lines.append(f"**{len(RULES)} rules total.**")
    lines.append("")
    lines.append(END)
    return "\n".join(lines)


def splice(existing: str, generated: str) -> str:
    start = existing.index(BEGIN)
    end = existing.index(END) + len(END)
    return existing[:start] + generated + existing[end:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the doc is stale")
    parser.add_argument("--write", action="store_true", help="rewrite the generated region")
    args = parser.parse_args()

    existing = DOC_PATH.read_text(encoding="utf-8")
    updated = splice(existing, render())

    if args.write:
        DOC_PATH.write_text(updated, encoding="utf-8", newline="\n")
        print(f"wrote {DOC_PATH}")
        return 0

    if updated != existing:
        print("docs/correlation-rules.md is stale; run tools/render_rules_doc.py --write")
        return 1

    print("docs/correlation-rules.md is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
