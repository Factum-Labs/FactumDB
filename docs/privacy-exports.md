# Errors and sharing exports

New pipeline failures and sidecar errors contain controlled, bounded summaries
instead of raw exception text or tool stderr. No additional diagnostic log or
third-party service is created. Previously saved errors and raw tool outputs
remain sensitive case material; this change does not erase them.

The Report screen defaults to **Redacted sharing copy** for JSON and CSV.
The desktop API likewise defaults to `redacted: true`; passing `false` explicitly
requests the full case export. Standalone Python export functions preserve their
existing full-export default and accept `redacted=True` for sharing copies.

Redacted copies replace evidence values, column labels, text identifiers,
timestamps and hashes with aliases, and remove personal metadata, paths,
commands and diagnostic context. Counts, structural positions and supported
finding classifications/rule IDs remain. NULL and unobserved values remain
distinguishable. Redacted data is not suitable for rerunning the analysis.

Aliases are consistent within one export, with a fresh random prefix for each
export. Legacy exports hold the mapping in memory. Version-3 exports use a
temporary local SQLite mapping to bound memory use; secure deletion removes
the mapping when preparation completes. It is never included in the report.
Redaction runs locally using Python's standard library and changes only the
generated copy. Report history records generated file hashes locally.

Every desktop JSON, CSV and PDF export also records the backend-authenticated
account ID and username in local report history. Historical exports retain unknown
attribution. The Report screen displays the actor, format, version and timestamp.
Report history is available only to the case owner and is excluded from generated
case exports. Raw tool output remains in separate, hash-verified case files with
owner-only application access; it is not embedded in ordinary audit metadata.

This is pseudonymization, not guaranteed anonymity: counts and structural
relationships can still identify a case to someone with outside knowledge.
Full exports and workspace backups contain sensitive original material.

## Selecting and previewing reports

The Report screen offers PDF, JSON and CSV, with section checkboxes for case
details, evidence inventory, hashes, tools, integrity, schemas, timeline,
histories, reconciliation, gaps, provenance and examiner notes. Unselected
sections and their optional metadata are excluded from the generated copy.
Partial exports are explicitly marked as partial. Report detail and redaction
are separate controls: **Investigator report** is the default; **Full evidence
export** includes every unique observation and analysis result. Both deduplicate
copies through references. Redacted copies are unsuitable for independent
reanalysis.

The investigator default keeps all non-Exact comparisons, classification totals,
warnings and limitations. Exact comparisons and unrelated successful activity
are summarized. Optional supporting-data checkboxes add Exact details, all
physical rows, all binlog events, complete timelines, histories, schemas and
intermediate analysis. Overlapping additions share canonical objects. Required
evidence, tools, hashes, schemas and limitations are included automatically when
needed to interpret selected data; preview lists these dependencies explicitly.

Select **Preview export** to review the selected content after redaction.
The preview is paginated and writes no report file or report-history entry.
The prepared copy and preview lines use a temporary local SQLite database,
expire after ten minutes, and use the same aliases when exported. The temporary
directory is removed on expiry, replacement, successful export, logout, lock or
shutdown. Changing options invalidates the UI preview; changes
to case data, profile, preferences or signed-in identity invalidate it at the
backend. A fresh preview is required before the UI can export. Prepared JSON
size and included/summarized/excluded counts are shown. Page navigation reuses
stored lines and never reloads the full case.

PDF generation uses bundled fpdf2, its dependencies and open-licensed Noto fonts,
including Sinhala and Tamil. No browser, external utility or network service is
invoked at runtime. The preview displays the same text pages as the PDF.
Characters missing from the bundled fonts use Unicode escapes so no characters
are silently lost. Build scripts download pinned wheels during packaging;
Linux bundles must be built with the deployment Python minor version.
JSON and CSV keep their structured formats; their readable preview shows the
selected report content. No HTML format or Presidio dependency was added.
