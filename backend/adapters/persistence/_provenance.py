"""Giving each stored row back its provenance when it is read.

Every table that holds extracted data keeps the evidence file and the tool
run each row came from (decision E in docs/sqlite-schema.md). The domain
models carry the same fact as a ProvenanceReference, and the services copy it
into their findings and verdicts. That copy is the only way a finding can
point back to the evidence behind it, so a row read without its reference
gives the analysis findings that cannot be checked.

The reference is rebuilt from the row on every read instead of being stored a
second time, so it can never disagree with the row's own columns.
"""

from core.domain.models.canonical import ProvenanceReference


def provenance_from(row, source_file, log_position=None):
    """The reference for one stored row.

    The row must come with the tool's name from a join on tool_runs. The
    foreign keys mean every row has a tool run, so None here can only come
    from a broken database, and it is passed on rather than guessed at.
    """
    if row["tool_name"] is None or source_file is None:
        return None
    return ProvenanceReference(
        evidence_id=row["evidence_id"],
        tool_name=row["tool_name"],
        tool_run_id=row["tool_run_id"],
        source_file=source_file,
        log_position=log_position,
    )
