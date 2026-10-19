"""Render the repository's social preview card.

Deterministic drawing with Pillow - no generative model involved, so text can
never come out garbled.

The card shows a real terminal session built from `data/latest.json`: the
repositories that appear in more than one of the three windows on the newest
snapshot. Generated from the data rather than hand-written, so it cannot drift
out of date the way a hand-drawn image would.

Usage:
    python scripts/make_cover.py --out assets/cover.png
    python scripts/make_cover.py --data data/latest.json --out assets/cover.png
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Warm editorial palette
INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"

# Terminal-specific: on the dark card, muted text needs to stay legible.
TERM_DIM = "#a3937f"
TERM_BRIGHT = "#f2ebe1"

SANS_BOLD = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
SANS = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
MONO = [
    r"C:\Windows\Fonts\consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
MONO_BOLD = [
    r"C:\Windows\Fonts\consolab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]


def load_font(size: int, family: list[str] | None = None) -> ImageFont.FreeTypeFont:
    for path in family or SANS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Word-aware wrapping.

    Latin text breaks on spaces so words are never split mid-glyph; CJK runs
    break per character because they have no spaces to break on.
    """
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for token in re.findall(r"[A-Za-z0-9\-—–'.,:;()/]+|\s+|.", para):
            trial = cur + token
            if draw.textlength(trial, font=font) <= max_width:
                cur = trial
                continue
            if token.isspace():
                lines.append(cur.rstrip())
                cur = ""
                continue
            if cur.strip():
                lines.append(cur.rstrip())
            cur = "" if token.isspace() else token
            # a single token wider than the box: fall back to per-char split
            while draw.textlength(cur, font=font) > max_width and len(cur) > 1:
                cut = len(cur)
                while cut > 1 and draw.textlength(cur[:cut], font=font) > max_width:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        if cur.strip():
            lines.append(cur.rstrip())
    return lines


# -- data ------------------------------------------------------------------


def crossings(snapshot: dict, min_windows: int = 2) -> list[dict]:
    """Repos present in `min_windows`+ of the three lists, best first.

    Rank is array position, matching what `query.py windows` reports - there is
    no rank field in the snapshot to read.
    """
    presence: dict[str, dict] = {}
    for period in ("daily", "weekly", "monthly"):
        for rank, row in enumerate(snapshot.get("lists", {}).get(period, []), 1):
            name = row.get("repo") or ""
            slot = presence.setdefault(
                name, {"name": name, "ranks": {}, "total": row.get("stars_total")}
            )
            slot["ranks"][period] = rank

    hits = [v for v in presence.values() if len(v["ranks"]) >= min_windows]
    hits.sort(key=lambda v: (-len(v["ranks"]), sorted(v["ranks"].values())))
    return hits


def short(name: str, limit: int) -> str:
    """Truncate a repo name without dropping its owner.

    Taking `owner/repo` down to `repo` changes which project the line refers to
    - two people can both have a `plugins` repo. Shorten from the tail instead,
    and only once the full name genuinely does not fit.
    """
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


# -- render ----------------------------------------------------------------


