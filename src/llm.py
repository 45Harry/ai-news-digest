"""Backwards-compatible import shim for the LLM writer agent.

New code should import from providers.py directly; this module re-exports the
same names so existing callers (and `from llm import ...`) keep working.
"""

from src.providers import (
    SYSTEM_PROMPT,
    available_providers,
    build_user_prompt,
    check_providers,
    summarize_digest,
)

__all__ = [
    "SYSTEM_PROMPT",
    "available_providers",
    "build_user_prompt",
    "check_providers",
    "summarize_digest",
]