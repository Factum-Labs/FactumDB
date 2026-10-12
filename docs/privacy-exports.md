# Report privacy and local previews

The application offers full case JSON and a grouped investigator summary PDF.
Both default to a **Redacted sharing copy**; investigators may explicitly choose
**Original values (sensitive)**. Report detail and redaction are independent:
original PDF remains a summary and redacted JSON still covers the complete case.

Redaction replaces evidence values and text identifiers with aliases. Personal
metadata, paths, commands and diagnostic text are withheld. Structural counts,
classifications and rule identifiers remain readable. Original case evidence
is untouched. Unknown metadata is not converted into an invented location or
custody event. These copies are pseudonymized, not anonymized, and unsuitable
for independent reanalysis. Use original full JSON to independently check values.

Each JSON preparation uses fresh aliases. PDF summary aliases use stable ordinal
identifiers assigned during canonical traversal, so unchanged inputs reproduce
the same readable layout. Summary template `investigator-summary-3` uses category
labels such as `[TABLE-001]`, `[FIELD-001]`, `[EVIDENCE-001]`, `[SOURCE-001]`
and `[RUN-001]`, with a legend in redacted PDFs. Each category has independent
numbering; identical original text in different categories receives different
aliases. Evidence filenames and finding source filenames share the SOURCE
category so their references connect. These aliases apply only within an export;
they are not a lookup key into another PDF or JSON export. Existing saved PDFs
and JSON alias behavior are unchanged. Aliases can allow linkage and equality comparisons;
they do not guarantee anonymity. Original alias maps reside only in the local
temporary SQLite projection and are dropped with secure_delete before freezing.

PDF summaries use larger body text, aligned evidence metadata, separate record
and field comparison tables, and grouped findings with dividers. Repeated rule
explanations appear once in a Rule guide; each finding retains its rule identifier,
title, counts and source references. Position ranges retain their original meaning.

Preview preparation reports stage progress and supports cancellation. PDF
preview shows the actual locally generated PDF using a bundled offline renderer;
JSON preview shows its manifest and coverage counts. PDF byte requests are
bounded and require the authenticated owner, a valid preview token and unchanged
source data/settings. Only one page canvas is rendered at a time.

Temporary projections, read-only source connections and preview artifacts are
removed on cancellation, replacement, ten-minute expiry, lock/logout or shutdown.
No preview is registered as a completed report. Saving copies the exact prepared
PDF or streams full JSON, checks destination ownership and refuses existing
paths, then records the signed-in actor, hashes and file sizes in history.

Generation timestamps can change between fresh exports; ordering, aggregation,
fonts and template behavior are fixed. Data is never uploaded by the report flow.
CSV generation is removed. Historical CSV entries and files are preserved.
