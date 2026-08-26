"""Safe LLM capacity/follow-up provider helpers for Trade Brain Deep Analysis.

This module is credential-blind: it only checks whether alternate provider credentials
exist in the local process environment. It never returns, logs, or persists API keys.

It also provides a small process-wide Groq capacity governor. The governor is advisory
capacity control only: it never changes trading policy or broker permissions.
"""

from __future__ import annotations

from collections import deque
import math
import os
import re
import threading
import time
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


def _parse_duration_seconds(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    total = 0.0
    matched = False
    for amount, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(ms|h|m|s)", text):
        matched = True
        number = float(amount)
        total += number / 1000.0 if unit == "ms" else number * {"s": 1, "m": 60, "h": 3600}[unit]
    return total if matched else None


def retry_after_seconds(exc: BaseException, *, default: float = 20.0) -> float:
    """Read Retry-After / Groq reset hints from common OpenAI-compatible errors."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        for key in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
            try:
                parsed = _parse_duration_seconds(headers.get(key))
            except Exception:
                parsed = None
            if parsed is not None and parsed > 0:
                return parsed
    text = str(exc)
    for pattern in (
        r"try again in\s+([0-9.]+\s*(?:ms|s|m|h)(?:\s*[0-9.]+\s*(?:ms|s|m|h))*)",
        r"retry[- ]?after[^0-9]*([0-9.]+\s*(?:ms|s|m|h)(?:\s*[0-9.]+\s*(?:ms|s|m|h))*)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            parsed = _parse_duration_seconds(match.group(1))
            if parsed is not None and parsed > 0:
                return parsed
    return max(0.0, default)


class GroqFreeTierGovernor:
    """Cooperatively pace Groq calls under a rolling soft token-per-minute budget."""

    def __init__(
        self,
        *,
        tpm_budget: int = 7600,
        window_seconds: float = 60.0,
        output_reserve: int = 1200,
        min_request_interval: float = 1.0,
    ) -> None:
        self.tpm_budget = max(1000, int(tpm_budget))
        self.window_seconds = max(1.0, float(window_seconds))
        self.output_reserve = max(0, int(output_reserve))
        self.min_request_interval = max(0.0, float(min_request_interval))
        self._events: deque[tuple[float, int]] = deque()
        self._last_request_at: float | None = None
        self._lock = threading.Lock()

    def _estimate(self, request: Any) -> int:
        # Dependency-free conservative estimate; provider 429 remains authoritative.
        estimated = math.ceil(len(str(request)) / 4.0) + self.output_reserve
        return min(max(1, estimated), max(1, self.tpm_budget - 200))

    def reserve(self, request: Any) -> dict[str, Any]:
        requested = self._estimate(request)
        waited = 0.0
        while True:
            wait_for = 0.0
            with self._lock:
                now = time.monotonic()
                cutoff = now - self.window_seconds
                while self._events and self._events[0][0] <= cutoff:
                    self._events.popleft()
                used = sum(tokens for _, tokens in self._events)
                if self._last_request_at is not None:
                    wait_for = max(wait_for, self.min_request_interval - (now - self._last_request_at))
                if used + requested > self.tpm_budget and self._events:
                    wait_for = max(wait_for, self._events[0][0] + self.window_seconds - now + 0.05)
                if wait_for <= 0:
                    self._events.append((now, requested))
                    self._last_request_at = now
                    return {
                        "estimated_tokens": requested,
                        "waited_seconds": round(waited, 3),
                        "soft_tpm_budget": self.tpm_budget,
                    }
            sleep_for = max(0.01, wait_for)
            time.sleep(sleep_for)
            waited += sleep_for

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._last_request_at = None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def groq_governor_enabled() -> bool:
    raw = os.getenv("TRADEBRAIN_GROQ_GOVERNOR", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


GLOBAL_GROQ_GOVERNOR = GroqFreeTierGovernor(
    tpm_budget=int(_env_float("TRADEBRAIN_GROQ_SOFT_TPM", 7600)),
    output_reserve=int(_env_float("TRADEBRAIN_GROQ_OUTPUT_RESERVE", 1200)),
    min_request_interval=_env_float("TRADEBRAIN_GROQ_MIN_INTERVAL_SECONDS", 1.0),
)


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
