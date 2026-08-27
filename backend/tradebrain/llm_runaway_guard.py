"""Emergency LLM runaway/billing circuit breaker for Trade Brain.

This is deliberately NOT a normal usage quota. Thresholds sit far above expected SHALLOW,
MEDIUM, and DEEP BSE analyses and exist only to stop accidental loops, recursive graph bugs,
or repeated retry storms from making unbounded paid-provider calls.

The guard is process-local and credential-blind. It never changes trading policy and never
authorizes an order. Crossing a tripwire fails the AI run closed as WAIT / NO TRADE.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import os
import threading
import time
from typing import Any


class LLMRunawayGuardError(RuntimeError):
    """Raised before another paid-provider call when an emergency tripwire is crossed."""


@dataclass
class _RunState:
    started_at: float
    calls: int = 0
    tokens: int = 0
    failures: int = 0
    providers: set[str] = field(default_factory=set)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def estimate_input_tokens(payload: Any) -> int:
    """Conservative dependency-free input estimate used only for pre-call tripwires."""
    return max(1, math.ceil(len(str(payload)) / 3.5))


def _response_total_tokens(response: Any) -> int | None:
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
        for candidate in (metadata.get("token_usage"), metadata.get("usage")):
            if not isinstance(candidate, dict):
                continue
            try:
                total = int(candidate.get("total_tokens") or candidate.get("total_token_count") or 0)
            except (TypeError, ValueError):
                total = 0
            if total > 0:
                return total
            try:
                input_tokens = int(candidate.get("prompt_tokens") or candidate.get("input_tokens") or 0)
                output_tokens = int(candidate.get("completion_tokens") or candidate.get("output_tokens") or 0)
            except (TypeError, ValueError):
                input_tokens = output_tokens = 0
            if input_tokens + output_tokens > 0:
                return input_tokens + output_tokens
    return None


class LLMRunawayGuard:
    """Generous per-analysis and rolling-hour emergency circuit breaker."""

    def __init__(
        self,
        *,
        max_calls_per_run: int = 160,
        max_tokens_per_run: int = 1_500_000,
        max_runtime_seconds: float = 2700.0,
        max_input_tokens_per_call: int = 120_000,
        max_calls_per_hour: int = 800,
        max_tokens_per_hour: int = 8_000_000,
        monotonic_fn=time.monotonic,
    ) -> None:
        self.max_calls_per_run = max(10, int(max_calls_per_run))
        self.max_tokens_per_run = max(100_000, int(max_tokens_per_run))
        self.max_runtime_seconds = max(300.0, float(max_runtime_seconds))
        self.max_input_tokens_per_call = max(10_000, int(max_input_tokens_per_call))
        self.max_calls_per_hour = max(100, int(max_calls_per_hour))
        self.max_tokens_per_hour = max(500_000, int(max_tokens_per_hour))
        self._monotonic = monotonic_fn
        self._runs: dict[str, _RunState] = {}
        self._hourly_calls: deque[float] = deque()
        self._hourly_tokens: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - 3600.0
        while self._hourly_calls and self._hourly_calls[0] <= cutoff:
            self._hourly_calls.popleft()
        while self._hourly_tokens and self._hourly_tokens[0][0] <= cutoff:
            self._hourly_tokens.popleft()
        # Avoid retaining old completed/abandoned run ids forever.
        stale = [run_id for run_id, state in self._runs.items() if now - state.started_at > 7200.0]
        for run_id in stale:
            self._runs.pop(run_id, None)

    def before_call(self, run_id: str | None, *, provider: str, model: str, payload: Any) -> None:
        """Reserve one provider call or raise before money can continue to be spent."""
        if not run_id:
            return
        estimated_input = estimate_input_tokens(payload)
        now = self._monotonic()
        with self._lock:
            self._prune(now)
            state = self._runs.setdefault(str(run_id), _RunState(started_at=now))
            elapsed = now - state.started_at
            hourly_tokens = sum(tokens for _, tokens in self._hourly_tokens)

            reason = None
            if elapsed > self.max_runtime_seconds:
                reason = f"AI runtime exceeded {round(self.max_runtime_seconds / 60)} minutes"
            elif state.calls >= self.max_calls_per_run:
                reason = f"provider calls exceeded {self.max_calls_per_run} for one analysis"
            elif state.tokens + estimated_input > self.max_tokens_per_run:
                reason = f"analysis token usage approached {self.max_tokens_per_run:,} tokens"
            elif estimated_input > self.max_input_tokens_per_call:
                reason = f"single prompt estimated above {self.max_input_tokens_per_call:,} input tokens"
            elif len(self._hourly_calls) >= self.max_calls_per_hour:
                reason = f"process-wide provider calls exceeded {self.max_calls_per_hour} in one hour"
            elif hourly_tokens + estimated_input > self.max_tokens_per_hour:
                reason = f"process-wide token usage approached {self.max_tokens_per_hour:,} tokens in one hour"

            if reason:
                raise LLMRunawayGuardError(
                    "AI_RUNAWAY_GUARD / WAIT: emergency billing circuit breaker stopped another "
                    f"provider call because {reason}. This threshold is intentionally far above "
                    "normal DEEP analysis usage. Trade Brain remains WAIT / NO TRADE."
                )

            state.calls += 1
            state.providers.add(str(provider or "unknown").lower())
            self._hourly_calls.append(now)

    def after_response(self, run_id: str | None, response: Any) -> int | None:
        """Record actual provider tokens after a successful response."""
        if not run_id:
            return None
        actual = _response_total_tokens(response)
        if not actual:
            return None
        now = self._monotonic()
        with self._lock:
            self._prune(now)
            state = self._runs.setdefault(str(run_id), _RunState(started_at=now))
            state.tokens += max(1, int(actual))
            self._hourly_tokens.append((now, max(1, int(actual))))
        return actual

    def after_failure(self, run_id: str | None) -> None:
        if not run_id:
            return
        now = self._monotonic()
        with self._lock:
            self._prune(now)
            state = self._runs.setdefault(str(run_id), _RunState(started_at=now))
            state.failures += 1

    def snapshot(self, run_id: str | None = None) -> dict[str, Any]:
        now = self._monotonic()
        with self._lock:
            self._prune(now)
            hourly_tokens = sum(tokens for _, tokens in self._hourly_tokens)
            result: dict[str, Any] = {
                "limits": {
                    "max_calls_per_run": self.max_calls_per_run,
                    "max_tokens_per_run": self.max_tokens_per_run,
                    "max_runtime_seconds": self.max_runtime_seconds,
                    "max_input_tokens_per_call": self.max_input_tokens_per_call,
                    "max_calls_per_hour": self.max_calls_per_hour,
                    "max_tokens_per_hour": self.max_tokens_per_hour,
                },
                "rolling_hour": {
                    "calls": len(self._hourly_calls),
                    "tokens": hourly_tokens,
                },
                "trade_authorization": False,
                "order_execution_allowed": False,
            }
            if run_id and str(run_id) in self._runs:
                state = self._runs[str(run_id)]
                result["run"] = {
                    "run_id": str(run_id),
                    "calls": state.calls,
                    "tokens": state.tokens,
                    "failures": state.failures,
                    "elapsed_seconds": round(max(0.0, now - state.started_at), 3),
                    "providers": sorted(state.providers),
                }
            return result

    def reset(self) -> None:
        with self._lock:
            self._runs.clear()
            self._hourly_calls.clear()
            self._hourly_tokens.clear()


GLOBAL_LLM_RUNAWAY_GUARD = LLMRunawayGuard(
    max_calls_per_run=_env_int("TRADEBRAIN_LLM_MAX_CALLS_PER_RUN", 160),
    max_tokens_per_run=_env_int("TRADEBRAIN_LLM_MAX_TOKENS_PER_RUN", 1_500_000),
    max_runtime_seconds=_env_float("TRADEBRAIN_LLM_MAX_RUNTIME_SECONDS", 2700.0),
    max_input_tokens_per_call=_env_int("TRADEBRAIN_LLM_MAX_INPUT_TOKENS_PER_CALL", 120_000),
    max_calls_per_hour=_env_int("TRADEBRAIN_LLM_MAX_CALLS_PER_HOUR", 800),
    max_tokens_per_hour=_env_int("TRADEBRAIN_LLM_MAX_TOKENS_PER_HOUR", 8_000_000),
)
