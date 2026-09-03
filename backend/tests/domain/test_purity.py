"""The domain layer must be pure. Enforced mechanically, not by convention.

Architecture.md's dependency rule says the domain must not depend on React,
Tauri, SQLite, filesystem paths or CLI tools. Reviews catch that for a while and
then stop catching it, so this walks the AST of every domain module instead.

The forbidden list is wider than "infrastructure": `random`, `time` and
`datetime.now` are banned because a forensic conclusion that changes between two
runs over the same evidence is not a conclusion. `uuid` is banned because ids
must be derived from the evidence, not minted - re-running a case has to produce
the same transaction ids.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DOMAIN_ROOT = Path(__file__).resolve().parents[2] / "core" / "domain"

FORBIDDEN_MODULES = {
    "sqlite3",
    "os",
    "os.path",
    "pathlib",
    "shutil",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "random",
    "secrets",
    "uuid",
    "time",
    "logging",
    "tempfile",
    "argparse",
    "pickle",
}

# Attribute chains that read the wall clock. `datetime` itself is fine and
# necessary - it is reading "now" that makes output unrepeatable.
FORBIDDEN_ATTRIBUTES = {
    ("datetime", "now"),
    ("datetime", "today"),
    ("datetime", "utcnow"),
    ("date", "today"),
    ("time", "time"),
}


def domain_modules() -> list[Path]:
    return sorted(p for p in DOMAIN_ROOT.rglob("*.py"))


def test_domain_has_modules() -> None:
    """Guard the guard: an empty glob would make every test below vacuous."""
    assert domain_modules(), f"no domain modules found under {DOMAIN_ROOT}"


@pytest.mark.parametrize("module", domain_modules(), ids=lambda p: p.name)
def test_no_forbidden_imports(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, always in-package
                continue
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_MODULES:
                offenders.append(f"line {node.lineno}: from {node.module} import ...")

    assert not offenders, f"{module.name} imports forbidden modules:\n" + "\n".join(offenders)


@pytest.mark.parametrize("module", domain_modules(), ids=lambda p: p.name)
def test_no_wall_clock_reads(module: Path) -> None:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and (node.value.id, node.attr) in FORBIDDEN_ATTRIBUTES
        ):
            offenders.append(f"line {node.lineno}: {node.value.id}.{node.attr}")

    assert not offenders, f"{module.name} reads the wall clock:\n" + "\n".join(offenders)


@pytest.mark.parametrize("module", domain_modules(), ids=lambda p: p.name)
def test_domain_imports_only_domain(module: Path) -> None:
    """No reaching sideways into application, adapters or interfaces."""
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("core.")
            and not node.module.startswith("core.domain")
        ):
            offenders.append(f"line {node.lineno}: from {node.module} import ...")

    assert not offenders, f"{module.name} imports outside the domain:\n" + "\n".join(offenders)
