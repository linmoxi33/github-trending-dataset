"""Render the repository's social preview card and README banner.

Deterministic drawing with Pillow - no generative model involved, so text can
never come out garbled.

Usage:
    python scripts/make_cover.py --out assets/cover.png
    python scripts/make_cover.py --title "Awesome Chinese TTS" --subtitle "..." --badge "N entries"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Warm editorial palette
INK = "#2b2119"
PAPER = "#faf6f0"
AMBER = "#c8892b"
TERRACOTTA = "#b4552f"
OLIVE = "#6b6b3a"
MUTED = "#8a7a68"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",     # 微软雅黑 Bold
    r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in (FONT_CANDIDATES if bold else FONT_CANDIDATES[1:]):
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


def render(
    out: Path,
    title: str,
    subtitle: str,
    badge: str,
    size: tuple[int, int] = (1280, 640),
) -> Path:
    w, h = size
    img = Image.new("RGB", size, PAPER)
    d = ImageDraw.Draw(img)

    # warm top band
    d.rectangle([0, 0, w, 14], fill=AMBER)
    d.rectangle([0, h - 14, w, h], fill=TERRACOTTA)

    pad = 84
    f_title = load_font(72, bold=True)
    f_sub = load_font(32)
    f_badge = load_font(26)

    # title
    y = 150
    for line in wrap(d, title, f_title, w - pad * 2)[:2]:
        d.text((pad, y), line, font=f_title, fill=INK)
        y += 88

    # amber rule
    d.rectangle([pad, y + 14, pad + 120, y + 20], fill=AMBER)
    y += 52

    # subtitle
    for line in wrap(d, subtitle, f_sub, w - pad * 2 - 40)[:3]:
        d.text((pad, y), line, font=f_sub, fill=OLIVE)
        y += 44

    # badge pill
    if badge:
        bw = d.textlength(badge, font=f_badge) + 48
        d.rounded_rectangle([pad, h - 132, pad + bw, h - 74], radius=28, fill=INK)
        d.text((pad + 24, h - 118), badge, font=f_badge, fill=PAPER)

    # corner mark
    d.text((w - pad - 8, h - 118), "data • daily", font=f_badge, fill=MUTED, anchor="ra")

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/cover.png")
    ap.add_argument("--title", default="GitHub Trending Dataset")
    ap.add_argument(
        "--subtitle",
        default="Daily snapshots of the GitHub Trending lists — the history page nobody kept.",
    )
    ap.add_argument("--badge", default="updated daily")
    args = ap.parse_args()
    path = render(Path(args.out), args.title, args.subtitle, args.badge)
    print(f"[saved] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
