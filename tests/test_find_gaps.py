"""Regression tests for the gap scorer.

These pin the behaviours that were wrong during development, so a later edit
cannot quietly bring them back:

  * repo names must never be mined for topics
  * short domains must match whole tokens only (`tts` != `attackss`)
  * scores must spread instead of pinning at 100
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import find_gaps as fg  # noqa: E402


def test_repo_name_is_not_a_topic():
    entry = {
        "repo": "anthropics/claude-plugins-official",
        "description": "A curated list of database migration tools.",
    }
    topics = fg.extract_topics(entry)
    assert "anthropic-managed" not in topics
    assert "claude-plugins-official" not in topics
    assert "database" in topics
    assert "migration" in topics


def test_description_phrases_are_canonicalised():
    entry = {"repo": "x/y", "description": "Tools for text to speech pipelines."}
    topics = fg.extract_topics(entry)
    assert "tts" in topics


def test_short_domain_matches_whole_token_only():
    domains = {
        "chattts": {"repo": "a/awesome-chattts", "stars": 10},
        "attackss": {"repo": "b/awesome-attackss", "stars": 10},
    }
    assert fg.count_lists("tts", domains, list(domains)) == 1


def test_exact_domain_counts_once_even_with_similar_siblings():
    domains = {
        "video": {"repo": "k/awesome-video", "stars": 1929},
        "video-diffusion-models": {"repo": "d/awesome-video-diffusion", "stars": 500},
    }
    hits = fg.count_lists("video", domains, list(domains))
    assert hits == 2  # exact + prefix match, both real lists


def test_scores_do_not_all_pin_at_100():
    domains = {}
    slow = fg.score("alpha", 0, 50.0, domains, 1)
    fast = fg.score("beta", 0, 40000.0, domains, 8)
    assert slow["score"] < fast["score"] < 100.0
    assert slow["breakdown"]["momentum"] < fast["breakdown"]["momentum"]


def test_crowding_falls_as_lists_appear():
    domains = {}
    free = fg.score("x", 0, 1000.0, domains, 1)
    covered = fg.score("x", 5, 1000.0, domains, 1)
    assert free["breakdown"]["crowding"] == 35.0
    assert covered["breakdown"]["crowding"] == 0.0


def test_stopwords_remove_product_and_verb_noise():
    entry = {
        "repo": "x/y",
        "description": "ElevenLabs alternative that writes cover letters automatically.",
    }
    topics = fg.extract_topics(entry)
    for bad in ("elevenlabs", "writes", "letter", "letters", "automatic", "automatically"):
        assert bad not in topics, f"{bad} leaked through"
