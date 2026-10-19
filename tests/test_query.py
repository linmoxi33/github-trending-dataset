"""Regression tests for the archive query layer.

These pin the failures that are easy to reintroduce:

  * `latest.json` must never be mistaken for a dated snapshot
  * a gap in the calendar must be reported, not smoothed over
  * a Δtotal that spans missing days must say so
  * repo matching is case-insensitive
  * rank comes from array order, because nothing stores it
  * one corrupt file must not sink a query about the other days
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import query as q  # noqa: E402


# -- fixtures --------------------------------------------------------------


def write_snapshot(folder: Path, day: str, daily=None, weekly=None, monthly=None,
                   captured: str | None = None) -> Path:
    payload = {
        "date": day,
        "captured_at": captured or f"{day}T10:00:00+00:00",
        "source": "https://github.com/trending",
        "lists": {
            "daily": daily or [],
            "weekly": weekly or [],
            "monthly": monthly or [],
        },
    }
    path = folder / f"{day}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def row(repo: str, period: int | None = 100, total: int | None = 1000,
        language: str = "Python", forks: int = 10) -> dict:
    return {
        "repo": repo,
        "url": f"https://github.com/{repo}",
        "description": f"{repo} description",
        "language": language,
        "stars_total": total,
        "forks_total": forks,
        "stars_period": period,
        "built_by": ["a", "b"],
    }


@pytest.fixture
def archive_dir(tmp_path: Path) -> Path:
    """Three consecutive days plus the two non-snapshot JSON files the repo has."""
    write_snapshot(
        tmp_path, "2026-10-17",
        daily=[row("alpha/one", 500, 10_000), row("beta/two", 300, 5_000)],
        weekly=[row("alpha/one", 900, 10_000)],
        monthly=[row("alpha/one", 4_000, 10_000)],
    )
    write_snapshot(
        tmp_path, "2026-10-18",
        daily=[row("beta/two", 700, 5_700), row("alpha/one", 400, 10_400),
               row("gamma/three", 250, 2_500)],
        weekly=[row("beta/two", 1_200, 5_700)],
        monthly=[row("alpha/one", 4_500, 10_400)],
    )
    write_snapshot(
        tmp_path, "2026-10-19",
        daily=[row("gamma/three", 800, 3_300), row("alpha/one", 350, 10_750)],
        weekly=[row("gamma/three", 1_800, 3_300)],
        monthly=[row("alpha/one", 4_800, 10_750)],
    )
    # The two files that broke `glob("*.json")`: `latest.json` sorts after every
    # date, so "newest snapshot" became a non-snapshot.
    (tmp_path / "latest.json").write_text(
        (tmp_path / "2026-10-19.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "awesome_index.json").write_text(
        json.dumps({"domains": {"tts": {"repo": "x/awesome-tts", "stars": 10}}}),
        encoding="utf-8",
    )
    return tmp_path


# -- discovery -------------------------------------------------------------


def test_latest_json_is_not_a_snapshot(archive_dir: Path):
    """The whole reason the regex is anchored instead of using glob('*.json')."""
    archive = q.Archive(archive_dir)
    assert len(archive.dates) == 3
    assert archive.dates[-1].isoformat() == "2026-10-19"
    names = {p.name for p in archive.paths.values()}
    assert "latest.json" not in names
    assert "awesome_index.json" not in names


def test_newest_snapshot_wins_over_sorted_filename(archive_dir: Path):
    """`sorted()` puts 'latest.json' last; the archive must not follow it."""
    archive = q.Archive(archive_dir)
    assert q._resolve_date(archive, None) == archive.dates[-1]
    assert archive.dates[-1].isoformat() == "2026-10-19"


def test_partial_write_with_a_date_in_the_name_is_ignored(archive_dir: Path):
    """An interrupted run leaves `2026-10-21.json.tmp` behind.

    Its name starts with a valid date, so a regex without the trailing `$`
    would accept it and treat a truncated file as a real snapshot.
    """
    (archive_dir / "2026-10-21.json.tmp").write_text('{"date": "2026-10', encoding="utf-8")
    (archive_dir / "2026-10-21.json.bak").write_text("{}", encoding="utf-8")
    archive = q.Archive(archive_dir)
    assert len(archive.dates) == 3
    assert archive.dates[-1].isoformat() == "2026-10-19"
    assert not any("21" in p.name for p in archive.paths.values())


def test_impossible_calendar_date_is_reported_not_fatal(archive_dir: Path):
    (archive_dir / "2026-13-01.json").write_text("{}", encoding="utf-8")
    archive = q.Archive(archive_dir)
    assert len(archive.dates) == 3
    assert any("2026-13-01.json" in p for p in archive.problems)


def test_empty_directory_exits(tmp_path: Path):
    with pytest.raises(SystemExit):
        q.Archive(tmp_path)


def test_missing_directory_exits(tmp_path: Path):
    with pytest.raises(SystemExit):
        q.Archive(tmp_path / "nope")


# -- gaps ------------------------------------------------------------------


def test_missing_days_are_reported(archive_dir: Path):
    archive = q.Archive(archive_dir)
    assert archive.missing_days() == []

    write_snapshot(archive_dir, "2026-10-22", daily=[row("alpha/one")])
    archive = q.Archive(archive_dir)
    assert [d.isoformat() for d in archive.missing_days()] == ["2026-10-20", "2026-10-21"]


def test_missing_days_are_interior_only(archive_dir: Path):
    """Leading and trailing absences are just the archive's start and end."""
    write_snapshot(archive_dir, "2026-10-24", daily=[row("alpha/one")])
    archive = q.Archive(archive_dir)
    missing = [d.isoformat() for d in archive.missing_days()]
    assert "2026-10-16" not in missing
    assert "2026-10-20" in missing
    assert "2026-10-25" not in missing


