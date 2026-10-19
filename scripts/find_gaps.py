"""Compare trending topic words against the existing awesome-list landscape.

Inputs
    data/latest.json          - output of fetch_trending.py
    data/awesome_index.json   - {"domains": {domain: {"stars": n, "repo": str}}, ...}

Output
    data/gap/YYYY-MM-DD.json  - scored candidate gaps, highest first

Scoring (0-100)
    crowding   0-35  fewer existing awesome lists -> higher
    momentum   0-40  faster star velocity in trending -> higher
    spread     0-25  more independent repos riding the topic -> higher
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Words that say nothing about a domain.
STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "without", "from", "into",
    "your", "you", "my", "our", "its", "their", "this", "that", "these",
    "is", "are", "was", "were", "be", "been", "being", "to", "of", "in", "on",
    "at", "by", "as", "it", "we", "i", "but", "not", "no", "all", "any",
    "open", "source", "based", "using", "used", "use", "built", "build",
    "simple", "fast", "lightweight", "modern", "new", "free", "self",
    "hosted", "selfhosted", "tool", "tools", "app", "apps", "project",
    "projects", "library", "framework", "platform", "system", "service",
    "support", "supports", "makes", "make", "get", "set", "run", "runs",
    "works", "working", "like", "just", "now", "one", "two", "way", "ways",
    "github", "repo", "code", "demo", "example", "examples", "collection",
    "curated", "list", "lists", "awesome", "resources", "resource",
    "guides", "guide", "tutorial", "tutorials", "docs", "documentation",
    "more", "most", "better", "best", "easy", "easily", "powerful",
    "scalable", "blazing", "extremely", "very", "really", "actually",
    "alternative", "alternatives", "instead", "than", "then", "only",
    "every", "each", "other", "another", "same", "own", "via", "over",
    "under", "about", "across", "between", "through", "during", "after",
    "before", "while", "when", "where", "which", "who", "how", "what", "why",
    # verbs and filler that describe an action rather than a domain
    "write", "writing", "writes", "read", "reading", "search", "searching",
    "evaluate", "evaluating", "evaluation", "find", "finding", "tailor",
    "tailoring", "generate", "generating", "convert", "converting",
    "manage", "managing", "monitor", "monitoring", "automate", "automating",
    "automation", "integrate", "integrating", "deploy", "deploying",
    "install", "installing", "configure", "configuring", "create",
    "creating", "add", "adds", "adding", "enable", "enables", "allow",
    "allows", "help", "helps", "helping", "show", "shows", "see", "look",
    "try", "tries", "need", "needs", "want", "wants", "give", "gives",
    "take", "takes", "turn", "turns", "keep", "keeps", "let", "lets",
    "job", "jobs", "posting", "postings", "letter", "letters", "cv", "cvs",
    "resume", "resumes", "applicant", "applicants", "hiring", "recruiter",
    "interview", "interviews", "candidate", "candidates", "apply",
    "applying", "application", "applications", "salary", "remote",
    "developer", "developers", "engineer", "engineers", "user", "users",
    "people", "person", "team", "teams", "company", "companies",
    "business", "product", "products", "feature", "features",
    "everything", "anything", "something", "nothing", "thing", "things",
    "world", "life", "time", "times", "day", "days", "week", "month",
    "year", "first", "last", "next", "back", "down", "up", "out", "off",
    "here", "there", "always", "never", "often", "still", "even", "also",
    "much", "many", "such", "some", "few", "both", "either", "neither",
    "does", "did", "done", "doing", "has", "have", "had", "having",
    "will", "would", "can", "could", "should", "may", "might", "must",
    "yourself", "itself", "themselves", "ourselves", "such", "per", "etc",
    # metrics / packaging words that are never a domain
    "fork", "forks", "star", "stars", "version", "versions", "release",
    "releases", "update", "updates", "plugin", "plugins", "extension",
    "extensions", "official", "directory", "managed", "runtime", "prep",
    "cover", "memory", "agent", "agents", "harness", "specification",
    "spec", "specs", "quality", "high", "high-quality", "original",
    "solution", "solutions", "intelligent", "autonomous", "conversational",
    "multi-player", "multi", "player", "swarm", "swarms", "handoff",
    "vendor", "vendors", "long", "long-term", "term", "between", "different",
    "coordinate", "facilitate", "deploy", "intelligent", "original",
    "runs", "coding", "coding-agent", "claude-code", "claude", "cursor",
    "anthropic", "openai", "gpt", "gemini", "llama", "web", "terminal",
    "desktop", "mobile", "server", "client", "local", "cloud", "online",
    # product / brand names: trending entries mention them, but they are not
    # domains anyone would catalogue
    "elevenlabs", "voicestudio", "chattts", "cosyvoice", "melotts", "suno",
    "grok", "deepseek", "qwen", "mistral", "midjourney", "sora", "kling",
    "comfyui", "wan", "flux", "whisper", "python", "javascript",
    "typescript", "rust", "golang", "swift", "kotlin", "php", "ruby",
    "apple", "google", "microsoft", "meta", "nvidia", "amazon",
    # adjectives that survive the filter but carry no domain meaning
    "automatic", "automated", "fully-local", "fully", "simply", "quick",
    "quickly", "instant", "instantly", "seamless", "seamlessly", "robust",
    "efficient", "flexible", "customizable", "extensible", "minimal",
    "tiny", "small", "large", "huge", "gigantic", "massive", "ultimate",
    "complete", "full", "whole", "entire", "single", "multiple", "various",
    "several", "countless", "endless", "infinite",
    # inflected forms that the shallow suffix stripper will not reduce cleanly
    "automatically", "quickly-", "seamlessly", "efficiently", "instantly",
    "simply", "easily", "reliably", "consistently", "beautifully",
}

# Multi-word phrases worth treating as one domain.
PHRASES = {
    "job search": "job-search",
    "model context protocol": "mcp",
    "command line": "cli",
    "text to speech": "tts",
    "speech to text": "stt",
    "large language model": "llm",
    "language model": "llm",
    "coding agent": "coding-agent",
    "code agent": "coding-agent",
    "local first": "local-first",
    "prompt engineering": "prompt-engineering",
    "reinforcement learning": "reinforcement-learning",
    "retrieval augmented": "rag",
    "voice clone": "voice-clone",
    "voice cloning": "voice-clone",
    "video generation": "video-generation",
    "image generation": "image-generation",
    "code review": "code-review",
    "static analysis": "static-analysis",
    "knowledge graph": "knowledge-graph",
    "vector database": "vector-db",
    "fine tuning": "fine-tuning",
    "web scraping": "web-scraping",
    "browser automation": "browser-automation",
    "workflow automation": "workflow-automation",
}

WORD_RE = re.compile(r"[a-z][a-z0-9+#.-]{2,}")

SUFFIXES = ("ally", "ly", "ed", "ing", "es", "s")


def strip_suffix(word: str) -> str:
    """Peel a trailing plural/adverb marker so `letters` -> `letter`.

    Deliberately shallow. Deeper suffix stripping produced false roots
    (`automatically` -> `automat`) and split hyphenated phrases. Words whose
    inflected form matters are listed explicitly in STOPWORDS instead.
    """
    for suffix in SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def norm_domain(name: str) -> str:
    base = name.split("/")[-1].lower()
    base = re.sub(r"^awesome[-_]", "", base)
    base = re.sub(r"[-_](awesome|list|lists|resources?|collection)$", "", base)
    return base


def load_domains(path: Path) -> dict[str, dict]:
    if not path.exists():
        print(f"[warn] {path} missing, crowding score will be 0 for all", file=sys.stderr)
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("domains", raw)


def extract_topics(entry: dict) -> set[str]:
    """Pull domain words out of a trending entry.

    Only the *description* is mined, plus the canonical phrases list. Repo
    names are deliberately ignored: `anthropic/claude-plugins-official` is a
    product name, not a domain, and splitting it produces garbage like
    "anthropic-managed".
    """
    blob = (entry.get("description") or "").lower()
    topics: set[str] = set()

    for phrase, canon in PHRASES.items():
        if phrase in blob:
            topics.add(canon)

    for word in WORD_RE.findall(blob):
        word = word.strip(".-")
        if word in STOPWORDS or len(word) < 3:
            continue
        if word.isdigit():
            continue
        if strip_suffix(word) in STOPWORDS:
            continue
        topics.add(word)

    return topics


def score(candidate: str, hits: int, velocity: float, domains: dict[str, dict],
          witnesses: int = 1) -> dict:
    """Score a candidate domain on a 0-100 scale.

    The three components are deliberately *bounded and graded* so candidates
    spread out instead of all pinning at 100:
      crowding  0-35  each existing awesome list costs 7 points
      momentum  0-40  logarithmic in star velocity, 50k/period saturates
      spread    0-25  how many independent repos rode the topic at once
    """
    crowding = max(0.0, 35.0 - hits * 7.0)

    if velocity <= 0:
        momentum = 0.0
    else:
        # log10(1 + v) / log10(1 + 50000) mapped onto 0..40
        momentum = min(40.0, 40.0 * math.log10(1 + velocity) / math.log10(1 + 50000))

    spread = min(25.0, witnesses * 5.0)

    total = crowding + momentum + spread
    match = domains.get(candidate)
    return {
        "domain": candidate,
        "score": round(total, 1),
        "breakdown": {
            "crowding": round(crowding, 1),
            "momentum": round(momentum, 1),
            "spread": round(spread, 1),
        },
        "existing_lists": hits,
        "existing_top_stars": (match or {}).get("stars", 0),
        "existing_top_repo": (match or {}).get("repo"),
    }


def count_lists(domain: str, domains: dict[str, dict], repo_names: list[str]) -> int:
    """How many existing awesome lists target this domain.

    A domain counts as covered when an index key *contains* it as a whole
    token: `tts` is covered by `chatt-tts`-style keys and by `text-to-speech`,
    `coding-agent` by `coding-agents`. Exact matches are counted once so the
    same list is never double-counted.
    """
    if not domain:
        return 0
    hits = set()
    exact = domains.get(domain)
    if exact is not None:
        hits.add(exact["repo"])

    # Split both sides on non-alphanumerics so `tts` matches `chat-tts` but not
    # `attackss`. Short domains need an exact token, longer ones may match a
    # prefix/suffix word.
    for key, meta in domains.items():
        if key == domain:
            continue
        tokens = re.split(r"[^a-z0-9]+", key)
        if len(domain) < 4:
            # Short acronyms need care: `tts` should cover `chattts` and
            # `chat-tts`, but never `attackss`. Accept only when the acronym
            # sits at a token boundary -- a prefix or suffix of the token --
            # rather than anywhere inside it.
            if domain in tokens or any(
                (t.startswith(domain) or t.endswith(domain)) and len(t) <= 12
                for t in tokens
            ):
                hits.add(meta["repo"])
        elif key.startswith(domain) or key.endswith(domain):
            hits.add(meta["repo"])
        elif domain in tokens:
            hits.add(meta["repo"])
    return len(hits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/latest.json")
    ap.add_argument("--index", default="data/awesome_index.json")
    ap.add_argument("--outdir", default="data/gap")
    ap.add_argument("--min-score", type=float, default=55.0)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    snap = json.loads(Path(args.data).read_text(encoding="utf-8"))
    domains = load_domains(Path(args.index))

    # topic -> aggregate momentum + witnesses
    agg: dict[str, dict] = {}
    for period, rows in snap.get("lists", {}).items():
        weight = {"daily": 3.0, "weekly": 1.5, "monthly": 1.0}.get(period, 1.0)
        for row in rows:
            velocity = (row.get("stars_period") or 0) * weight
            for topic in extract_topics(row):
                slot = agg.setdefault(
                    topic, {"velocity": 0.0, "repos": set(), "witness_names": []}
                )
                slot["velocity"] += velocity
                slot["repos"].add(row["repo"])
                if len(slot["witness_names"]) < 3 and row["repo"] not in slot["witness_names"]:
                    slot["witness_names"].append(row["repo"])

    scored = []
    for topic, info in agg.items():
        hits = count_lists(topic, domains, list(domains))
        witnesses = len(info["repos"])
        item = score(topic, hits, info["velocity"], domains, witnesses)
        item["witnesses"] = info["witness_names"][:3]
        scored.append(item)
    scored.sort(key=lambda x: (-x["score"], -x["breakdown"]["momentum"]))

    date_key = snap.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    top = [s for s in scored if s["score"] >= args.min_score][: args.top]
    payload = {
        "date": date_key,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_score": args.min_score,
        "candidates": top,
        "total_topics_seen": len(scored),
    }
    out = outdir / f"{date_key}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[topics] {len(scored)} seen, {len(top)} above {args.min_score}")
    for item in top[:10]:
        print(
            f"  {item['score']:>5.1f}  {item['domain']:<28}"
            f" lists={item['existing_lists']} top={item['existing_top_stars']}"
        )
    print(f"[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
