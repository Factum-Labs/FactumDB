"""innochecksum: telling a damaged file apart from one that was never checked.

The tool exits with 1 in both cases, so the exit code alone cannot be trusted.
"""

from __future__ import annotations

import subprocess

import pytest

from adapters.tools import InnochecksumAdapter

IBD = "/cases/case-1/working/accounts.ibd"


def output(stdout=b"", code=0, stderr=b""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def tool(*outputs):
    """Stands in for subprocess.run, answering each call in turn."""
    queue = list(outputs)
    return lambda command, capture_output=True: queue.pop(0)


def test_a_failed_page_is_reported_as_damage() -> None:
    fail = b"Fail: page 4 invalid\nExceeded the maximum allowed checksum mismatch count::0\n"

    result = InnochecksumAdapter().validate(
        IBD, run=tool(output(code=1, stderr=fail), output(code=1, stderr=fail))
    )

    assert (result.status, result.damaged_pages) == ("damaged", 1)


@pytest.mark.parametrize(
    "message",
    [
        b"Error: accounts.ibd cannot be found\n",
        b"Error: Was not able to read the minimum page size of 1024 bytes."
        b"  Bytes read was 22\n",
        b"Error: Unable to lock file:: accounts.ibd\nfcntl: Bad file descriptor\n",
    ],
)
def test_a_file_that_was_never_checked_is_not_called_damaged(message) -> None:
    """These are innochecksum's real messages for a missing file, a file too
    small to be a tablespace, and a file it could not lock. Each used to be
    reported as a damaged tablespace with one bad page."""
    with pytest.raises(RuntimeError, match="could not check"):
        InnochecksumAdapter().validate(
            IBD, run=tool(output(code=1, stderr=message), output(code=1, stderr=message))
        )