# -- integrity -------------------------------------------------------------


def test_latest_json_match_is_detected(archive_dir: Path):
    archive = q.Archive(archive_dir)
    assert q._check_latest(archive).startswith("matches 2026-10-19")


def test_stale_latest_json_is_a_mismatch(archive_dir: Path):
    """A run interrupted between the two writes leaves the copy behind."""
    stale = json.loads((archive_dir / "2026-10-18.json").read_text(encoding="utf-8"))
    (archive_dir / "latest.json").write_text(json.dumps(stale), encoding="utf-8")
    archive = q.Archive(archive_dir)
    assert "MISMATCH" in q._check_latest(archive)


def test_absent_latest_json_is_not_an_error(archive_dir: Path):
    (archive_dir / "latest.json").unlink()
    archive = q.Archive(archive_dir)
    assert q._check_latest(archive) == "absent"


# -- rank ------------------------------------------------------------------


def test_rank_follows_array_order(archive_dir: Path):
    """Nothing stores a rank field; position in the array is the only truth."""
    archive = q.Archive(archive_dir)
    day = q.date(2026, 10, 18)
    assert archive.find(day, "beta/two")[0] == 1
    assert archive.find(day, "alpha/one")[0] == 2
    assert archive.find(day, "gamma/three")[0] == 3


def test_rank_is_not_sorted_by_stars_total(archive_dir: Path):
    """beta/two leads on 2026-10-18 despite alpha/one having more total stars."""
    archive = q.Archive(archive_dir)
    day = q.date(2026, 10, 18)
    beta = archive.find(day, "beta/two")[1]
    alpha = archive.find(day, "alpha/one")[1]
    assert beta["stars_total"] < alpha["stars_total"]
    assert archive.find(day, "beta/two")[0] < archive.find(day, "alpha/one")[0]


def test_repo_lookup_is_case_insensitive(archive_dir: Path):
    archive = q.Archive(archive_dir)
    day = q.date(2026, 10, 18)
    assert archive.find(day, "ALPHA/One") is not None
    assert archive.find(day, "alpha/one")[0] == archive.find(day, "Alpha/One")[0]


def test_absent_repo_returns_none(archive_dir: Path):
    archive = q.Archive(archive_dir)
    assert archive.find(q.date(2026, 10, 19), "nobody/nothing") is None


def test_period_isolation(archive_dir: Path):
    """A repo in monthly but not weekly must not leak across periods."""
    archive = q.Archive(archive_dir)
    day = q.date(2026, 10, 18)
    # 2026-10-18: beta/two is in daily + weekly, alpha/one in daily + monthly.
    assert archive.find(day, "beta/two", "daily") is not None
    assert archive.find(day, "beta/two", "weekly") is not None
    assert archive.find(day, "beta/two", "monthly") is None
    assert archive.find(day, "alpha/one", "monthly") is not None
    assert archive.find(day, "alpha/one", "weekly") is None


# -- corrupt input ---------------------------------------------------------


