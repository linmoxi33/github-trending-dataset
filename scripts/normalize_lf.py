"""Normalise every text file in the repo to LF and report what changed.

Windows editors and the Write tool can leave CRLF behind; a mixed repo makes
`git diff` noisy and breaks patch-based tooling. Run this before committing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yml", ".yaml", ".txt", ".toml", ".cfg",
    ".ini", ".gitignore", ".gitattributes", "",
}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "assets"}


def main() -> int:
    changed = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in (".gitignore", ".gitattributes"):
            continue
        raw = path.read_bytes()
        if b"\r\n" not in raw:
            continue
        path.write_bytes(raw.replace(b"\r\n", b"\n"))
        changed.append(path.relative_to(ROOT).as_posix())

    print(f"[lf] normalised {len(changed)} file(s)")
    for name in changed:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
