"""LLM provider registry with automatic failover.

Each provider is a small (name, callable) pair. `summarize_digest()` walks the
configured chain in order and stops at the first provider that answers; any
provider that raises (bad key, quota, outage) is logged and skipped so the next
provider gets a chance. Add new providers here -- they are picked up
automatically as long as they follow the builder pattern below.
"""

import json
import re
from typing import Callable, Dict, List, Optional, Tuple

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    CEREBRAS_API_KEY,
    CEREBRAS_BASE_URL,
    CEREBRAS_MODEL,
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    HUGGINGFACE_API_KEY,
    HUGGINGFACE_BASE_URL,
    HUGGINGFACE_MODEL,
    LLM_OVERVIEW_PROVIDERS,
    LLM_VERIFY_PROVIDERS,
    NIM_API_KEY,
    NIM_BASE_URL,
    NIM_MODEL,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENCODE_API_KEY,
    OPENCODE_BASE_URL,
    OPENCODE_MODEL,
)

SYSTEM_PROMPT = (
    "You are a terse AI-industry news editor. You will be given a list of "
    "recent headlines: general AI news, and separately AI policy/political "
    "news. Write a 3-5 sentence plain-text overview of the most notable "
    "themes in this batch, for a busy reader who wants the gist before the "
    "full list of links below. Do not invent facts, numbers, or events beyond "
    "what the headlines imply. Plain prose only -- no markdown, no headers, "
    "no bullet points."
)

DEFAULT_OVERVIEW = "Here's what's new across AI news and policy since the last update \u2014 full list below."

# Structured overview (the "generate" step). The email template is fixed, so the
# model is forced to return raw JSON with a fixed schema; whatever provider wrote
# it, the email renders identically. Fall back to DEFAULT_OVERVIEW if a provider
# returns unrunnable prose or invalid JSON.
OVERVIEW_SYSTEM_PROMPT = (
    "You are a terse AI-industry news editor. You will be given a batch of "
    "recent AI headlines (general news, policy/politics, lab updates, lab "
    "tweets). Write a short summary of the most notable themes for a busy "
    "reader. Do not invent facts, numbers, or events beyond what the headlines "
    "imply.\n"
    "Respond with ONLY raw JSON in EXACTLY this schema (no markdown fences, no "
    "prose outside the JSON):\n"
    '{"headline":"<one-line takeaway of the biggest theme>",'
    '"summary":"<3-5 sentence plain-text overview>",'
    '"top_themes":["<theme label>","<theme label>"]}\n'
    "Rules: headline and summary are plain prose with NO markdown and NO line "
    "breaks inside them; give 3 to 5 short uppercase-style theme labels."
)

# Verification step (same provider chain). Fixes cross-feed duplication: the same
# story covered by several outlets is kept once, and outright junk is dropped.
VERIFY_SYSTEM_PROMPT = (
    "You are a news verification editor. You are given a numbered batch of "
    "AI-news items, each line as: <index>: [<category>] <headline> (<source>) <snippet>\n"
    "Your jobs:\n"
    "1) GROUPINGS: indices that describe the SAME underlying story (including "
    "near-duplicates, e.g. rewrites or re-syndication) belong together.\n"
    "2) DROP: any item that is junk, off-topic, machine-generated spam, "
    "empty/placeholder, or not a real news item.\n"
    "Respond with ONLY raw JSON (no markdown fences, no prose) in EXACTLY "
    "this schema, listing indices as integer arrays:\n"
    '{"groups":[[0,3],[1]],"drop":[5]}\n'
    '"groups" is a list of index arrays, each array = one unique story; '
    '"drop" is a list of indices to remove entirely. Indices not mentioned '
    '"anywhere are kept unchanged."'
)