def test_corrupt_snapshot_is_skipped_not_fatal(archive_dir: Path):
    (archive_dir / "2026-10-18.json").write_text("{ this is not json", encoding="utf-8")
    archive = q.Archive(archive_dir)
    assert archive.snapshot(q.date(2026, 10, 18)) is None
    assert any("2026-10-18.json" in p for p in archive.problems)
    # The surviving days still answer.
    assert archive.rows(q.date(2026, 10, 19), "daily")


def test_snapshot_without_lists_is_skipped(archive_dir: Path):
    (archive_dir / "2026-10-18.json").write_text('{"date": "2026-10-18"}', encoding="utf-8")
    archive = q.Archive(archive_dir)
    assert archive.snapshot(q.date(2026, 10, 18)) is None
    assert any("no 'lists'" in p for p in archive.problems)


# -- timeline --------------------------------------------------------------


def test_timeline_flags_span_across_a_gap(archive_dir: Path):
    """Δtotal must not read as one day's growth when days are missing."""
    write_snapshot(archive_dir, "2026-10-23", daily=[row("alpha/one", 100, 12_000)])
    archive = q.Archive(archive_dir)
    hits = []
    for day in archive.dates:
        found = archive.find(day, "alpha/one", "daily")
        if found:
            hits.append(found)

    # 2026-10-19 -> 2026-10-23 is a 4-day span with three days missing.
    previous, current = hits[-2][1], hits[-1][1]
    span = (archive.dates[-1] - q.date(2026, 10, 19)).days
    assert span == 4
    assert q._delta(current["stars_total"], previous["stars_total"]) == 12_000 - 10_750


def test_drift_is_total_delta_minus_reported_period(archive_dir: Path):
    """drift = Δtotal − stars_period; both figures come from GitHub, so they differ."""
    current = {"stars_total": 10_400, "stars_period": 400}
    previous = {"stars_total": 10_000}
    assert q._drift(current, previous) == 0

    current = {"stars_total": 10_500, "stars_period": 400}
    assert q._drift(current, previous) == 100


def test_drift_returns_none_when_a_figure_is_missing():
    assert q._drift({"stars_total": None, "stars_period": 10}, {"stars_total": 5}) is None
    assert q._drift({"stars_total": 10, "stars_period": None}, {"stars_total": 5}) is None


def test_missing_between_counts_only_interior_days(archive_dir: Path):
    """A span note has to name how many days were never captured, not just the span."""
    write_snapshot(archive_dir, "2026-10-23", daily=[row("alpha/one")])
    archive = q.Archive(archive_dir)
    assert q._missing_between(archive, q.date(2026, 10, 18), q.date(2026, 10, 23)) == 3


def test_missing_between_is_zero_for_adjacent_snapshots(archive_dir: Path):
    archive = q.Archive(archive_dir)
    assert q._missing_between(archive, q.date(2026, 10, 17), q.date(2026, 10, 18)) == 0


def test_missing_between_ignores_days_that_exist(archive_dir: Path):
    """The fixture already holds 10-17..10-19; 10-19 must not be counted as missing."""
    write_snapshot(archive_dir, "2026-10-20", daily=[row("alpha/one")])
    archive = q.Archive(archive_dir)
    assert q._missing_between(archive, q.date(2026, 10, 18), q.date(2026, 10, 20)) == 0

    write_snapshot(archive_dir, "2026-10-23", daily=[row("alpha/one")])
    archive = q.Archive(archive_dir)
    # 10-21 and 10-22 are the only absent days in that range.
    assert q._missing_between(archive, q.date(2026, 10, 20), q.date(2026, 10, 23)) == 2


def test_delta_tolerates_nulls():
    assert q._delta(10, None) is None
    assert q._delta(None, 10) is None
    assert q._delta(10, 4) == 6


# -- diff ------------------------------------------------------------------


def test_diff_separates_entered_left_and_moved(archive_dir: Path):
    archive = q.Archive(archive_dir)
    before = {(r["repo"] or "").lower(): (i, r)
              for i, r in enumerate(archive.rows(q.date(2026, 10, 17), "daily"), 1)}
    after = {(r["repo"] or "").lower(): (i, r)
             for i, r in enumerate(archive.rows(q.date(2026, 10, 18), "daily"), 1)}

    assert after.keys() - before.keys() == {"gamma/three"}
    assert before.keys() - after.keys() == set()
    # alpha fell from #1 to #2, beta rose from #2 to #1.
    assert before["alpha/one"][0] - after["alpha/one"][0] == -1
    assert before["beta/two"][0] - after["beta/two"][0] == 1


