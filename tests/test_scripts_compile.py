"""Fail fast on syntax errors in any script.

`pytest` only imports the modules it touches; a broken file elsewhere in
`scripts/` still ships. This compiles every script so CI catches it too.

The compile output goes to pytest's own temp directory. An earlier version
wrote `<script>.pyc.tmp` next to the source, which is how seven of those files
ended up committed: every local test run dropped one into `scripts/`.
"""

from __future__ import annotations

import py_compile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "scripts").glob("*.py"))


def test_every_script_compiles(tmp_path: Path):
    assert SCRIPTS, "no scripts found"
    failures = []
    for path in SCRIPTS:
        try:
            py_compile.compile(
                str(path), doraise=True, cfile=str(tmp_path / f"{path.name}.pyc")
            )
        except py_compile.PyCompileError as exc:
            failures.append(f"{path.name}: {exc}")
    assert not failures, "syntax errors:\n" + "\n".join(failures)


def test_scripts_are_unique_and_non_empty():
    names = [p.name for p in SCRIPTS]
    assert len(names) == len(set(names))
    for path in SCRIPTS:
        assert path.stat().st_size > 0, f"{path.name} is empty"


def test_compiling_leaves_no_artifacts_in_scripts():
    """The regression this file was rewritten for.

    A `.pyc.tmp` beside the sources is both noise and a lie: it suggests the
    script directory holds build output. Nothing may be written there.
    """
    stray = sorted(p.name for p in (ROOT / "scripts").glob("*.pyc*"))
    assert not stray, f"build artifacts in scripts/: {stray}"


@pytest.mark.parametrize("name", [p.name for p in SCRIPTS])
def test_script_has_a_docstring(name: str):
    """Each script is a CLI someone has to understand from `--help` alone."""
    source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    assert source.lstrip().startswith(('"""', "'''")), f"{name} has no module docstring"
