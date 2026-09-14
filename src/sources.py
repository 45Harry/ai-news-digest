"""Fetcher agents: pull raw articles from RSS/Atom feeds.

Kept deliberately dumb and deterministic -- no LLM involved here, so a feed
outage or a slow site never breaks the run, and every headline/link in the
final email is exactly what the publisher wrote. Twitter accounts are fetched
concurrently via RSSHub (or any template you point TWITTER_RSS_TEMPLATE at).
"""

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import feedparser
import requests

from src.config import (
    AI_TWITTER_ACCOUNTS,
    GENERAL_AI_FEEDS,
    LAB_AI_FEEDS,
    POLICY_AI_FEEDS,
    REQUEST_TIMEOUT,
    TWITTER_RSS_TEMPLATE,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-news-digest/1.0; personal use bot)"}

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(text: str) -> str:
    """Strip tags/entities so raw HTML never shows up in the email body."""
    text = _TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_one(url: str, category: str, source_override: str = "") -> List[Dict]:
    articles: List[Dict] = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:  # noqa: BLE001 -- a single bad feed should never kill the run
        print(f"[sources] failed to fetch {url}: {exc}")
        return articles

    source_name = source_override or (parsed.feed.get("title", url) if getattr(parsed, "feed", None) else url)

    for entry in parsed.entries:
        published_ts = 0.0
        if getattr(entry, "published_parsed", None):
            published_ts = time.mktime(entry.published_parsed)
        elif getattr(entry, "updated_parsed", None):
            published_ts = time.mktime(entry.updated_parsed)

        articles.append(
            {
                "title": _clean_text(entry.get("title", "(untitled)")),
                "link": entry.get("link", "").strip(),
                "summary": _clean_text(entry.get("summary", "")),
                "source": source_name,
                "category": category,
                "published_ts": published_ts,
            }
        )
    return articles


def fetch_general_news() -> List[Dict]:
    articles: List[Dict] = []
    for url in GENERAL_AI_FEEDS:
        articles.extend(_fetch_one(url, "general"))
    return articles


def fetch_policy_news() -> List[Dict]:
    articles: List[Dict] = []
    for url in POLICY_AI_FEEDS:
        articles.extend(_fetch_one(url, "policy"))
    return articles


def fetch_lab_news() -> List[Dict]:
    articles: List[Dict] = []
    for url in LAB_AI_FEEDS:
        articles.extend(_fetch_one(url, "labs"))
    return articles


def _fetch_tweet_account(user: str) -> List[Dict]:
    return _fetch_one(TWITTER_RSS_TEMPLATE.format(user=user), "tweets", source_override="@" + user)


def fetch_tweets() -> List[Dict]:
    """Fetch the latest tweets from every lab account, concurrently."""
    articles: List[Dict] = []
    if not AI_TWITTER_ACCOUNTS:
        return articles
    workers = min(len(AI_TWITTER_ACCOUNTS), 8)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_tweet_account, user): user for user in AI_TWITTER_ACCOUNTS}
        for future in as_completed(futures):
            articles.extend(future.result())
    return articles