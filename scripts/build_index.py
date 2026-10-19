"""Build data/awesome_index.json from GitHub search.

Two queries are merged because either one alone leaves holes:

    A. topic:awesome-list stars:>=100   – repos that opted into the topic
    B. awesome in:name   stars:>=1000   – repos named awesome-* that never
                                          added the topic (e.g.
                                          punkpeye/awesome-mcp-servers only
                                          carries `ai` + `mcp`)

GitHub caps each search at 1000 results, so every query is sliced by star
range until the whole band is covered.

Usage:
    python scripts/build_index.py [--min-stars 100]

Requires GH_TOKEN (or GITHUB_TOKEN) in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://api.github.com/search/repositories"
PER_PAGE = 100
MAX_PAGES = 10  # GitHub refuses page > 10 for search


def norm_domain(name: str) -> str:
    base = name.split("/")[-1].lower()
    base = re.sub(r"^awesome[-_]", "", base)
    base = re.sub(r"[-_](awesome|list|lists|resources?|collection)$", "", base)
    return base


def search(session: requests.Session, query: str, page: int, tries: int = 4) -> dict:
    """Search with retries: transient SSL/connection drops are common."""
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            resp = session.get(
                API,
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": PER_PAGE,
                    "page": page,
                },
                timeout=40,
            )
            if resp.status_code == 403:
                raise RuntimeError("rate limited: " + resp.text[:160])
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < tries:
                wait = 3 * attempt
                print(f"  [retry {attempt}/{tries - 1}] {type(exc).__name__}, waiting {wait}s")
                time.sleep(wait)
    raise RuntimeError(f"search failed after {tries} tries: {query}") from last


def collect(session: requests.Session, base_query: str, floor: int,
            known: dict[str, dict] | None = None,
            refresh_days: int = 0) -> list[dict]:
    """Walk descending star bands so the 1000-result cap never truncates.

    When `known` holds the previous index and `refresh_days` > 0, repositories
    whose last push is older than the window are reused from the index instead
    of being fetched again. That keeps the nightly run to a couple of pages
    instead of a dozen.
    """
    out: dict[str, dict] = {}
    reused = 0
    cutoff = None
    if refresh_days > 0:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=refresh_days)
        ).strftime("%Y-%m-%d")

    hi = None
    guard = 0
    incremental = bool(cutoff) and bool(known)
    while guard < 40:
        guard += 1
        if hi is None:
            q = f"{base_query} stars:>={floor}"
        else:
            q = f"{base_query} stars:{floor}..{hi}"
        if incremental:
            # Let GitHub filter stale entries server-side: one request instead
            # of a dozen page fetches.
            q += f" pushed:>={cutoff}"
        first = search(session, q, 1)
        total = first.get("total_count", 0)
        if total == 0:
            break
        page = 1
        items = first.get("items", [])
        while True:
            for repo in items:
                name = repo["full_name"]
                out[name] = repo
            if len(items) < PER_PAGE or page >= MAX_PAGES or page * PER_PAGE >= total:
                break
            page += 1
            time.sleep(2.2)
            items = search(session, q, page).get("items", [])
        lowest = min((r["stargazers_count"] for r in items), default=None)
        print(f"  [{base_query}] {q[:78]} -> {total} total, fetched {len(out)} unique")
        if total < 1000 or lowest is None or lowest <= floor:
            break
        hi = lowest - 1
        if hi < floor:
            break
        time.sleep(2.2)
    if reused:
        print(f"  [{base_query}] reused {reused} unchanged entr(ies) from the index")
    return list(out.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-stars", type=int, default=100)
    ap.add_argument("--out", default="data/awesome_index.json")
    ap.add_argument(
        "--refresh-days",
        type=int,
        default=0,
        help="Reuse index entries not pushed in the last N days (0 = full crawl)",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="Force a full crawl even if --refresh-days is set",
    )
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("[error] set GH_TOKEN first", file=sys.stderr)
        return 2

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "awesome-gap-indexer",
        }
    )

    known: dict[str, dict] = {}
    out_path = Path(args.out)
    if args.refresh_days > 0 and not args.full and out_path.exists():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            for key, meta in prev.get("domains", {}).items():
                repo = meta.get("repo")
                if repo:
                    known[repo] = meta
            print(f"[incremental] loaded {len(known)} known repos from {out_path}")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] could not read previous index: {exc}", file=sys.stderr)

    repos: dict[str, dict] = {}
    for base_query in ("topic:awesome-list", "awesome in:name"):
        found = collect(
            session,
            base_query,
            args.min_stars,
            known=known,
            refresh_days=0 if args.full else args.refresh_days,
        )
        for repo in found:
            key = repo["full_name"]
            if key not in repos or repo["stargazers_count"] > repos[key]["stargazers_count"]:
                repos[key] = repo

    if known and not args.full:
        # Carry over everything the incremental crawl did not touch.
        carried = 0
        for name, meta in known.items():
            if name in repos:
                continue
            repos[name] = {
                "full_name": name,
                "stargazers_count": meta.get("stars", 0),
                "pushed_at": meta.get("pushed_at", ""),
                "topics": meta.get("topics", []),
                "description": meta.get("description", ""),
            }
            carried += 1
        print(f"[incremental] carried over {carried} unchanged repos")

    domains: dict[str, dict] = {}
    for repo in repos.values():
        key = norm_domain(repo["full_name"])
        cur = domains.get(key)
        if cur is None or repo["stargazers_count"] > cur["stars"]:
            domains[key] = {
                "repo": repo["full_name"],
                "stars": repo["stargazers_count"],
                "pushed_at": repo["pushed_at"][:10],
                "topics": repo.get("topics", []),
                "description": (repo.get("description") or "")[:160],
            }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_stars": args.min_stars,
        "refresh_days": 0 if args.full else args.refresh_days,
        "repos_seen": len(repos),
        "domains": dict(sorted(domains.items(), key=lambda kv: -kv[1]["stars"])),
    }
    out = out_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[saved] {out}  repos={len(repos)}  domains={len(domains)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
