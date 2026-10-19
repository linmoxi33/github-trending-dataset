"""Fail fast on syntax errors in any script.

`pytest` only imports the modules it touches; a broken file elsewhere in
`scripts/` still ships. This compiles every script so CI catches it too.
"""

from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "scripts").glob("*.py"))


def test_every_script_compiles():
    assert SCRIPTS, "no scripts found"
    failures = []
    for path in SCRIPTS:
        try:
            py_compile.compile(str(path), doraise=True, cfile=str(path) + ".pyc.tmp")
        except py_compile.PyCompileError as exc:
            failures.append(f"{path.name}: {exc}")
    assert not failures, "syntax errors:\n" + "\n".join(failures)


def test_scripts_are_unique_and_non_empty():
    names = [p.name for p in SCRIPTS]
    assert len(names) == len(set(names))
    for path in SCRIPTS:
        assert path.stat().st_size > 0, f"{path.name} is empty"
