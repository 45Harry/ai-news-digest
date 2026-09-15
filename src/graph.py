"""The multi-agent graph.

    START --> fetch_general --+
                              |                                      +--> summarize --> send_digest --> END
    START --> fetch_policy  --+--> merge --> prioritize --> verify --> send_breaking --+
    START --> fetch_tweets --+                              |                |
    START --> fetch_labs   --+                    (nothing new --> END)      (no hot --> skip breaking)
                                                                             (no regular news --> END)

Each node is a small, single-purpose agent. fetch_general/fetch_policy/
fetch_tweets/fetch_labs run in parallel; merge fans them back in, drops exact
duplicates and anything already emailed before (via SeenStore); prioritize
scores every story; **verify** is the LLM verification pass that merges
near-duplicate coverage of the same story (keeping the hottest version) and
drops junk before anything is emailed; and:

- hot stories are emailed **immediately** as a BREAKING alert (real time),
- any remaining new stories go into the regular digest with a structured,
  identically-rendered LLM overview (the template never varies by provider).

If nothing new was found, the graph short-circuits to END -- no LLM call, no
email.
"""

from typing import Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph

from src.config import BREAKING_ALERTS, FILTER_TODAY_ONLY, MAX_ARTICLES_PER_RUN, RECENCY_DAYS
from src.mailer import send_breaking_email, send_digest_email
from src.priority import annotate, split_hot
from src.providers import dedupe_news, summarize_digest
from src.seen_store import SeenStore
from src.sources import fetch_general_news, fetch_lab_news, fetch_policy_news, fetch_tweets

import time
from datetime import datetime, timedelta


def _today_cutoff() -> float:
    if not FILTER_TODAY_ONLY:
        return 0.0
    today_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (today_midnight - timedelta(days=RECENCY_DAYS)).timestamp()

_CATEGORIES = ("general", "policy", "tweets", "labs")


class DigestState(TypedDict):
    raw_general: List[Dict]
    raw_policy: List[Dict]
    raw_tweets: List[Dict]
    raw_labs: List[Dict]
    new_general: List[Dict]
    new_policy: List[Dict]
    new_tweets: List[Dict]
    new_labs: List[Dict]
    hot_general: List[Dict]
    hot_policy: List[Dict]
    hot_tweets: List[Dict]
    hot_labs: List[Dict]
    normal_general: List[Dict]
    normal_policy: List[Dict]
    normal_tweets: List[Dict]
    normal_labs: List[Dict]
    overview: str
    sent: bool
    breaking_only: bool


DigestUpdate = Dict[str, object]


def node_fetch_general(state: DigestState) -> DigestUpdate:
    return {"raw_general": fetch_general_news()}


def node_fetch_policy(state: DigestState) -> DigestUpdate:
    return {"raw_policy": fetch_policy_news()}


def node_fetch_tweets(state: DigestState) -> DigestUpdate:
    return {"raw_tweets": fetch_tweets()}


def node_fetch_labs(state: DigestState) -> DigestUpdate:
    return {"raw_labs": fetch_lab_news()}


def _dedupe_and_filter(articles: List[Dict], seen: SeenStore, today_cutoff: float) -> List[Dict]:
    unique: Dict[str, Dict] = {}
    for a in articles:
        if a.get("link"):
            unique[a["link"]] = a
    fresh = [
        a
        for a in unique.values()
        if not seen.has(a["link"]) and a.get("published_ts", 0) >= today_cutoff
    ]
    fresh.sort(key=lambda a: a.get("published_ts", 0), reverse=True)
    return fresh


def node_merge(state: DigestState) -> DigestUpdate:
    seen = SeenStore()
    today_cutoff = _today_cutoff()
    return {
        f"new_{cat}": _dedupe_and_filter(state.get(f"raw_{cat}", []), seen, today_cutoff)[:MAX_ARTICLES_PER_RUN]
        for cat in _CATEGORIES
    }


def route_after_merge(state: DigestState) -> str:
    if state["new_general"] or state["new_policy"] or state["new_tweets"] or state["new_labs"]:
        return "prioritize"
    return END


def node_prioritize(state: DigestState) -> DigestUpdate:
    all_new = annotate(
        state["new_general"] + state["new_policy"] + state["new_tweets"] + state["new_labs"]
    )
    by_link = {a["link"]: a for a in all_new}
    return {
        f"new_{cat}": [by_link[a["link"]] for a in state[f"new_{cat}"] if a["link"] in by_link]
        for cat in _CATEGORIES
    }