def render(
    out: Path,
    snapshot: dict,
    title: str,
    subtitle: str,
    badge: str,
    size: tuple[int, int] = (1280, 640),
) -> Path:
    w, h = size
    img = Image.new("RGB", size, PAPER)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, w, 10], fill=AMBER)
    d.rectangle([0, h - 10, w, h], fill=TERRACOTTA)

    # ---- left column: the claim
    pad = 72
    col_w = 470

    f_eyebrow = load_font(17, SANS_BOLD)
    f_title = load_font(58, SANS_BOLD)
    f_sub = load_font(25, SANS)
    f_badge = load_font(21, SANS_BOLD)

    eyebrow = "DATASET  ·  SCRAPER  ·  PYTHON"
    x = pad
    for ch in eyebrow:
        d.text((x, 92), ch, font=f_eyebrow, fill=AMBER)
        x += d.textlength(ch, font=f_eyebrow) + 2.6

    y = 132
    for line in wrap(d, title, f_title, col_w):
        d.text((pad, y), line, font=f_title, fill=INK)
        y += 70

    d.rectangle([pad, y + 16, pad + 104, y + 22], fill=AMBER)
    y += 60

    for line in wrap(d, subtitle, f_sub, col_w):
        d.text((pad, y), line, font=f_sub, fill=OLIVE)
        y += 36

    # Badge sits at a fixed baseline so a longer subtitle cannot push it off.
    bw = d.textlength(badge, font=f_badge) + 44
    d.rounded_rectangle([pad, h - 108, pad + bw, h - 58], radius=25, fill=INK)
    d.text((pad + 22, h - 96), badge, font=f_badge, fill=PAPER)

    # ---- right column: the proof
    tx0, ty0, tx1, ty1 = 588, 76, 1216, 564
    d.rounded_rectangle([tx0, ty0, tx1, ty1], radius=16, fill=INK)

    # window chrome
    for i, colour in enumerate(("#6b5f52", "#6b5f52", "#6b5f52")):
        cx = tx0 + 30 + i * 22
        d.ellipse([cx, ty0 + 22, cx + 10, ty0 + 32], fill=colour)
    f_chrome = load_font(15, MONO)
    d.text((tx1 - 24, ty0 + 20), "query.py", font=f_chrome, fill=TERM_DIM, anchor="ra")
    d.line([tx0, ty0 + 52, tx1, ty0 + 52], fill="#41372c", width=1)

    f_mono = load_font(16, MONO)
    f_mono_b = load_font(16, MONO_BOLD)

    px = tx0 + 28
    py = ty0 + 72
    d.text((px, py), "$ ", font=f_mono_b, fill=AMBER)
    d.text((px + d.textlength("$ ", font=f_mono_b), py),
           "python scripts/query.py windows", font=f_mono, fill=TERM_BRIGHT)

    rows = crossings(snapshot)
    date = snapshot.get("date", "")
    counts = {p: len(snapshot.get("lists", {}).get(p, [])) for p in
              ("daily", "weekly", "monthly")}

    py += 34
    d.text((px, py), f"{date}   daily {counts['daily']}  weekly "
                     f"{counts['weekly']}  monthly {counts['monthly']}",
           font=f_mono, fill=TERM_DIM)

    # column geometry
    c_rank = {"daily": tx1 - 196, "weekly": tx1 - 116, "monthly": tx1 - 36}
    py += 30
    d.text((px, py), "repository", font=f_mono, fill=TERM_DIM)
    for period, cx in c_rank.items():
        d.text((cx, py), period, font=f_mono, fill=TERM_DIM, anchor="ra")
    py += 20
    d.line([px, py, tx1 - 24, py], fill="#41372c", width=1)

    py += 12
    for row in rows:
        text = short(row["name"], 34)
        d.text((px, py), text, font=f_mono, fill=TERM_BRIGHT)
        for period, cx in c_rank.items():
            rank = row["ranks"].get(period)
            if rank is None:
                d.text((cx, py), "·", font=f_mono, fill="#5d5245", anchor="ra")
            else:
                d.text((cx, py), f"#{rank}", font=f_mono_b, fill=AMBER, anchor="ra")
        py += 30

    # Two-window-only repos are the point of the view, not an afterthought:
    # name the tie-break so the reader is not left wondering why these seven.
    py += 6
    d.line([px, py, tx1 - 24, py], fill="#41372c", width=1)
    py += 12
    d.text((px, py), "rank = position in the list that day", font=load_font(14, MONO),
           fill=TERM_DIM)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/cover.png")
    ap.add_argument("--data", default="data/latest.json")
    ap.add_argument("--title", default="GitHub Trending Dataset")
    ap.add_argument(
        "--subtitle",
        default="Every day's three rankings, archived. Now you can ask them questions.",
    )
    ap.add_argument("--badge", default="5 commands · no dependencies")
    args = ap.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"[error] no snapshot at {data_path}", file=sys.stderr)
        return 2
    snapshot = json.loads(data_path.read_text(encoding="utf-8"))

    path = render(Path(args.out), snapshot, args.title, args.subtitle, args.badge)
    print(f"[saved] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
