# GitHub Trending Dataset

**Daily snapshots of the GitHub Trending lists — the history page nobody kept.**

GitHub's Trending page only ever shows the current moment. Once midnight UTC rolls over, yesterday's ranking is gone: there is no built-in way to ask "what was trending the week that project launched?" This repository keeps every day.

Updated automatically at **23:50 UTC** by GitHub Actions. No bot accounts, no scraped star counts, no invented numbers — just the three public lists, parsed and stored.

---

## What is in here

| Path | Contents |
|---|---|
| `data/YYYY-MM-DD.json` | One snapshot: the daily, weekly and monthly lists as parsed that day |
| `data/latest.json` | The most recent snapshot, for anyone who does not want to sort files |
| `data/awesome_index.json` | Every `awesome-*` repository above 100 stars, collapsed to one entry per domain |
| `data/gap/YYYY-MM-DD.json` | Scored candidates for domains that trend but have no dedicated list |
| `assets/cover.png` | Social preview card |

### Snapshot schema

```jsonc
{
  "date": "2026-10-19",
  "captured_at": "2026-10-19T06:17:02+00:00",
  "lists": {
    "daily": [
      {
        "repo": "anomalyco/opencode",
        "url": "https://github.com/anomalyco/opencode",
        "description": "The open source coding agent.",
        "language": "TypeScript",
        "stars_total": 216871,
        "forks_total": 12034,
        "stars_period": 1414,      // stars gained inside the list window
        "built_by": ["user1", "user2"]
      }
    ],
    "weekly":  [],
    "monthly": []
  }
}
```

`stars_period` is the number that matters for trending — GitHub ranks by velocity, not by total.

---

## Using the data

```python
import json, urllib.request

url = "https://raw.githubusercontent.com/<owner>/github-trending-dataset/main/data/latest.json"
data = json.load(urllib.request.urlopen(url))

for row in data["lists"]["daily"][:10]:
    print(f"{row['repo']:<45} +{row['stars_period']:,} today")
```

Or with `curl`:

```bash
curl -s https://raw.githubusercontent.com/<owner>/github-trending-dataset/main/data/latest.json \
  | jq '.lists.daily[] | {repo, stars_period}'
```

### Why not just read the Trending page?

Three reasons:

1. **No history.** Yesterday's ranking is not addressable today.
2. **No machine-readable output.** The page is HTML with no API behind it.
3. **No comparison.** The three windows (24 h, 7 d, 30 d) are separate pages; here they sit in one file per day.

---

## The gap index

`data/gap/` answers a narrower question: *which domains are hot right now but still have no curated list?*

Each candidate is scored out of 100 on three components:

| Component | Max | Meaning |
|---|---:|---|
| crowding | 35 | Deducted 7 per existing awesome-list in that domain |
| momentum | 40 | Logarithmic in stars gained across the three windows |
| spread | 25 | Five per independent repository riding the topic |

A high score means several projects are pulling attention to a domain that nobody has catalogued yet. A low score means either nobody cares, or the space is already covered by someone with a 50k-star head start.

> The index is a discovery aid, not a verdict. Every candidate still needs a judgement call about whether the demand is real and durable.

<!-- TRENDING:START -->

**Last snapshot:** `2026-10-19` · source: [github.com/trending](https://github.com/trending)

### Top 5 · today

| # | Repository | Language | Stars today | Total |
|---:|---|---|---:|---:|
| 1 | [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) | Python | +2,232 | 54,549 |
| 2 | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | Python | +1,175 | 42,942 |
| 3 | [anomalyco/opencode](https://github.com/anomalyco/opencode) | TypeScript | +1,414 | 216,984 |
| 4 | [cursor/plugins](https://github.com/cursor/plugins) | TypeScript | +350 | 12,888 |
| 5 | [ruvnet/ruflo](https://github.com/ruvnet/ruflo) | TypeScript | +513 | 76,750 |

### Coverage gaps

Domains trending right now that have **no dedicated awesome-list** in the index. Scored out of 100 on crowding / momentum / spread (5 shown).

| Score | Domain | Existing lists | Best existing | Witnesses |
|---:|---|---:|---:|---|
| 81.7 | `sandboxes` | 0 | — | `context-mode`, `cua` |
| 80.0 | `binaries` | 0 | — | `rea` |
| 79.9 | `transcription` | 0 | — | `VoiceStudio` |
| 79.9 | `dictation` | 0 | — | `VoiceStudio` |
| 79.9 | `cloning` | 0 | — | `VoiceStudio` |

<!-- TRENDING:END -->

---

## Running it yourself

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/fetch_trending.py            # write data/<today>.json
python scripts/build_index.py               # refresh the awesome-list index (needs GH_TOKEN)
python scripts/find_gaps.py                 # score candidates into data/gap/
python scripts/render_readme.py             # rewrite the block above
python scripts/make_cover.py                # regenerate assets/cover.png
```

Test the issue notifier without touching your tracker:

```bash
python scripts/notify_issue.py --threshold 80 --dry-run
```

### Automation

`.github/workflows/daily.yml` runs the whole chain on a schedule and commits the result. It also opens one issue per day when a candidate clears the threshold — the only step that asks a human for a decision.

---

## Notes and limits

- Trending is scraped from the public HTML; if GitHub changes the markup the parser needs updating. The workflow fails loudly rather than committing an empty file.
- `stars_period` is whatever GitHub labels in the window ("stars today" / "this week" / "this month"); it is not recomputed from `stars_total`.
- The awesome-list index merges two search queries (`topic:awesome-list` and `awesome in:name`) because plenty of well-known lists never added the topic.
- Star counts here measure bookmarks, not quality. A repo with 50k stars and no commits in two years is a museum piece.

## License

Data: [CC0 1.0](LICENSE) — public domain, use it for anything.
Code: MIT.