# Second job of the verify model: check a GENERATED overview against the source
# headlines it was based on, so no invented fact ever gets mailed out. The
# generate model writes; the verify model fact-checks; only clean text ships.
VERIFY_OVERVIEW_SYSTEM_PROMPT = (
    "You are a strict fact-checking editor. Below you will get the actual "
    "source headlines an AI overview was based on, and the overview itself "
    "(headline, summary, top themes). Check ONLY for:\n"
    "1) HALLUCINATION: does the overview state any concrete fact, name, number, "
    "or event that is NOT supported by the source headlines?\n"
    "2) CONTRADICTION: does the overview headline contradict its summary, or do "
    "the top themes contradict either?\n"
    "Do NOT demand completeness -- omitting stories is fine. Respond with ONLY "
    'raw JSON in EXACTLY this schema: {"ok": true, "issues": []} or '
    '{"ok": false, "issues": ["short description of each problem"]}'
)


def build_user_prompt(
    general: List[Dict],
    policy: List[Dict],
    tweets: List[Dict] = None,
    labs: List[Dict] = None,
) -> str:
    tweets = tweets or []
    labs = labs or []
    lines = ["GENERAL AI NEWS:"]
    lines += [f"- {a['title']} ({a['source']})" for a in general] or ["(none)"]
    lines.append("")
    lines.append("AI POLICY / POLITICAL NEWS:")
    lines += [f"- {a['title']} ({a['source']})" for a in policy] or ["(none)"]
    lines.append("")
    lines.append("AI LAB UPDATES:")
    lines += [f"- {a['title']} ({a['source']})" for a in labs] or ["(none)"]
    lines.append("")
    lines.append("AI LAB TWEETS:")
    lines += [f"- {a['title']} ({a['source']})" for a in tweets] or ["(none)"]
    return "\n".join(lines)


def _call_openai_compatible(
    base_url: str, api_key: str, model: str, system: str, user_prompt: str
) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=90)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1200,
        temperature=0.3,
    )
    return (resp.choices[0].message.content or "").strip()


