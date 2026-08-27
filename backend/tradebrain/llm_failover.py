"""Safe LLM capacity/follow-up provider helpers for Trade Brain Deep Analysis.

This module is credential-blind: it only checks whether alternate provider credentials
exist in the local process environment. It never returns, logs, or persists API keys.

It also provides a process-wide Groq free-tier capacity governor. The governor is advisory
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
    """Read Retry-After / provider reset hints from common capacity errors."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        lowered = {str(key).lower(): value for key, value in dict(headers).items()}
        for key in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
            parsed = _parse_duration_seconds(lowered.get(key))
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


def capacity_error_summary(exc: BaseException) -> str:
    """Return a credential-safe, human-readable capacity classification."""
    text = str(exc).lower()
    if any(marker in text for marker in (
        "per day", "per-day", "requests per day", "tokens per day", "daily quota",
        "rpd", "tpd",
    )):
        scope = "daily quota"
    elif any(marker in text for marker in (
        "per minute", "per-minute", "requests per minute", "tokens per minute", "rpm", "tpm",
    )):
        scope = "minute rate limit"
    elif "resource_exhausted" in text or "quota" in text or "429" in text or "rate limit" in text:
        scope = "quota/rate limit"
    elif any(marker in text for marker in ("503", "502", "504", "overloaded", "capacity")):
        scope = "temporary provider capacity"
    else:
        scope = "temporary provider capacity"

    delay = retry_after_seconds(exc, default=0.0)
    if delay > 0:
        if delay >= 120:
            retry = f"; retry hint ~{max(1, round(delay / 60))} min"
        else:
            retry = f"; retry hint ~{max(1, round(delay))} sec"
    else:
        retry = ""
    return f"{scope}{retry}"


