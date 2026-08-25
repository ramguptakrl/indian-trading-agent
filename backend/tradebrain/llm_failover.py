"""Safe LLM capacity/follow-up provider helpers for Trade Brain Deep Analysis.

This module is credential-blind: it only checks whether alternate provider credentials
exist in the local process environment. It never returns, logs, or persists API keys.
"""

from __future__ import annotations

import os
from typing import Any

RETRYABLE_MARKERS = (
    "resource_exhausted",
    "resource has been exhausted",
    "rate limit",
    "rate_limit",
    "ratelimiterror",
    "quota",
    "too many requests",
    "429",
    "temporarily unavailable",
    "service unavailable",
    "server overloaded",
    "overloaded",
    "capacity",
    "503",
    "502",
    "504",
)


def is_retryable_llm_capacity_error(exc: BaseException) -> bool:
    """Return True only for provider capacity/quota/transient availability failures."""
    text = str(exc).lower()
    return any(marker in text for marker in RETRYABLE_MARKERS)


def get_capacity_fallback_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """Return one alternate provider config for a retryable capacity failure.

    Normal BSE architecture is Groq primary + Gemini verifier. Capacity failover remains
    symmetric so a user who explicitly selected Google can still fall back to Groq.
    Protected Trade Brain policy fields are copied unchanged.
    """
    provider = str(config.get("llm_provider") or "").strip().lower()
    fallback = dict(config)

    if provider == "groq" and (os.getenv("GOOGLE_API_KEY") or "").strip():
        fallback["llm_provider"] = "google"
        fallback["deep_think_llm"] = "gemini-3.6-flash"
        fallback["quick_think_llm"] = "gemini-3.6-flash"
        return fallback

    if provider == "google" and (os.getenv("GROQ_API_KEY") or "").strip():
        fallback["llm_provider"] = "groq"
        fallback["deep_think_llm"] = "openai/gpt-oss-20b"
        fallback["quick_think_llm"] = "openai/gpt-oss-20b"
        fallback["google_thinking_level"] = None
        return fallback

    return None


def get_material_verifier_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """Return Gemini verifier metadata when Groq is primary and Google is configured.

    The analysis runtime may use this only for material findings; it must not call the
    verifier for every market tick. The returned object contains no credential.
    """
    provider = str(config.get("llm_provider") or "").strip().lower()
    if provider != "groq" or not (os.getenv("GOOGLE_API_KEY") or "").strip():
        return None
    return {
        "provider": "google",
        "model": str(config.get("llm_verifier_model") or "gemini-3.6-flash"),
        "material_findings_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def public_capacity_error(exc: BaseException, *, fallback_available: bool) -> str:
    """Return a concise user-safe fail-closed message instead of an SDK error dump."""
    if fallback_available:
        return (
            "AI_UNAVAILABLE / WAIT: the primary AI provider hit a temporary quota/rate "
            "limit and the configured alternate provider also could not complete the "
            "analysis. Trade Brain remains WAIT / NO TRADE. Retry after the cooldown or "
            "review Settings > Models & Keys."
        )
    return (
        "AI_UNAVAILABLE / WAIT: the selected AI provider hit a temporary quota/rate "
        "limit and no configured alternate provider is currently available. Trade Brain "
        "remains WAIT / NO TRADE. Retry after the provider cooldown or review Settings > "
        "Models & Keys."
    )