def _call_anthropic(model: str, system: str, user_prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=60)
    resp = client.messages.create(
        model=model,
        max_tokens=1200,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text").strip()


Provider = Tuple[str, Callable[[str, str], str]]


def _build_ollama(model: Optional[str] = None) -> Optional[Provider]:
    model = model or OLLAMA_MODEL
    return (
        "ollama",
        lambda s, p: _call_openai_compatible(OLLAMA_BASE_URL, OLLAMA_API_KEY, model, s, p),
    )


def _build_opencode_zen(model: Optional[str] = None) -> Optional[Provider]:
    if not OPENCODE_API_KEY:
        return None
    model = model or OPENCODE_MODEL
    return (
        "opencode_zen",
        lambda s, p: _call_openai_compatible(OPENCODE_BASE_URL, OPENCODE_API_KEY, model, s, p),
    )


def _build_gemini(model: Optional[str] = None) -> Optional[Provider]:
    if not GEMINI_API_KEY:
        return None
    model = model or GEMINI_MODEL
    return (
        "gemini",
        lambda s, p: _call_openai_compatible(GEMINI_BASE_URL, GEMINI_API_KEY, model, s, p),
    )


def _build_huggingface(model: Optional[str] = None) -> Optional[Provider]:
    if not HUGGINGFACE_API_KEY:
        return None
    model = model or HUGGINGFACE_MODEL
    return (
        "huggingface",
        lambda s, p: _call_openai_compatible(HUGGINGFACE_BASE_URL, HUGGINGFACE_API_KEY, model, s, p),
    )


def _build_groq(model: Optional[str] = None) -> Optional[Provider]:
    if not GROQ_API_KEY:
        return None
    model = model or GROQ_MODEL
    return (
        "groq",
        lambda s, p: _call_openai_compatible(GROQ_BASE_URL, GROQ_API_KEY, model, s, p),
    )


def _build_cerebras(model: Optional[str] = None) -> Optional[Provider]:
    if not CEREBRAS_API_KEY:
        return None
    model = model or CEREBRAS_MODEL
    return (
        "cerebras",
        lambda s, p: _call_openai_compatible(CEREBRAS_BASE_URL, CEREBRAS_API_KEY, model, s, p),
    )


def _build_nim(model: Optional[str] = None) -> Optional[Provider]:
    if not NIM_API_KEY:
        return None
    model = model or NIM_MODEL
    return (
        "nim",
        lambda s, p: _call_openai_compatible(NIM_BASE_URL, NIM_API_KEY, model, s, p),
    )


def _build_openai(model: Optional[str] = None) -> Optional[Provider]:
    if not OPENAI_API_KEY:
        return None
    model = model or OPENAI_MODEL
    return (
        "openai",
        lambda s, p: _call_openai_compatible("https://api.openai.com/v1", OPENAI_API_KEY, model, s, p),
    )


def _build_anthropic(model: Optional[str] = None) -> Optional[Provider]:
    if not ANTHROPIC_API_KEY:
        return None
    model = model or ANTHROPIC_MODEL
    return ("anthropic", lambda s, p: _call_anthropic(model, s, p))


_BUILDERS: Dict[str, Callable[[Optional[str]], Optional[Provider]]] = {
    "ollama": _build_ollama,
    "opencode_zen": _build_opencode_zen,
    "gemini": _build_gemini,
    "huggingface": _build_huggingface,
    "groq": _build_groq,
    "cerebras": _build_cerebras,
    "nim": _build_nim,
    "openai": _build_openai,
    "anthropic": _build_anthropic,
}


def available_providers(chain: List[str] = None) -> List[Provider]:
    """Return (name, callable) pairs for a chain, in order.

    `chain` entries may be a provider name or `provider@model` (to pin a
    specific model for this task). Defaults to the global PROVIDER_CHAIN.
    """
    from src.config import PROVIDER_CHAIN as DEFAULT_CHAIN

    if chain is None:
        chain = DEFAULT_CHAIN
    providers: List[Provider] = []
    for token in chain:
        name, _, model = token.partition("@")
        name = name.strip().lower()
        model_override = model.strip() or None
        builder = _BUILDERS.get(name)
        if builder is None:
            print(f"[llm] unknown provider '{name}' in chain -- skipping")
            continue
        built = builder(model_override)
        if built is not None:
            providers.append(built)
    return providers


def _extract_json(text: str) -> dict:
    """Pull the first balanced JSON object out of a model reply.

    Tolerant of markdown fences and of trailing prose after the JSON: we scan
    every candidate closing brace and take the first substring that parses.
    """
    if not text:
        raise ValueError("empty LLM response")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text, count=1).strip()
        text = re.sub(r"```$", "", text, count=1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    for i in range(len(text) - 1, start, -1):
        if text[i] == "}":
            try:
                return json.loads(text[start : i + 1])
            except (json.JSONDecodeError, ValueError):
                continue
    raise ValueError("no parseable JSON object in model response")


def _truncate_snippet(text: str, limit: int = 160) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "\u2026"


def _run_chain(system: str, user_prompt: str, chain: List[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Try every provider in `chain` in order; return (text, provider_name)."""
    providers = available_providers(chain)
    if not providers:
        print("[llm] no LLM provider is configured/available in this task's chain -- using default")
    for name, call in providers:
        try:
            text = call(system, user_prompt)
            if text:
                return text, name
        except Exception as exc:  # noqa: BLE001 -- failing provider should never block the email
            print(f"[llm] provider '{name}' failed: {exc} -- trying next")
    return None, None


def dedupe_news(articles: List[Dict]) -> List[Dict]:
    """LLM verification pass: merge same-story near-duplicates and drop junk.

    Only *which* items survive changes -- the surviving dicts are the original
    feed objects (headline/link/source untouched). Representative per group is
    the hottest-previously-scored item, so a major multi-outlet story stays hot.
    Fails open: any LLM error returns the input unchanged.
    """
    if not articles:
        return articles
    lines = [
        f"{i}: [{a.get('category')}] {a.get('title', '')} ({a.get('source', '')}) {_truncate_snippet(a.get('summary', ''))}"
        for i, a in enumerate(articles)
    ]
    user_prompt = (
        "Here is the numbered batch of AI-news items "
        "(<index>: [<category>] <headline> (<source>) <snippet>):\n\n"
        + "\n".join(lines)
        + "\n\nReturn the verification JSON now."
    )
    text, name = _run_chain(VERIFY_SYSTEM_PROMPT, user_prompt, chain=LLM_VERIFY_PROVIDERS)
    if not text:
        print("[llm] verification passed through unchanged (no provider answer)")
        return articles
    try:
        verdict = _extract_json(text)
    except Exception as exc:
        print(f"[llm] verification JSON parse failed ({name}): {exc} -- keeping all items")
        return articles

    def _ints(value) -> List[int]:
        out = []
        for v in value or []:
            if isinstance(v, bool) or v is None:
                continue
            try:
                iv = int(v)
            except (TypeError, ValueError):
                continue
            if 0 <= iv < len(articles):
                out.append(iv)
        return out

    keep = set(range(len(articles)))
    for group in verdict.get("groups") or []:
        idx = _ints(group)
        if not idx:
            continue
        representative = max(idx, key=lambda i: (articles[i].get("heat", 0), articles[i].get("published_ts", 0), -i))
        for i in idx:
            if i != representative:
                keep.discard(i)
    for i in _ints(verdict.get("drop") or []):
        keep.discard(i)

    kept = [a for i, a in enumerate(articles) if i in keep]
    removed = len(articles) - len(kept)
    if removed > len(articles) * 0.5:
        print(
            f"[llm] verification by {name} removed {removed}/{len(articles)} item(s) -- "
            "suspicious over-merge, keeping all items unchanged"
        )
        return articles
    print(f"[llm] verified by {name}: kept {len(kept)}/{len(articles)} item(s) (removed {removed} dup/junk)")
    return kept


# Markup/code that must never reach the email body. The model is told to write
# plain text, but if it leaks HTML tags, markdown, backticks or JSON-ish
# fragments, the overview FAILS validation and is regenerated (never sent).
_MARKUP_PATTERNS = [
    re.compile(r"<[a-z][^>]*>", re.I),  # HTML/XML tags
    re.compile(r"</[a-z][^>]*>", re.I),
    re.compile(r"```"),                # code fences
    re.compile(r"`[^`]+`"),            # inline code / backticks
    re.compile(r"!\[.*?\]\(.*?\)"),    # markdown image
    re.compile(r"\[[^\]]*\]\(https?://[^)]+\)"),  # markdown link
    re.compile(r"^\s*#{1,6}\s+", re.M),  # markdown heading
    re.compile(r"\*\*[^*\n]+\*\*"),    # bold
    re.compile(r'"[a-zA-Z_]+"\s*:'),    # JSON-style key
]

MAX_OVERVIEW_ATTEMPTS = 3  # regenerate up to this many times before falling back


def _markup_problems(text: str) -> List[str]:
    if not text:
        return []
    problems = []
    for pat in _MARKUP_PATTERNS:
        m = pat.search(text)
        if m:
            problems.append(pat.pattern)
    if "\n" in text:
        problems.append("line break")
    return problems


def overview_problems(overview: Dict) -> List[str]:
    """Return a list of format violations in an LLM overview, [] if it's clean."""
    problems = []
    for field in ("headline", "summary"):
        for p in _markup_problems(str(overview.get(field) or "")):
            problems.append(f"{field}: {p}")
    for t in overview.get("themes", []):
        for p in _markup_problems(str(t)):
            problems.append(f"theme: {p}")
    return problems


def _source_lines(
    general: List[Dict],
    policy: List[Dict],
    tweets: List[Dict],
    labs: List[Dict],
) -> List[str]:
    lines = []
    for group in (general, policy, labs, tweets):
        lines += [f"- {a.get('title', '')} ({a.get('source', '')})" for a in group]
    return lines or ["(no source headlines)"]


def verify_overview(overview: Dict, source_lines: List[str]) -> List[str]:
    """Ask the verify model to fact-check a generated overview against the
    headlines it was based on. Returns a (possibly empty) list of issues.
    Fails open: any verifier error => the overview is accepted ([]).
    """
    if not overview.get("summary"):
        return []
    user = (
        "SOURCE HEADLINES:\n" + "\n".join(source_lines) + "\n\nMODEL OVERVIEW:\n"
        f"headline: {overview.get('headline')}\n"
        f"summary: {overview.get('summary')}\n"
        f"top themes: {', '.join(overview.get('themes', []))}\n\n"
        "Return the fact-check JSON now."
    )
    text, name = _run_chain(VERIFY_OVERVIEW_SYSTEM_PROMPT, user, chain=LLM_VERIFY_PROVIDERS)
    if not text:
        return []
    try:
        verdict = _extract_json(text)
        if not verdict.get("ok", True):
            issues = [str(i).strip() for i in (verdict.get("issues") or []) if str(i).strip()]
            print(f"[llm] overview flagged by verifier ({name}): {'; '.join(issues) or 'unspecified issues'}")
            return issues
    except Exception as exc:
        print(f"[llm] overview fact-check reply unparsable ({name}): {exc} -- accepting")
    return []


def summarize_digest(
    general: List[Dict],
    policy: List[Dict],
    tweets: List[Dict] = None,
    labs: List[Dict] = None,
) -> Dict:
    """Generate a structured overview; returns {"headline", "summary", "themes"}.

    Two independent gates before anything is mailed:
    1. format check -- the output may not contain HTML/markdown/code;
    2. fact-check -- the verify model confirms the overview doesn't invent
       anything beyond the source headlines.
    On any failure the overview is regenerated (up to MAX_OVERVIEW_ATTEMPTS);
    a fixed plain-text DEFAULT_OVERVIEW is the last resort, so unclean output
    can never reach your inbox. The rendered email layout is identical
    whichever provider wrote the text (fixed template in mailer.py).
    """
    user_prompt = build_user_prompt(general, policy, tweets, labs)
    source_lines = _source_lines(general, policy, tweets or [], labs or [])
    for attempt in range(1, MAX_OVERVIEW_ATTEMPTS + 1):
        correction = (
            "\n\nYour previous answer FAILED validation (raw HTML tag, markdown, "
            "backticks, a line break, or an invented fact was flagged). Reply with "
            "ONLY the raw JSON object again; every field must be plain prose, "
            "faithful to the source headlines, with NO markup."
            if attempt > 1
            else ""
        )
        text, name = _run_chain(OVERVIEW_SYSTEM_PROMPT, user_prompt + correction, chain=LLM_OVERVIEW_PROVIDERS)
        if not text:
            break
        try:
            data = _extract_json(text)
            headline = str(data.get("headline") or "").strip()
            summary = str(data.get("summary") or "").strip()
            themes = [str(t).strip() for t in (data.get("top_themes") or []) if str(t).strip()]
            overview = {"headline": headline, "summary": summary, "themes": themes[:5]}
            if not summary:
                print(f"[llm] overview attempt {attempt}: empty summary from {name} -- regenerating")
                continue
            problems = overview_problems(overview)
            if problems:
                print(
                    f"[llm] overview by {name} FAILED format check: {'; '.join(problems)} "
                    f"-- regenerating (attempt {attempt}/{MAX_OVERVIEW_ATTEMPTS})"
                )
                continue
            issues = verify_overview(overview, source_lines)
            if issues:
                print(f"[llm] overview by {name} FAILED fact-check -- regenerating (attempt {attempt}/{MAX_OVERVIEW_ATTEMPTS})")
                continue
            print(f"[llm] overview written and PASSED both checks by {name}")
            return overview
        except Exception as exc:
            print(f"[llm] overview attempt {attempt}: JSON parse failed ({name}): {exc} -- regenerating")
    print("[llm] using default overview format (no clean answer after retries)")
    return {"headline": "", "summary": DEFAULT_OVERVIEW, "themes": []}


def check_providers() -> List[Dict]:
    """Test each configured provider with a trivial prompt; used by `run.py --check-llm`."""
    results: List[Dict] = []
    providers = available_providers()
    if not providers:
        print("[llm] no providers are configured. Add API keys to .env (e.g. GEMINI_API_KEY, OPENCODE_API_KEY, HUGGINGFACE_API_KEY) or start Ollama.")
        return results
    for name, call in providers:
        try:
            text = call(SYSTEM_PROMPT, "Reply with exactly this word: OK")
            results.append({"provider": name, "ok": bool(text), "error": "" if text else "empty response"})
        except Exception as exc:  # noqa: BLE001
            results.append({"provider": name, "ok": False, "error": str(exc)[:200]})
    return results