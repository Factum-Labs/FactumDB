"""The version of each external tool, for the tool run record.

Every tool run records which version of the tool produced its output. The
version is read from the tool itself rather than written into configuration,
because an ordinary system update can change it without anything in the
project changing - the MySQL utilities on the development machine moved from
8.4.10 to 8.4.11 exactly that way.
"""

import re
import subprocess

# The MySQL utilities print e.g.
#   innochecksum  Ver 8.4.11-0ubuntu0.26.04.1 for Linux on x86_64 ((Ubuntu))
_MYSQL_VERSION = re.compile(r"\bVer\s+(\S+)")


def read_version(command):
    """Ask a tool for its version, for example "8.4.11-0ubuntu0.26.04.1".

    This is not run through the audited runner. Checking a version is not
    something done to the evidence, so it should not be recorded as a run on
    it.

    A version that cannot be read is an error rather than "unknown": a tool
    that fails on --version is not one whose output should be trusted.
    """
    try:
        result = subprocess.run(list(command) + ["--version"], capture_output=True)
    except FileNotFoundError as error:
        raise RuntimeError(
            f"Cannot launch tool executable '{command[0]}': file not found. "
            "Configure its full path in Settings or restore the bundled tools."
        ) from error
    text = result.stdout.decode(errors="replace").strip()
    if result.returncode != 0 or not text:
        raise RuntimeError(
            f"could not read the version of {command[-1]} "
            f"(exit {result.returncode}): {result.stderr.decode(errors='replace')[:200]}"
        )
    match = _MYSQL_VERSION.search(text)
    # Tools that do not use MySQL's format, like ibd2sql, are kept as printed.
    return match.group(1) if match else text.splitlines()[0]


class ToolVersions:
    """Each tool's version, read the first time a run needs it, then kept.

    Reading on first use instead of when the application is built keeps
    building it free of I/O, which the composition relies on.

    get() has the same shape as dict.get, so the audited runner can take
    this anywhere it accepted a plain dictionary of versions.
    """

    def __init__(self, readers):
        # tool name -> a function that reads that tool's version
        self._readers = dict(readers)
        self._known = {}

    def get(self, tool_name, default=None):
        if tool_name not in self._readers:
            return default
        if tool_name not in self._known:
            self._known[tool_name] = self._readers[tool_name]()
        return self._known[tool_name]
