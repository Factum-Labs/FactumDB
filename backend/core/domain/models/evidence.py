"""Models for the evidence itself and for the tools we run against it.

`docs/canonical-model.md` describes what the adapters produce. These two are
about where that output came from: which file was seized, and which command
produced which output. The SQLite schema already had tables for both
(`docs/sqlite-schema.md` sections 2 and 3) but there were no models to go with
them, so the repositories had nothing to take or return.

Both are frozen, like the rest of the models. A record of a seized file or of
a command that has already run should not be editable afterwards.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EvidenceFile:
    """One acquired file, plus how we know it is unaltered.

    Two hashes rather than one: the original is hashed where it was found, the
    working copy is hashed after copying, and the two are compared. All the
    tools run against the working copy, never the original. If the hashes ever
    differ the evidence is not usable and the tool has to say so.

    `acquisition_method` is stored because it is itself forensically
    meaningful. "FLUSH TABLES accounts FOR EXPORT then cp" says the page image
    is internally consistent and was not copied mid-write, which a plain `cp`
    would not.
    """

    evidence_id: str
    case_id: str
    evidence_type: str           # "ibd" | "binlog" | "binlog_index"
    file_name: str
    original_path: str
    size_bytes: int
    sha256_original: str
    working_copy_path: str
    sha256_working: str
    registered_at: str           # ISO-8601 UTC
    acquisition_method: str = ""

    def is_verified(self) -> bool:
        """True when the working copy still matches the original."""
        return self.sha256_original == self.sha256_working


@dataclass(frozen=True)
class ToolRun:
    """One execution of one external tool against one evidence file.

    This is what makes provenance real. Every normalized row we store carries
    a tool_run_id, so any value in a report can be traced back to the exact
    command that produced it, the version of the tool that ran, and a hash of
    the raw output it printed.

    `tool_version` matters because these tools change their output format
    between versions. Three of them have a --version flag. ibd2sql has none at
    all, so for that one we record `git describe --tags` from its clone, which
    names one exact commit instead of a version number.
    """

    tool_run_id: str
    evidence_id: str
    tool_name: str               # ibd2sdi | innochecksum | ibd2sql | mysqlbinlog
    command: str
    started_at: str              # ISO-8601 UTC
    tool_version: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    raw_output_path: Optional[str] = None
    raw_output_sha256: Optional[str] = None

    def succeeded(self) -> bool:
        return self.exit_code == 0
