"""Keeping a read to the evidence of one case.

A case database can hold more than one case. Extracted rows are tied to their
case only through their evidence file, so a read for one case keeps the rows
whose evidence file belongs to it. Without that, a second case in the same
file would leak into the first one's analysis: its rows, its events, and its
version of a table's schema, which would then name the wrong columns.

Reads that are given no case still cover the whole database, as before.
"""


def in_case(case_id, column="evidence_id"):
    """A WHERE condition, and its parameters, that keeps one case's rows."""
    if case_id is None:
        return "1 = 1", ()
    return (
        f"{column} IN (SELECT evidence_id FROM evidence_files WHERE case_id = ?)",
        (case_id,),
    )
