"""Safe LLM capacity failover helpers for Trade Brain Deep Analysis.

This module is intentionally credential-blind: it only checks whether a fallback key is
present in the local process environment. It never returns, logs, or persists API keys.
"""

from __future__ import annotations

import os
from typing import Any

RETRYABLE_MARKERS = (
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "quota",
    "too many requests",
    "429",
    "temporarily unavailable",
    "service unavailable",
    "503",
)


def is_retryable_llm_capacity_error(exc: BaseException) -> bool:
    """Return True only for provider capacity/quota style failures."""
    text = str(exc).lower()
    return any(marker in text for marker in RETRYABLE_MARKERS)


def get_capacity_fallback_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """Return a one-shot Groq fallback config when Google capacity is exhausted.

    The fallback is deliberately narrow: Google Gemini -> Groq only, and only when a
    local GROQ_API_KEY is already configured. Protected Trade Brain policy fields are
    copied unchanged.
    """
    if str(config.get("llm_provider") or "").strip().lower() != "google":
        return None
    if not (os.getenv("GROQ_API_KEY") or "").strip():
        return None

    fallback = dict(config)
    fallback["llm_provider"] = "groq"
    fallback["deep_think_llm"] = "openai/gpt-oss-20b"
    fallback["quick_think_llm"] = "openai/gpt-oss-20b"
    # Provider-specific Gemini tuning must not leak into Groq.
    fallback["google_thinking_level"] = None
    return fallback


def public_capacity_error(exc: BaseException, *, fallback_available: bool) -> str:
    """Return a concise user-safe message instead of a provider SDK error dump."""
    if fallback_available:
        return (
            "The primary AI provider hit a temporary quota/rate limit and the alternate "
            "provider also could not complete the analysis. Please retry shortly or review "
            "Settings > Models & Keys."
        )
    return (
        "Google Gemini hit a temporary quota/rate limit. Configure and test Groq under "
        "Settings > Models & Keys for automatic failover, or retry after the provider's "
        "cooldown period."
    )
