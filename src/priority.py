"""Big / unique news detection (heuristic, no LLM).

Every new article gets a heat score:

- High-signal keywords in the headline (model launches, regulation, court
  cases, funding rounds, acquisitions, scoops, big-tech names...).
- A "coverage" bonus when two or more feeds report the same story, which is a
  strong signal it's genuinely major, not a one-off item.

Stories scoring >= HOT_THRESHOLD are flagged hot and trigger the instant
"BREAKING AI NEWS" alert email (see graph.py). Everything else waits for the
regular digest. Keep it dumb on purpose -- a headline typo can only downgrade
a single story, never break the pipeline.
"""

import re
from collections import Counter
from typing import Dict, List, Tuple

from src.config import HOT_THRESHOLD

# (weight, tag, keywords[...]) -- weights only matter relative to HOT_THRESHOLD
HOT_KEYWORDS: List[Tuple[int, str, List[str]]] = [
    (80, "breaking", ["breaking", "exclusive", "urgent"]),
    (70, "regulation", ["eu ai act", "ai act", "artificial intelligence act", "executive order", "export control", "lawsuit", "court", "regulat", "sanction", "congress", "white house", "legislat", "lawmaker", "ban"]),
    (60, "money", ["billion", "million", "valuation", "acquisit", "merger", "ipo", "funding round", "raises $", "series a", "series b", "series c", "investment"]),
    (55, "frontier-model", ["gpt-", "gpt5", "o3", "o4", "claude", "superintelligence", "agi", "reasoning model", "frontier model", "grok", "deepseek"]),
    (45, "big-tech", ["openai", "anthropic", "google", "deepmind", "microsoft", "meta", "nvidia", "apple", "amazon", "tsmc", "xai"]),
    (35, "launch", ["launch", "release", "unveil", "announc", "introduc", "rolls out", "available"]),
    (30, "scoop", ["leak", "rumor", "source says", "reportedly"]),
]

COVERAGE_BONUS = 40  # same story on 2+ different feeds => clearly major


def _normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def _coverage_counts(all_articles: List[Dict]) -> Counter:
    counts: Counter = Counter()
    for a in all_articles:
        key = _normalize_title(a.get("title", ""))
        if key:
            counts[key] += 1
    return counts


def _keyword_hits(title: str) -> Tuple[int, List[str]]:
    t = title.lower()
    score = 0
    tags: List[str] = []
    for weight, tag, keywords in HOT_KEYWORDS:
        for kw in keywords:
            if len(kw) <= 4:
                if re.search(rf"\b{re.escape(kw)}\w*", t):
                    score += weight
                    tags.append(tag)
                    break
            elif kw in t:
                score += weight
                tags.append(tag)
                break
    return score, tags


def annotate(all_articles: List[Dict]) -> List[Dict]:
    """Add heat / hot / tags / coverage fields to every article in place."""
    counts = _coverage_counts(all_articles)
    for a in all_articles:
        title = a.get("title", "")
        coverage = counts.get(_normalize_title(title), 1)
        kw_score, tags = _keyword_hits(title)
        heat = kw_score + (COVERAGE_BONUS if coverage >= 2 else 0)
        if coverage >= 2:
            tags.append("multiple-outlets")
        a["heat"] = heat
        a["hot"] = heat >= HOT_THRESHOLD
        a["tags"] = tags
        a["coverage"] = coverage
    return all_articles


def split_hot(all_articles: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Return (hot, normal) articles."""
    hot = [a for a in all_articles if a.get("hot")]
    normal = [a for a in all_articles if not a.get("hot")]
    return hot, normal