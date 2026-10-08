"""Reading each tool's version for the tool run record."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from adapters.tools import Ibd2SqlAdapter, InnochecksumAdapter, MysqlBinlogAdapter
from adapters.tools.versions import ToolVersions


def output(stdout=b"", code=0, stderr=b""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


@patch("subprocess.run")
def test_a_mysql_version_is_read_from_its_ver_field(run) -> None:
    run.return_value = output(
        b"innochecksum  Ver 8.4.11-0ubuntu0.26.04.1 for Linux on x86_64 ((Ubuntu))\n"
    )

    assert InnochecksumAdapter().version() == "8.4.11-0ubuntu0.26.04.1"
    run.assert_called_once_with(["innochecksum", "--version"], capture_output=True)


@patch("subprocess.run")
def test_ibd2sql_version_is_kept_as_printed(run) -> None:
    run.return_value = output(b"ibd2sql v2.3-20260526\n")

    version = Ibd2SqlAdapter("/tools/ibd2sql/main.py").version()

    assert version == "ibd2sql v2.3-20260526"
    run.assert_called_once_with(
        ["python3", "/tools/ibd2sql/main.py", "--version"], capture_output=True
    )


@patch("subprocess.run")
def test_a_version_that_cannot_be_read_is_an_error(run) -> None:
    """A tool that fails on --version is not one whose output should be trusted."""
    run.return_value = output(code=1, stderr=b"broken install")

    with pytest.raises(RuntimeError, match="version"):
        MysqlBinlogAdapter("/opt/mysql/bin/mysqlbinlog").version()


def test_versions_are_read_once_and_only_when_first_needed() -> None:
    """Building the application must not launch any tool."""
    reads = []
    versions = ToolVersions({"mysqlbinlog": lambda: reads.append(1) or "8.4.11"})

    assert reads == []
    assert versions.get("mysqlbinlog") == versions.get("mysqlbinlog") == "8.4.11"
    assert reads == [1]
    assert versions.get("ibd2sdi", "unknown") == "unknown"


@patch("subprocess.run", side_effect=FileNotFoundError("[WinError 2]"))
def test_missing_executable_names_tool_and_how_to_fix_it(run) -> None:
    with pytest.raises(RuntimeError, match="innochecksum.*file not found.*Settings"):
        InnochecksumAdapter("C:/missing/innochecksum.exe").version()
