"""LLM provider registry with automatic failover.

Each provider is a small (name, callable) pair. `summarize_digest()` walks the
configured chain in order and stops at the first provider that answers; any
provider that raises (bad key, quota, outage) is logged and skipped so the next
provider gets a chance. Add new providers here -- they are picked up
automatically as long as they follow the builder pattern below.
"""

from typing import Callable, Dict, List, Optional, Tuple

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    HUGGINGFACE_API_KEY,
    HUGGINGFACE_BASE_URL,
    HUGGINGFACE_MODEL,
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


def _call_openai_compatible(base_url: str, api_key: str, model: str, user_prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=90)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=800,
        temperature=0.4,
    )
    return (resp.choices[0].message.content or "").strip()


def _call_anthropic(model: str, user_prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=60)
    resp = client.messages.create(
        model=model,
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text").strip()


Provider = Tuple[str, Callable[[str], str]]


def _build_ollama() -> Optional[Provider]:
    return ("ollama", lambda p: _call_openai_compatible(OLLAMA_BASE_URL, OLLAMA_API_KEY, OLLAMA_MODEL, p))


def _build_opencode_zen() -> Optional[Provider]:
    if not OPENCODE_API_KEY:
        return None
    return ("opencode_zen", lambda p: _call_openai_compatible(OPENCODE_BASE_URL, OPENCODE_API_KEY, OPENCODE_MODEL, p))


def _build_gemini() -> Optional[Provider]:
    if not GEMINI_API_KEY:
        return None
    return ("gemini", lambda p: _call_openai_compatible(GEMINI_BASE_URL, GEMINI_API_KEY, GEMINI_MODEL, p))


def _build_huggingface() -> Optional[Provider]:
    if not HUGGINGFACE_API_KEY:
        return None
    return ("huggingface", lambda p: _call_openai_compatible(HUGGINGFACE_BASE_URL, HUGGINGFACE_API_KEY, HUGGINGFACE_MODEL, p))


def _build_openai() -> Optional[Provider]:
    if not OPENAI_API_KEY:
        return None
    return ("openai", lambda p: _call_openai_compatible("https://api.openai.com/v1", OPENAI_API_KEY, OPENAI_MODEL, p))


def _build_anthropic() -> Optional[Provider]:
    if not ANTHROPIC_API_KEY:
        return None
    return ("anthropic", lambda p: _call_anthropic(ANTHROPIC_MODEL, p))


_BUILDERS: Dict[str, Callable[[], Optional[Provider]]] = {
    "ollama": _build_ollama,
    "opencode_zen": _build_opencode_zen,
    "gemini": _build_gemini,
    "huggingface": _build_huggingface,
    "openai": _build_openai,
    "anthropic": _build_anthropic,
}


def available_providers() -> List[Provider]:
    """Return (name, callable) pairs for every configured provider, in chain order."""
    from src.config import PROVIDER_CHAIN

    providers: List[Provider] = []
    for name in PROVIDER_CHAIN:
        builder = _BUILDERS.get(name)
        if builder is None:
            continue
        built = builder()
        if built is not None:
            providers.append(built)
    return providers


def summarize_digest(
    general: List[Dict],
    policy: List[Dict],
    tweets: List[Dict] = None,
    labs: List[Dict] = None,
) -> str:
    """Try every configured provider in order; return the first successful overview."""
    user_prompt = build_user_prompt(general, policy, tweets, labs)
    providers = available_providers()
    if not providers:
        print("[llm] no LLM provider is configured/available -- email will use the default overview")
    for name, call in providers:
        try:
            text = call(user_prompt)
            if text:
                print(f"[llm] overview written by {name}")
                return text
        except Exception as exc:  # noqa: BLE001 -- failing provider should never block the email
            print(f"[llm] provider '{name}' failed: {exc} -- trying next")
    return "Here's what's new across AI news and policy since the last update — full list below."


def check_providers() -> List[Dict]:
    """Test each configured provider with a trivial prompt; used by `run.py --check-llm`."""
    results: List[Dict] = []
    providers = available_providers()
    if not providers:
        print("[llm] no providers are configured. Add API keys to .env (e.g. GEMINI_API_KEY, OPENCODE_API_KEY, HUGGINGFACE_API_KEY) or start Ollama.")
        return results
    for name, call in providers:
        try:
            text = call("Reply with exactly this word: OK")
            results.append({"provider": name, "ok": bool(text), "error": "" if text else "empty response"})
        except Exception as exc:  # noqa: BLE001
            results.append({"provider": name, "ok": False, "error": str(exc)[:200]})
    return results