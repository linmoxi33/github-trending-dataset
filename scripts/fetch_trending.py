"""Fetch GitHub Trending (daily / weekly / monthly) and save a dated snapshot.

Usage:
    python scripts/fetch_trending.py [--date YYYY-MM-DD] [--outdir data]

Exit code 0 on success, 1 when any list comes back empty (so CI fails loudly
instead of committing an empty file).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://github.com/trending"
PERIODS = ("daily", "weekly", "monthly")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

NUM_RE = re.compile(r"([\d,]+)")


def _num(text: str) -> int | None:
    """'1,234' -> 1234; empty/None -> None."""
    if not text:
        return None
    m = NUM_RE.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def _proxies() -> dict | None:
    """Honour HTTPS_PROXY / ALL_PROXY if the caller set one.

    github.com is unreachable on some networks while api.github.com answers
    fine, so local runs often need a proxy that CI does not.
    """
    for var in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(var)
        if value:
            return {"http": value, "https": value}
    return None


def _fetch(url: str, tries: int = 3, wait: int = 5) -> str:
    last: Exception | None = None
    proxies = _proxies()
    for attempt in range(1, tries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30, proxies=proxies)
            if resp.status_code == 200:
                return resp.text
            last = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except Exception as exc:  # noqa: BLE001
            last = exc
        if attempt < tries:
            time.sleep(wait)
    raise RuntimeError(f"failed after {tries} tries: {url}") from last


def parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for box in soup.select("article.Box-row"):
        link = box.select_one("h2 a")
        if link is None:
            continue
        full_name = " ".join(link.get_text(" ", strip=True).split())
        full_name = full_name.replace(" / ", "/").replace(" ", "")
        desc_el = box.select_one("p")
        lang_el = box.select_one('[itemprop="programmingLanguage"]')
        star_link = box.select_one('a[href$="/stargazers"]')
        fork_link = box.select_one('a[href$="/forks"]')

        period_stars = None
        for span in box.select("span.d-inline-block.float-sm-right"):
            txt = span.get_text(" ", strip=True)
            if "star" in txt:
                period_stars = _num(txt)
                break

        built_by = [
            img.get("alt", "").lstrip("@")
            for img in box.select('span.d-inline-block img[alt]')
            if img.get("alt")
        ]

        rows.append(
            {
                "repo": full_name,
                "url": f"https://github.com/{full_name}",
                "description": desc_el.get_text(" ", strip=True) if desc_el else None,
                "language": lang_el.get_text(strip=True) if lang_el else None,
                "stars_total": _num(star_link.get_text(strip=True)) if star_link else None,
                "forks_total": _num(fork_link.get_text(strip=True)) if fork_link else None,
                "stars_period": period_stars,
                "built_by": built_by[:5],
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="override date key (YYYY-MM-DD)")
    ap.add_argument("--outdir", default="data")
    args = ap.parse_args()

    date_key = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "date": date_key,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": BASE,
        "lists": {},
    }

    failed = []
    for period in PERIODS:
        url = f"{BASE}?since={period}"
        try:
            rows = parse(_fetch(url))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {period}: {exc}", file=sys.stderr)
            rows = []
        if not rows:
            failed.append(period)
        payload["lists"][period] = rows
        print(f"[ok] {period}: {len(rows)} repos")

    if failed:
        print(f"[error] empty lists: {', '.join(failed)}", file=sys.stderr)
        return 1

    out = outdir / f"{date_key}.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (outdir / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