def node_verify(state: DigestState) -> DigestUpdate:
    """LLM verification pass: merge same-story near-duplicates and drop junk.

    Runs after prioritization so hotness (incl. the multi-outlet bonus) is
    already known; the kept representative of each group keeps the pipeline's
    hottest version of the story.
    """
    all_new = [a for cat in _CATEGORIES for a in state[f"new_{cat}"]]
    kept = dedupe_news(all_new)
    keep = {a["link"] for a in kept}
    out: DigestUpdate = {}
    for cat in _CATEGORIES:
        cat_new = [a for a in state[f"new_{cat}"] if a["link"] in keep]
        hot, normal = split_hot(cat_new)
        out[f"new_{cat}"] = cat_new
        out[f"hot_{cat}"] = hot
        out[f"normal_{cat}"] = normal
    return out


def node_send_breaking(state: DigestState) -> DigestUpdate:
    """Email big/unique stories immediately (if BREAKING_ALERTS=1).

    With BREAKING_ALERTS off (default), hot stories are NOT emailed right away
    and NOT marked seen -- they stay in the pool and are included in the next
    regular digest instead.
    """
    hot = (
        state.get("hot_general", [])
        + state.get("hot_policy", [])
        + state.get("hot_tweets", [])
        + state.get("hot_labs", [])
    )
    if not hot:
        return {}
    if BREAKING_ALERTS:
        send_breaking_email(hot)
        SeenStore().mark_seen([a["link"] for a in hot])
        print(f"[graph] BREAKING alert sent: {len(hot)} big/unique story(ies)")
    else:
        out: DigestUpdate = {}
        for cat in _CATEGORIES:
            out[f"normal_{cat}"] = state.get(f"normal_{cat}", []) + state.get(f"hot_{cat}", [])
        print(f"[graph] BREAKING alerts off: {len(hot)} big story(ies) folded into digest")
        return out
    return {}


def route_after_breaking(state: DigestState) -> str:
    if state.get("breaking_only"):
        return END
    if (
        state.get("normal_general")
        or state.get("normal_policy")
        or state.get("normal_tweets")
        or state.get("normal_labs")
    ):
        return "summarize"
    return END


def node_summarize(state: DigestState) -> DigestUpdate:
    return {
        "overview": summarize_digest(
            state.get("normal_general", []),
            state.get("normal_policy", []),
            state.get("normal_tweets", []),
            state.get("normal_labs", []),
        )
    }


def node_send_digest(state: DigestState) -> DigestUpdate:
    normal_general = state.get("normal_general", [])
    normal_policy = state.get("normal_policy", [])
    normal_tweets = state.get("normal_tweets", [])
    normal_labs = state.get("normal_labs", [])
    count = len(normal_general) + len(normal_policy) + len(normal_tweets) + len(normal_labs)
    send_digest_email(
        state.get("overview", ""),
        normal_general,
        normal_policy,
        normal_tweets,
        count,
        normal_labs,
    )
    SeenStore().mark_seen([a["link"] for a in normal_general + normal_policy + normal_tweets + normal_labs])
    print(f"[graph] digest sent: {count} new article(s)")
    return {"sent": True}


def build_graph():
    graph = StateGraph(DigestState)
    graph.add_node("fetch_general", node_fetch_general)
    graph.add_node("fetch_policy", node_fetch_policy)
    graph.add_node("fetch_tweets", node_fetch_tweets)
    graph.add_node("fetch_labs", node_fetch_labs)
    graph.add_node("merge", node_merge)
    graph.add_node("prioritize", node_prioritize)
    graph.add_node("verify", node_verify)
    graph.add_node("send_breaking", node_send_breaking)
    graph.add_node("summarize", node_summarize)
    graph.add_node("send_digest", node_send_digest)

    graph.add_edge(START, "fetch_general")
    graph.add_edge(START, "fetch_policy")
    graph.add_edge(START, "fetch_tweets")
    graph.add_edge(START, "fetch_labs")
    graph.add_edge("fetch_general", "merge")
    graph.add_edge("fetch_policy", "merge")
    graph.add_edge("fetch_tweets", "merge")
    graph.add_edge("fetch_labs", "merge")
    graph.add_conditional_edges("merge", route_after_merge, {"prioritize": "prioritize", END: END})
    graph.add_edge("prioritize", "verify")
    graph.add_edge("verify", "send_breaking")
    graph.add_conditional_edges("send_breaking", route_after_breaking, {"summarize": "summarize", END: END})
    graph.add_edge("summarize", "send_digest")
    graph.add_edge("send_digest", END)

    return graph.compile()