def response_total_tokens(response: Any) -> int | None:
    """Extract actual provider token usage from common LangChain AIMessage metadata."""
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        for key in ("total_tokens", "total_token_count"):
            try:
                value = int(usage.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        try:
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
        except (TypeError, ValueError):
            input_tokens = output_tokens = 0
        if input_tokens + output_tokens > 0:
            return input_tokens + output_tokens

    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        candidates = [metadata.get("token_usage"), metadata.get("usage")]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for key in ("total_tokens", "total_token_count"):
                try:
                    value = int(candidate.get(key) or 0)
                except (TypeError, ValueError):
                    value = 0
                if value > 0:
                    return value
            try:
                prompt = int(candidate.get("prompt_tokens") or candidate.get("input_tokens") or 0)
                completion = int(candidate.get("completion_tokens") or candidate.get("output_tokens") or 0)
            except (TypeError, ValueError):
                prompt = completion = 0
            if prompt + completion > 0:
                return prompt + completion
    return None


def response_rate_limit_headers(response: Any) -> dict[str, Any]:
    """Return normalized provider rate headers when LangChain preserved them."""
    metadata = getattr(response, "response_metadata", None)
    if not isinstance(metadata, dict):
        return {}
    headers = metadata.get("headers")
    if not headers:
        return {}
    try:
        return {str(key).lower(): value for key, value in dict(headers).items()}
    except Exception:
        return {}


def _header_int(headers: dict[str, Any], key: str) -> int | None:
    try:
        value = int(float(str(headers.get(key, "")).strip()))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


class GroqFreeTierGovernor:
    """Cooperatively pace Groq calls under a rolling soft token-per-minute budget.

    Reservations are estimated before a request, then reconciled to actual provider usage
    after success. When Groq response headers are available, the governor also observes the
    account/project model limit, remaining token window and reset timing. Capacity-rejected
    requests are released so a 429 does not poison the local budget.
    """

    def __init__(
        self,
        *,
        tpm_budget: int = 6200,
        window_seconds: float = 60.0,
        output_reserve: int = 1000,
        min_request_interval: float = 1.25,
    ) -> None:
        self._configured_tpm_budget = max(1000, int(tpm_budget))
        self.tpm_budget = self._configured_tpm_budget
        self.window_seconds = max(1.0, float(window_seconds))
        self.output_reserve = max(0, int(output_reserve))
        self.min_request_interval = max(0.0, float(min_request_interval))
        self._events: deque[tuple[float, int, int]] = deque()
        self._last_request_at: float | None = None
        self._blocked_until: float = 0.0
        self._next_reservation_id = 1
        self._provider_limit_tokens: int | None = None
        self._provider_remaining_tokens: int | None = None
        self._provider_remaining_requests: int | None = None
        self._provider_reset_tokens_at: float = 0.0
        self._lock = threading.Lock()

    def _estimate(self, request: Any) -> int:
        estimated = math.ceil(len(str(request)) / 3.5) + self.output_reserve
        return min(max(1, estimated), max(1, self.tpm_budget - 200))

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] <= cutoff:
            self._events.popleft()
        if self._provider_reset_tokens_at and now >= self._provider_reset_tokens_at:
            self._provider_remaining_tokens = self._provider_limit_tokens
            self._provider_reset_tokens_at = 0.0

    def observe_headers(self, headers: Any) -> dict[str, Any]:
        """Observe Groq's model/project limit headers without exposing credentials."""
        try:
            normalized = {str(key).lower(): value for key, value in dict(headers or {}).items()}
        except Exception:
            return self.snapshot()

        hard_tpm = _header_int(normalized, "x-ratelimit-limit-tokens")
        remaining_tokens = _header_int(normalized, "x-ratelimit-remaining-tokens")
        remaining_requests = _header_int(normalized, "x-ratelimit-remaining-requests")
        reset_seconds = _parse_duration_seconds(normalized.get("x-ratelimit-reset-tokens"))

        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if hard_tpm and hard_tpm > 0:
                self._provider_limit_tokens = hard_tpm
                observed_soft = max(1000, int(hard_tpm * 0.78))
                self.tpm_budget = min(self._configured_tpm_budget, observed_soft)
            if remaining_tokens is not None:
                self._provider_remaining_tokens = remaining_tokens
            if remaining_requests is not None:
                self._provider_remaining_requests = remaining_requests
            if reset_seconds is not None and reset_seconds > 0:
                self._provider_reset_tokens_at = now + reset_seconds
            snapshot = self._snapshot_unlocked(now)
        return snapshot

    def observe_response(self, response: Any) -> dict[str, Any]:
        return self.observe_headers(response_rate_limit_headers(response))

    def observe_error(self, exc: BaseException) -> dict[str, Any]:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        return self.observe_headers(headers)

    def reserve(self, request: Any) -> dict[str, Any]:
        requested = self._estimate(request)
        waited = 0.0
        while True:
            wait_for = 0.0
            with self._lock:
                now = time.monotonic()
                self._prune(now)
                used = sum(tokens for _, tokens, _ in self._events)
                wait_for = max(wait_for, self._blocked_until - now)
                if self._last_request_at is not None:
                    wait_for = max(wait_for, self.min_request_interval - (now - self._last_request_at))
                if used + requested > self.tpm_budget and self._events:
                    wait_for = max(wait_for, self._events[0][0] + self.window_seconds - now + 0.10)
                if (
                    self._provider_remaining_tokens is not None
                    and self._provider_reset_tokens_at > now
                    and requested > self._provider_remaining_tokens
                ):
                    wait_for = max(wait_for, self._provider_reset_tokens_at - now + 0.10)
                if wait_for <= 0:
                    reservation_id = self._next_reservation_id
                    self._next_reservation_id += 1
                    self._events.append((now, requested, reservation_id))
                    self._last_request_at = now
                    if self._provider_remaining_tokens is not None and self._provider_reset_tokens_at > now:
                        self._provider_remaining_tokens = max(0, self._provider_remaining_tokens - requested)
                    return {
                        "reservation_id": reservation_id,
                        "estimated_tokens": requested,
                        "waited_seconds": round(waited, 3),
                        "soft_tpm_budget": self.tpm_budget,
                    }
            sleep_for = max(0.01, wait_for)
            time.sleep(sleep_for)
            waited += sleep_for

    def reconcile(self, reservation: dict[str, Any] | int | None, response: Any) -> int | None:
        """Replace an estimate with actual provider usage when metadata is available."""
        rid = reservation.get("reservation_id") if isinstance(reservation, dict) else reservation
        actual = response_total_tokens(response)
        if not rid or not actual:
            return actual
        actual = max(1, int(actual))
        with self._lock:
            for index, (timestamp, _tokens, event_id) in enumerate(self._events):
                if event_id == int(rid):
                    self._events[index] = (timestamp, actual, event_id)
                    break
        return actual

    def release(self, reservation: dict[str, Any] | int | None) -> None:
        """Release a provider-rejected reservation that did not complete."""
        rid = reservation.get("reservation_id") if isinstance(reservation, dict) else reservation
        if not rid:
            return
        with self._lock:
            self._events = deque(event for event in self._events if event[2] != int(rid))

    def impose_cooldown(self, seconds: float) -> None:
        """Apply provider reset timing process-wide so other agents do not stampede Groq."""
        delay = max(0.0, float(seconds))
        with self._lock:
            self._blocked_until = max(self._blocked_until, time.monotonic() + delay)

    def _snapshot_unlocked(self, now: float) -> dict[str, Any]:
        reset_remaining = max(0.0, self._provider_reset_tokens_at - now)
        return {
            "soft_tpm_budget": self.tpm_budget,
            "rolling_tokens": sum(tokens for _, tokens, _ in self._events),
            "reservations": len(self._events),
            "cooldown_remaining_seconds": round(max(0.0, self._blocked_until - now), 3),
            "provider_limit_tokens_per_minute": self._provider_limit_tokens,
            "provider_remaining_tokens": self._provider_remaining_tokens,
            "provider_remaining_requests_per_day": self._provider_remaining_requests,
            "provider_token_reset_seconds": round(reset_remaining, 3),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            return self._snapshot_unlocked(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._last_request_at = None
            self._blocked_until = 0.0
            self._provider_limit_tokens = None
            self._provider_remaining_tokens = None
            self._provider_remaining_requests = None
            self._provider_reset_tokens_at = 0.0
            self.tpm_budget = self._configured_tpm_budget


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def groq_governor_enabled() -> bool:
    raw = os.getenv("TRADEBRAIN_GROQ_GOVERNOR", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


GLOBAL_GROQ_GOVERNOR = GroqFreeTierGovernor(
    tpm_budget=int(_env_float("TRADEBRAIN_GROQ_SOFT_TPM", 6200)),
    output_reserve=int(_env_float("TRADEBRAIN_GROQ_OUTPUT_RESERVE", 1000)),
    min_request_interval=_env_float("TRADEBRAIN_GROQ_MIN_INTERVAL_SECONDS", 1.25),
)


def _google_fallback(config: dict[str, Any]) -> dict[str, Any]:
    fallback = dict(config)
    fallback["llm_provider"] = "google"
    fallback["deep_think_llm"] = "gemini-3.6-flash"
    fallback["quick_think_llm"] = "gemini-3.6-flash"
    fallback["google_thinking_level"] = (
        os.getenv("TRADEBRAIN_GEMINI_FALLBACK_THINKING_LEVEL", "minimal").strip()
        or None
    )
    return fallback


def _openai_fallback(config: dict[str, Any]) -> dict[str, Any]:
    fallback = dict(config)
    fallback["llm_provider"] = "openai"
    fallback["deep_think_llm"] = "gpt-5.6-terra"
    fallback["quick_think_llm"] = "gpt-5.6-luna"
    fallback["google_thinking_level"] = None
    return fallback


def get_capacity_fallback_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """Return one deterministic alternate-provider config for a retryable capacity failure.

    Preferred order for the paid-development setup is OpenAI primary -> Gemini fallback.
    When Google is primary, a configured OpenAI key is preferred over the constrained Groq
    free tier. Groq primary still uses Gemini first so existing installations remain compatible.
    """
    provider = str(config.get("llm_provider") or "").strip().lower()
    google_ready = bool((os.getenv("GOOGLE_API_KEY") or "").strip())
    openai_ready = bool((os.getenv("OPENAI_API_KEY") or "").strip())
    groq_ready = bool((os.getenv("GROQ_API_KEY") or "").strip())

    if provider == "openai" and google_ready:
        return _google_fallback(config)

    if provider == "groq" and google_ready:
        return _google_fallback(config)

    if provider == "google" and openai_ready:
        return _openai_fallback(config)

    if provider == "google" and groq_ready:
        fallback = dict(config)
        fallback["llm_provider"] = "groq"
        fallback["deep_think_llm"] = "openai/gpt-oss-20b"
        fallback["quick_think_llm"] = "openai/gpt-oss-20b"
        fallback["google_thinking_level"] = None
        return fallback

    return None


def get_material_verifier_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """Return Gemini verifier metadata when a non-Google primary and Google are configured."""
    provider = str(config.get("llm_provider") or "").strip().lower()
    if provider == "google" or not (os.getenv("GOOGLE_API_KEY") or "").strip():
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
    summary = capacity_error_summary(exc)
    if fallback_available:
        return (
            "AI_UNAVAILABLE / WAIT: the primary AI provider was capacity-limited and the "
            f"configured alternate provider also hit {summary}. Trade Brain remains WAIT / "
            "NO TRADE. This is provider capacity, not a trading-signal failure. "
            "Review Settings > Models & Keys if the provider test also fails."
        )
    return (
        f"AI_UNAVAILABLE / WAIT: the selected AI provider hit {summary} and no configured "
        "alternate provider is currently available. Trade Brain remains WAIT / NO TRADE. "
        "Review Settings > Models & Keys or retry after the provider reset."
    )
