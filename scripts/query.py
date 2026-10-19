"""Query the archive: turn the dated snapshots into answers.

Every other script writes data. Until now nothing read it back — `find_gaps.py`
and `render_readme.py` both look only at `data/latest.json`, so a snapshot
older than yesterday was unreachable in code. That is the half the README
promised ("what was trending the week that project launched?") and never
shipped.

Sub-commands
    stats                     what the archive covers, and what it is missing
    top                       one day's ranking, by rank or by total stars
    timeline REPO             every day a repository appeared, with day-over-day deltas
    diff FROM TO              who entered, who left, who moved
    windows [DATE]            the three windows side by side, and who appears in more than one

Standard library only, so it runs against a checkout without `pip install`.

Usage:
    python scripts/query.py stats
    python scripts/query.py top --date 2026-10-19 --limit 5
    python scripts/query.py timeline anomalyco/opencode
    python scripts/query.py diff 2026-10-18 2026-10-19 --period daily
    python scripts/query.py windows 2026-10-19
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

PERIODS = ("daily", "weekly", "monthly")
PERIOD_WEIGHT = {"daily": 3.0, "weekly": 1.5, "monthly": 1.0}


def unicode_ok(stream: object | None = None) -> bool:
    """Can the target console print `Δ` and `−`?

    A Chinese Windows console defaults to GBK, where those characters raise
    `UnicodeEncodeError` — not a mojibake box, an actual crash. Probe the
    encoding of the stream that will be written to.
    """
    target = stream if stream is not None else sys.stdout
    encoding = getattr(target, "encoding", None) or "ascii"
    try:
        "Δ−·▲▼".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def glyphs(stream: object | None = None) -> dict[str, str]:
    """Labels for the current console.

    A function rather than module constants: constants freeze whatever the
    encoding was at import time, so redirecting stdout to a GBK pipe would still
    print the unicode labels and crash.
    """
    if unicode_ok(stream):
        return {"d_rank": "Δrank", "d_total": "Δtotal", "dot": "·", "up": "▲", "down": "▼"}
    return {"d_rank": "d-rank", "d_total": "d-total", "dot": "-", "up": "+", "down": "-"}

# A snapshot file is named exactly `YYYY-MM-DD.json`. This regex is deliberately
# not `glob("*.json")`: that also picks up `latest.json` and `awesome_index.json`,
# and `sorted()` puts `latest` *after* every date — so the "newest snapshot"
# would silently become a non-snapshot file. Anchor on the name instead.
SNAPSHOT_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.json$")


class Archive:
    """Lazy, validated view over a snapshot directory."""

    def __init__(self, datadir: Path) -> None:
        self.datadir = Path(datadir)
        self.paths: dict[date, Path] = {}
        self.problems: list[str] = []
        self._cache: dict[date, dict] = {}
        self._scan()

    # -- discovery ---------------------------------------------------------

    def _scan(self) -> None:
        if not self.datadir.is_dir():
            raise SystemExit(f"[error] not a directory: {self.datadir}")
        for path in sorted(self.datadir.iterdir()):
            match = SNAPSHOT_NAME.match(path.name)
            if match is None or not path.is_file():
                continue
            try:
                day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                # `2026-13-01.json` looks like a date but is not one. Report it
                # rather than crashing on someone's stray file.
                self.problems.append(f"ignored {path.name}: not a real calendar date")
                continue
            self.paths[day] = path
        if not self.paths:
            raise SystemExit(f"[error] no YYYY-MM-DD.json snapshots in {self.datadir}")

    @property
    def dates(self) -> list[date]:
        return sorted(self.paths)

    # -- loading -----------------------------------------------------------

    def snapshot(self, day: date) -> dict | None:
        """Parsed snapshot, or None when the file is unreadable.

        A corrupt file must not take down a query about the other 300 days, so
        the failure is collected into `problems` and the caller skips the day.
        """
        if day in self._cache:
            return self._cache[day]
        try:
            payload = json.loads(self.paths[day].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self.problems.append(f"skipped {self.paths[day].name}: {exc}")
            return None
        if not isinstance(payload.get("lists"), dict):
            self.problems.append(f"skipped {self.paths[day].name}: no 'lists' object")
            return None
        self._cache[day] = payload
        return payload

    def rows(self, day: date, period: str = "daily") -> list[dict]:
        payload = self.snapshot(day)
        return [] if payload is None else payload["lists"].get(period, [])

    def find(self, day: date, repo: str, period: str = "daily") -> tuple[int, dict] | None:
        """(rank, row) for `repo` on `day`, case-insensitively; None if absent.

        Rank is the position in the array — GitHub hands back the list already
        ordered, and `fetch_trending.py` preserves that order. Nothing stores a
        rank field, so deriving it here is the only source of truth.
        """
        wanted = repo.lower()
        for rank, row in enumerate(self.rows(day, period), 1):
            if (row.get("repo") or "").lower() == wanted:
                return rank, row
        return None

    # -- coverage ----------------------------------------------------------

    def missing_days(self) -> list[date]:
        """Calendar days absent between the first and last snapshot."""
        seen = set(self.paths)
        first, last = self.dates[0], self.dates[-1]
        out, cursor = [], first + timedelta(days=1)
        while cursor < last:
            if cursor not in seen:
                out.append(cursor)
            cursor += timedelta(days=1)
        return out


# -- formatting ------------------------------------------------------------


def fmt_int(value: object) -> str:
    return f"{value:,}" if isinstance(value, int) else "-"


def fmt_signed(value: object) -> str:
    if not isinstance(value, int):
        return "-"
    return f"+{value:,}" if value >= 0 else f"{value:,}"


def emit(payload: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def die(message: str, code: int = 2) -> int:
    print(message, file=sys.stderr)
    return code


# -- stats -----------------------------------------------------------------


def cmd_stats(archive: Archive, args: argparse.Namespace) -> int:
    days = archive.dates
    missing = archive.missing_days()

    per_period: dict[str, list[int]] = {p: [] for p in PERIODS}
    distinct: set[str] = set()
    entries = 0
    for day in days:
        payload = archive.snapshot(day)
        if payload is None:
            continue
        for period in PERIODS:
            rows = payload["lists"].get(period, [])
            per_period[period].append(len(rows))
            entries += len(rows)
            distinct.update((r.get("repo") or "").lower() for r in rows)

    integrity = _check_latest(archive)

    if args.json:
        emit(
            {
                "datadir": str(archive.datadir),
                "snapshots": len(days),
                "first": days[0].isoformat(),
                "last": days[-1].isoformat(),
                "span_days": (days[-1] - days[0]).days + 1,
                "missing_days": [d.isoformat() for d in missing],
                "rows_per_period": {p: v for p, v in per_period.items()},
                "entries": entries,
                "distinct_repos": len(distinct),
                "latest_json": integrity,
                "problems": archive.problems,
            },
            True,
        )
        return 0

    print(f"Archive      {archive.datadir}")
    print(f"Snapshots    {len(days)}")
    print(f"Range        {days[0]} .. {days[-1]}  ({(days[-1] - days[0]).days + 1} day span)")
    if missing:
        shown = ", ".join(d.isoformat() for d in missing[:8])
        more = f" ... +{len(missing) - 8}" if len(missing) > 8 else ""
        print(f"Missing      {len(missing)} day(s): {shown}{more}")
    else:
        print("Missing      none")
    for period in PERIODS:
        counts = per_period[period] or [0]
        print(
            f"  {period:<8} {min(counts)}..{max(counts)} rows/day"
            f"  ({sum(counts)} entries over {len(counts)} day(s))"
        )
    print(f"Coverage     {entries} snapshot entries, {len(distinct)} distinct repositories")
    print(f"latest.json  {integrity}")
    for problem in archive.problems:
        print(f"[warn] {problem}")
    return 0


def _check_latest(archive: Archive) -> str:
    """Compare the `latest.json` convenience copy with the newest dated file.

    Both are written from the same payload, so any difference means a run was
    interrupted between the two writes — worth surfacing before someone trusts
    the copy.
    """
    latest = archive.datadir / "latest.json"
    if not latest.exists():
        return "absent"
    try:
        copy = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return f"unreadable ({exc})"

    newest = archive.dates[-1]
    original = archive.snapshot(newest)
    if original is None:
        return "newest snapshot unreadable"

    if copy.get("date") != original.get("date"):
        return f"MISMATCH: copy says {copy.get('date')}, newest file is {newest}"

    for period in PERIODS:
        left = [r.get("repo") for r in copy.get("lists", {}).get(period, [])]
        right = [r.get("repo") for r in original["lists"].get(period, [])]
        if left != right:
            return f"MISMATCH: {period} list differs from {newest}"

    return f"matches {newest}"


# -- top -------------------------------------------------------------------


def cmd_top(archive: Archive, args: argparse.Namespace) -> int:
    g = glyphs()
    day = _resolve_date(archive, args.date)
    rows = archive.rows(day, args.period)
    if not rows:
        return die(f"[error] no {args.period} rows in {day}")

    indexed = list(enumerate(rows, 1))
    if args.sort == "total":
        indexed.sort(key=lambda pair: -(pair[1].get("stars_total") or 0))

    picked = indexed[: args.limit]

    if args.json:
        emit(
            {
                "date": day.isoformat(),
                "period": args.period,
                "sort": args.sort,
                "rows": [
                    {
                        "rank": rank,
                        "repo": row.get("repo"),
                        "language": row.get("language"),
                        "stars_period": row.get("stars_period"),
                        "stars_total": row.get("stars_total"),
                        "forks_total": row.get("forks_total"),
                    }
                    for rank, row in picked
                ],
            },
            True,
        )
        return 0

    print(
        f"{day} {g['dot']} {args.period} {g['dot']} top {len(picked)} of {len(rows)}"
        f" {g['dot']} sorted by {args.sort}"
    )
    print(f"{'#':>3}  {'Repository':<44}{'Language':<14}{'Period':>9}{'Total':>10}")
    print("-" * 80)
    for rank, row in picked:
        print(
            f"{rank:>3}  {(row.get('repo') or '?'):<44}"
            f"{(row.get('language') or '-')[:13]:<14}"
            f"{fmt_signed(row.get('stars_period')):>9}"
            f"{fmt_int(row.get('stars_total')):>10}"
        )
    return 0


def _resolve_date(archive: Archive, wanted: str | None) -> date:
    if not wanted:
        return archive.dates[-1]
    try:
        day = date.fromisoformat(wanted)
    except ValueError:
        raise SystemExit(f"[error] not a date: {wanted}") from None
    if day not in archive.paths:
        near = _nearest(archive, day)
        hint = f" nearest snapshot is {near}" if near else ""
        raise SystemExit(f"[error] no snapshot for {day};{hint}")
    return day


def _nearest(archive: Archive, day: date) -> str | None:
    closest = min(archive.dates, key=lambda d: abs((d - day).days))
    return closest.isoformat()


# -- timeline --------------------------------------------------------------


def cmd_timeline(archive: Archive, args: argparse.Namespace) -> int:
    g = glyphs()
    periods = (args.period,) if args.period else PERIODS
    wanted = args.repo.lower()

    blocks: dict[str, list[dict]] = {}
    for period in periods:
        hits = []
        for day in archive.dates:
            found = archive.find(day, wanted, period)
            if found is None:
                continue
            rank, row = found
            hits.append(
                {
                    "date": day,
                    "rank": rank,
                    "stars_period": row.get("stars_period"),
                    "stars_total": row.get("stars_total"),
                    "forks_total": row.get("forks_total"),
                    "language": row.get("language"),
                }
            )
        if hits:
            blocks[period] = hits

    if not blocks:
        return die(f"[error] {args.repo} does not appear in any snapshot ({', '.join(periods)})")

    if args.json:
        emit({"repo": args.repo, "periods": {p: [_jsonable(h) for h in v] for p, v in blocks.items()}}, True)
        return 0

    print(args.repo)
    for period, hits in blocks.items():
        print(f"\n  {period}: {len(hits)} appearance(s)")
        print(
            f"    {'Date':<12}{'Rank':>5}{g['d_rank']:>7}"
            f"{'Period stars':>14}{'Total':>11}{g['d_total']:>10}  Note"
        )
        previous: dict | None = None
        for hit in hits:
            span = (hit["date"] - previous["date"]).days if previous else None
            d_rank = previous["rank"] - hit["rank"] if previous else None
            d_total = _delta(hit["stars_total"], previous["stars_total"] if previous else None)

            notes = []
            if previous is None:
                notes.append("first appearance")
            elif span and span > 1:
                # Adjacent-in-archive is not adjacent-in-calendar: the totals
                # straddle days this archive never captured. Say so instead of
                # letting the delta look like one day's growth.
                gaps = _missing_between(archive, previous["date"], hit["date"])
                notes.append(f"total delta spans {span}d, {gaps} missing")
            if period == "daily" and span == 1:
                drift = _drift(hit, previous)
                if drift is not None:
                    notes.append(f"drift {fmt_signed(drift)}")

            print(
                f"    {hit['date'].isoformat():<12}{hit['rank']:>5}"
                f"{fmt_signed(d_rank):>7}"
                f"{fmt_signed(hit['stars_period']):>14}"
                f"{fmt_int(hit['stars_total']):>11}"
                f"{fmt_signed(d_total):>10}  {'; '.join(notes) or ''}"
            )
            previous = hit

    print(
        "\n  drift = (change in stars_total between consecutive days)"
        " minus (stars reported for the period)."
    )
    print("  A large drift means GitHub's period figure and the running total disagree.")
    return 0


def _delta(now: object, before: object) -> int | None:
    if isinstance(now, int) and isinstance(before, int):
        return now - before
    return None


def _missing_between(archive: Archive, start: date, end: date) -> int:
    """How many calendar days between two snapshots were never captured."""
    seen = set(archive.paths)
    return sum(
        1 for offset in range(1, (end - start).days) if start + timedelta(days=offset) not in seen
    )


def _drift(current: dict, previous: dict) -> int | None:
    d_total = _delta(current["stars_total"], previous["stars_total"])
    period = current["stars_period"]
    if d_total is None or not isinstance(period, int):
        return None
    return d_total - period


def _jsonable(record: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in record.items()}


# -- diff ------------------------------------------------------------------


def cmd_diff(archive: Archive, args: argparse.Namespace) -> int:
    g = glyphs()
    old = _resolve_date(archive, args.from_date)
    new = _resolve_date(archive, args.to_date)
    if old == new:
        return die("[error] --from and --to are the same snapshot")

    before = {(r.get("repo") or "").lower(): (i, r) for i, r in enumerate(archive.rows(old, args.period), 1)}
    after = {(r.get("repo") or "").lower(): (i, r) for i, r in enumerate(archive.rows(new, args.period), 1)}

    entered = [after[k] for k in after.keys() - before.keys()]
    left = [before[k] for k in before.keys() - after.keys()]
    entered.sort(key=lambda pair: pair[0])
    left.sort(key=lambda pair: pair[0])

    movers = []
    for key in after.keys() & before.keys():
        new_rank, row = after[key]
        old_rank = before[key][0]
        if new_rank != old_rank:
            movers.append({"repo": row.get("repo"), "from": old_rank, "to": new_rank,
                           "delta": old_rank - new_rank})
    movers.sort(key=lambda m: -m["delta"])

    span = (new - old).days
    if args.json:
        emit(
            {
                "period": args.period,
                "from": old.isoformat(),
                "to": new.isoformat(),
                "span_days": span,
                "contiguous": span == 1,
                "entered": [{"rank": r, "repo": row.get("repo")} for r, row in entered],
                "left": [{"rank": r, "repo": row.get("repo")} for r, row in left],
                "movers": movers,
            },
            True,
        )
        return 0

    note = "" if span == 1 else f"  ({span} days apart - not consecutive)"
    print(f"{args.period}: {old} -> {new}{note}")

    print(f"\n  entered ({len(entered)})")
    for rank, row in entered[: args.limit]:
        print(f"    #{rank:<4}{row.get('repo')}  {fmt_signed(row.get('stars_period'))}")
    if not entered:
        print("    -")

    print(f"\n  left ({len(left)})")
    for rank, row in left[: args.limit]:
        print(f"    was #{rank:<4}{row.get('repo')}")
    if not left:
        print("    -")

    print(f"\n  rank movers ({len(movers)})")
    for mover in movers[: args.limit]:
        if mover["delta"] > 0:
            print(
                f"    {g['up']}{mover['delta']:<4}{mover['repo']:<46}"
                f"#{mover['from']} -> #{mover['to']}"
            )
        else:
            print(
                f"    {g['down']}{-mover['delta']:<4}{mover['repo']:<46}"
                f"#{mover['from']} -> #{mover['to']}"
            )
    if not movers:
        print("    -")
    return 0


# -- windows ---------------------------------------------------------------


def cmd_windows(archive: Archive, args: argparse.Namespace) -> int:
    g = glyphs()
    day = _resolve_date(archive, args.date)
    lists = {period: archive.rows(day, period) for period in PERIODS}

    presence: dict[str, dict] = {}
    for period, rows in lists.items():
        for rank, row in enumerate(rows, 1):
            key = (row.get("repo") or "").lower()
            slot = presence.setdefault(key, {"repo": row.get("repo"), "ranks": {},
                                             "stars_total": row.get("stars_total")})
            slot["ranks"][period] = rank

    crossing = {k: v for k, v in presence.items() if len(v["ranks"]) >= args.min_windows}
    ordered = sorted(crossing.values(), key=lambda v: (-len(v["ranks"]), sorted(v["ranks"].values())))

    if args.json:
        emit(
            {
                "date": day.isoformat(),
                "counts": {p: len(r) for p, r in lists.items()},
                "crossing": [
                    {"repo": v["repo"], "windows": sorted(v["ranks"]), "ranks": v["ranks"],
                     "stars_total": v["stars_total"]}
                    for v in ordered
                ],
            },
            True,
        )
        return 0

    print(f"{day} {g['dot']} " + f" {g['dot']} ".join(f"{p} {len(lists[p])}" for p in PERIODS))
    if not ordered:
        print(f"\n  No repository appears in {args.min_windows}+ windows on this day.")
        return 0

    print(f"\n  In {args.min_windows}+ windows ({len(ordered)})")
    print(f"    {'Repository':<46}{'daily':>7}{'weekly':>8}{'monthly':>9}{'Total':>11}")
    print("    " + "-" * 78)
    for v in ordered:
        cells = [f"#{v['ranks'][p]}" if p in v["ranks"] else g['dot'] for p in PERIODS]
        print(
            f"    {(v['repo'] or '?')[:45]:<46}"
            f"{cells[0]:>7}{cells[1]:>8}{cells[2]:>9}{fmt_int(v['stars_total']):>11}"
        )
    print("\n  A repository in daily *and* monthly is a long-run project spiking now.")
    print("  One in daily only is a single-day event, worth checking before you chase it.")
    return 0


# -- cli -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="query.py",
        description="Read the archived GitHub Trending snapshots.",
    )
    ap.add_argument("--data", default="data", help="snapshot directory (default: data)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    sub = ap.add_subparsers(dest="command", required=True)

    p_stats = sub.add_parser("stats", help="archive coverage and integrity")
    p_stats.set_defaults(func=cmd_stats)

    p_top = sub.add_parser("top", help="one day's ranking")
    p_top.add_argument("--date", default=None, help="snapshot date (default: newest)")
    p_top.add_argument("--period", default="daily", choices=PERIODS)
    p_top.add_argument("--limit", type=int, default=10)
    p_top.add_argument("--sort", default="rank", choices=("rank", "total"))
    p_top.set_defaults(func=cmd_top)

    p_time = sub.add_parser("timeline", help="every appearance of one repository")
    p_time.add_argument("repo", help="owner/name")
    p_time.add_argument("--period", default=None, choices=PERIODS)
    p_time.set_defaults(func=cmd_timeline)

    p_diff = sub.add_parser("diff", help="compare two snapshots")
    p_diff.add_argument("from_date", metavar="FROM")
    p_diff.add_argument("to_date", metavar="TO")
    p_diff.add_argument("--period", default="daily", choices=PERIODS)
    p_diff.add_argument("--limit", type=int, default=10)
    p_diff.set_defaults(func=cmd_diff)

    p_win = sub.add_parser("windows", help="daily / weekly / monthly side by side")
    p_win.add_argument("date", nargs="?", default=None)
    p_win.add_argument("--min-windows", type=int, default=2, dest="min_windows",
                       choices=(1, 2, 3))
    p_win.set_defaults(func=cmd_windows)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # `Archive` and `_resolve_date` raise SystemExit for unusable input. Turn it
    # into a return code so callers (and tests) see a number, not a traceback.
    try:
        archive = Archive(Path(args.data))
        code = args.func(archive, args)
    except SystemExit as exc:
        # `SystemExit("message")` carries the text in `.code`. Uncaught, Python
        # would print it; caught, we have to do that ourselves or the user sees
        # a silent exit code and no explanation.
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        return exc.code if isinstance(exc.code, int) else 2

    if args.command != "stats":
        for problem in archive.problems:
            print(f"[warn] {problem}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