def test_diff_flags_non_contiguous_range(archive_dir: Path):
    write_snapshot(archive_dir, "2026-10-25", daily=[row("alpha/one")])
    archive = q.Archive(archive_dir)
    span = (archive.dates[-1] - archive.dates[0]).days
    assert span > 1


# -- windows ---------------------------------------------------------------


def test_windows_counts_crossings(archive_dir: Path):
    archive = q.Archive(archive_dir)
    day = q.date(2026, 10, 19)
    presence: dict[str, set[str]] = {}
    for period in q.PERIODS:
        for r in archive.rows(day, period):
            presence.setdefault(r["repo"].lower(), set()).add(period)

    assert presence["alpha/one"] == {"daily", "monthly"}
    assert presence["gamma/three"] == {"daily", "weekly"}
    assert len(presence["alpha/one"]) == 2


# -- cli surface -----------------------------------------------------------


def test_cli_stats_json(archive_dir: Path, capsys):
    code = q.main(["--data", str(archive_dir), "--json", "stats"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["snapshots"] == 3
    assert payload["first"] == "2026-10-17"
    assert payload["last"] == "2026-10-19"
    assert payload["span_days"] == 3
    assert payload["missing_days"] == []
    assert payload["distinct_repos"] == 3


def test_cli_top_json_respects_limit_and_rank(archive_dir: Path, capsys):
    code = q.main(["--data", str(archive_dir), "--json", "top", "--limit", "2"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["date"] == "2026-10-19"
    assert [r["rank"] for r in payload["rows"]] == [1, 2]
    assert payload["rows"][0]["repo"] == "gamma/three"


def test_cli_top_renders_missing_fields_without_exotic_glyphs(archive_dir: Path, capsys, monkeypatch):
    """A row with no language and no star count still has to print something.

    The placeholder used to be an em dash, which GBK renders as `¡ª`.
    `capsys` presents UTF-8, so `glyphs()` legitimately picks unicode there and
    an ASCII assertion would test nothing. Force the ASCII branch instead - that
    is the console the placeholder has to survive.
    """
    monkeypatch.setattr(q, "glyphs", lambda stream=None: {
        "d_rank": "d-rank", "d_total": "d-total", "dot": "-", "up": "+", "down": "-",
    })
    write_snapshot(
        archive_dir, "2026-10-26",
        daily=[{"repo": "sparse/row", "url": "https://github.com/sparse/row",
                "description": None, "language": None, "stars_total": None,
                "forks_total": None, "stars_period": None, "built_by": []}],
    )
    code = q.main(["--data", str(archive_dir), "top", "--date", "2026-10-26"])
    assert code == 0
    out = capsys.readouterr().out
    assert "sparse/row" in out
    assert out.isascii(), "ASCII console must get an ASCII placeholder"


def test_cli_top_sort_by_total(archive_dir: Path, capsys):
    code = q.main(["--data", str(archive_dir), "--json", "top", "--sort", "total", "--limit", "2"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    totals = [r["stars_total"] for r in payload["rows"]]
    assert totals == sorted(totals, reverse=True)


def test_cli_timeline_unknown_repo_exits(archive_dir: Path):
    assert q.main(["--data", str(archive_dir), "timeline", "nobody/nothing"]) == 2


def test_cli_unknown_date_suggests_nearest(archive_dir: Path, capsys):
    code = q.main(["--data", str(archive_dir), "top", "--date", "2026-10-20"])
    assert code == 2
    assert "nearest snapshot is 2026-10-19" in capsys.readouterr().err


def test_cli_bad_date_format_exits(archive_dir: Path):
    assert q.main(["--data", str(archive_dir), "top", "--date", "yesterday"]) == 2


def test_cli_diff_rejects_identical_dates(archive_dir: Path):
    assert q.main(["--data", str(archive_dir), "diff", "2026-10-19", "2026-10-19"]) == 2


def test_cli_diff_json(archive_dir: Path, capsys):
    code = q.main(["--data", str(archive_dir), "--json", "diff", "2026-10-17", "2026-10-18"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["span_days"] == 1
    assert payload["contiguous"] is True
    assert [e["repo"] for e in payload["entered"]] == ["gamma/three"]
    assert payload["left"] == []
    assert payload["movers"][0]["repo"] == "beta/two"
    assert payload["movers"][0]["delta"] == 1


def test_cli_windows_json(archive_dir: Path, capsys):
    code = q.main(["--data", str(archive_dir), "--json", "windows", "2026-10-19"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"] == {"daily": 2, "weekly": 1, "monthly": 1}
    # gamma/three = daily + weekly, alpha/one = daily + monthly. Both cross two
    # windows; the tie is broken by rank, and gamma holds #1 in both of its.
    assert [c["repo"] for c in payload["crossing"]] == ["gamma/three", "alpha/one"]
    assert payload["crossing"][0]["windows"] == ["daily", "weekly"]
    assert payload["crossing"][1]["windows"] == ["daily", "monthly"]


def test_cli_windows_requires_min_two_by_default(archive_dir: Path, capsys):
    q.main(["--data", str(archive_dir), "--json", "windows", "2026-10-19"])
    payload = json.loads(capsys.readouterr().out)
    assert all(len(c["windows"]) >= 2 for c in payload["crossing"])


def test_cli_windows_min_one_lists_everything(archive_dir: Path, capsys):
    q.main(["--data", str(archive_dir), "--json", "windows", "2026-10-19", "--min-windows", "1"])
    payload = json.loads(capsys.readouterr().out)
    # Two distinct repos appear that day; every one of them is a crossing at 1.
    assert len(payload["crossing"]) == 2


def test_cli_windows_min_three_is_empty_when_nothing_sweeps_all_three(archive_dir: Path, capsys):
    q.main(["--data", str(archive_dir), "--json", "windows", "2026-10-19", "--min-windows", "3"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["crossing"] == []


# -- console encoding ------------------------------------------------------


def test_every_printed_character_survives_a_gbk_console(archive_dir: Path, capsys):
    """A Chinese Windows console is GBK, where `Δ` raises UnicodeEncodeError.

    Not a mojibake box - the script died with a traceback before this was
    fixed. Encoding alone is not enough of a check: `—` encodes to GBK bytes
    that *display* as `¡ª`, so this also requires the output to survive a
    round-trip unchanged. Anything that changes identity on the way to the
    console is unreadable to the person looking at it.
    """
    commands = [
        ["stats"],
        ["top", "--limit", "3"],
        ["timeline", "alpha/one"],
        ["diff", "2026-10-17", "2026-10-18"],
        ["windows", "2026-10-19"],
    ]
    for command in commands:
        capsys.readouterr()
        code = q.main(["--data", str(archive_dir), *command])
        assert code == 0, f"{command} exited {code}"
        out = capsys.readouterr().out
        assert out, f"{command} printed nothing"
        try:
            roundtrip = out.encode("gbk").decode("gbk")
        except UnicodeEncodeError as exc:
            bad = out[exc.start : exc.end]
            pytest.fail(f"{command} prints {bad!r}, which GBK cannot encode")
        assert roundtrip == out, f"{command} output is mangled by GBK"


class _FakeStream:
    """A stream whose encoding we control, standing in for a GBK console."""

    def __init__(self, encoding: str) -> None:
        self.encoding = encoding


def test_unicode_console_gets_unicode_glyphs():
    g = q.glyphs(_FakeStream("utf-8"))
    assert g["d_rank"] == "Δrank"
    assert g["dot"] == "·"
    assert g["up"] == "▲"


def test_gbk_console_gets_ascii_glyphs():
    """The fallback must actually change the labels, not just be declared."""
    g = q.glyphs(_FakeStream("gbk"))
    for key in ("d_rank", "d_total", "dot", "up", "down"):
        assert g[key].isascii(), f"{key}={g[key]!r} is not ASCII"


def test_glyph_set_is_resolved_per_stream_not_at_import():
    """Freezing the labels at import would ignore a later stdout redirect."""
    assert q.glyphs(_FakeStream("utf-8")) != q.glyphs(_FakeStream("gbk"))


def test_unknown_encoding_falls_back_rather_than_crashing():
    g = q.glyphs(_FakeStream("no-such-codec"))
    assert g["dot"].isascii()


# -- real repository data --------------------------------------------------

def test_real_snapshot_parses():
    """Guard the shipped snapshot against schema drift in fetch_trending.py."""
    data = Path(__file__).resolve().parents[1] / "data"
    if not (data / "latest.json").exists():
        pytest.skip("no committed snapshot")

    archive = q.Archive(data)
    day = archive.dates[-1]
    rows = archive.rows(day, "daily")
    assert rows, "daily list is empty"
    for r in rows:
        assert set(r) >= {"repo", "url", "stars_total", "stars_period"}
        assert "/" in r["repo"]
        assert isinstance(r["stars_total"], int)
