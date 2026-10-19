"""Rewrite the README block between the TRENDING markers.

Reads data/latest.json + the newest data/gap/*.json and regenerates the
"Today's movers" and "Coverage gaps" sections. Everything outside the markers
is left untouched, so hand-written prose survives the automation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

START = "<!-- TRENDING:START -->"
END = "<!-- TRENDING:END -->"

PERIOD_LABEL = {"daily": "Today", "weekly": "This week", "monthly": "This month"}


def load_newest_gap(folder: Path) -> dict | None:
    files = sorted(folder.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def fmt(n: int | None) -> str:
    return f"{n:,}" if isinstance(n, int) else "—"


def build_block(snap: dict, gap: dict | None) -> str:
    date = snap.get("date", "")
    lines: list[str] = [START, ""]

    lines.append(f"**Last snapshot:** `{date}` · source: [github.com/trending](https://github.com/trending)")
    lines.append("")

    daily = snap.get("lists", {}).get("daily", [])
    if daily:
        lines.append("### Top 5 · today")
        lines.append("")
        lines.append("| # | Repository | Language | Stars today | Total |")
        lines.append("|---:|---|---|---:|---:|")
        for i, row in enumerate(daily[:5], 1):
            name = row["repo"]
            lines.append(
                f"| {i} | [{name}]({row['url']}) | {row.get('language') or '—'} "
                f"| +{fmt(row.get('stars_period'))} | {fmt(row.get('stars_total'))} |"
            )
        lines.append("")

    if gap:
        candidates = gap.get("candidates", [])[:5]
        if candidates:
            lines.append("### Coverage gaps")
            lines.append("")
            lines.append(
                "Domains trending right now that have **no dedicated awesome-list** in the index. "
                f"Scored out of 100 on crowding / momentum / spread ({len(candidates)} shown)."
            )
            lines.append("")
            lines.append("| Score | Domain | Existing lists | Best existing | Witnesses |")
            lines.append("|---:|---|---:|---:|---|")
            for c in candidates:
                best = f"{c['existing_top_repo']} ({fmt(c['existing_top_stars'])})" if c.get("existing_top_repo") else "—"
                witnesses = ", ".join(f"`{w.split('/')[-1]}`" for w in c.get("witnesses", [])[:2]) or "—"
                lines.append(
                    f"| {c['score']:.1f} | `{c['domain']}` | {c['existing_lists']} | {best} | {witnesses} |"
                )
            lines.append("")

    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readme", default="README.md")
    ap.add_argument("--data", default="data/latest.json")
    ap.add_argument("--gapdir", default="data/gap")
    args = ap.parse_args()

    readme = Path(args.readme)
    snap = json.loads(Path(args.data).read_text(encoding="utf-8"))
    gap = load_newest_gap(Path(args.gapdir))

    block = build_block(snap, gap)
    text = readme.read_text(encoding="utf-8") if readme.exists() else f"# Title\n\n{START}\n{END}\n"

    if START in text and END in text:
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        text = head + block + tail
    else:
        text = text.rstrip() + "\n\n" + block + "\n"

    readme.write_text(text, encoding="utf-8")
    print(f"[readme] refreshed {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
