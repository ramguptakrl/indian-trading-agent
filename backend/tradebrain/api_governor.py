"""Process-local read-only API pacing/backoff for Trade Brain.

This module deliberately governs data/research calls only. It contains no broker order
execution path. Rules are conservative ceilings intended to prevent noisy polling and
429 storms; callers may still choose to call *less* often when live WebSocket state is
fresh.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, Mapping


@dataclass(frozen=True)
class ApiBudgetRule:
    name: str
    min_interval_seconds: float
    max_retries: int = 3
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0


class ApiGovernor:
    """Thread-safe per-bucket pacing with Retry-After aware exponential backoff."""

    def __init__(
        self,
        rules: Mapping[str, ApiBudgetRule],
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.rules = dict(rules)
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self._random = random_fn
        self._lock = threading.Lock()
        self._last_call: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}
        self._calls: dict[str, int] = {}
        self._retries: dict[str, int] = {}

    def rule(self, bucket: str) -> ApiBudgetRule:
        if bucket not in self.rules:
            raise KeyError(f"Unknown API budget bucket: {bucket}")
        return self.rules[bucket]

    def wait_for_slot(self, bucket: str) -> float:
        rule = self.rule(bucket)
        waited = 0.0
        while True:
            with self._lock:
                now = self._monotonic()
                last = self._last_call.get(bucket)
                cooldown_until = self._cooldown_until.get(bucket, 0.0)
                spacing_until = (last + rule.min_interval_seconds) if last is not None else now
                ready_at = max(now, spacing_until, cooldown_until)
                delay = max(0.0, ready_at - now)
                if delay <= 0:
                    self._last_call[bucket] = now
                    self._calls[bucket] = self._calls.get(bucket, 0) + 1
                    return waited
            self._sleep(delay)
            waited += delay

    @staticmethod
    def _retry_after_seconds(headers: Mapping[str, str] | None) -> float | None:
        if not headers:
            return None
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is None:
            return None
        value = str(raw).strip()
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                return max(0.0, retry_at.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return None

    def register_retry(
        self,
        bucket: str,
        *,
        attempt: int,
        headers: Mapping[str, str] | None = None,
    ) -> float:
        rule = self.rule(bucket)
        explicit = self._retry_after_seconds(headers)
        if explicit is not None:
            delay = min(max(explicit, rule.min_interval_seconds), rule.max_backoff_seconds)
        else:
            exponential = rule.base_backoff_seconds * (2 ** max(0, attempt))
            jitter = 0.15 * exponential * self._random()
            delay = min(exponential + jitter, rule.max_backoff_seconds)
        with self._lock:
            now = self._monotonic()
            self._cooldown_until[bucket] = max(self._cooldown_until.get(bucket, 0.0), now + delay)
            self._retries[bucket] = self._retries.get(bucket, 0) + 1
        return delay

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "buckets": {
                    name: {
                        "min_interval_seconds": rule.min_interval_seconds,
                        "max_retries": rule.max_retries,
                        "calls": self._calls.get(name, 0),
                        "retries": self._retries.get(name, 0),
                    }
                    for name, rule in self.rules.items()
                },
                "order_execution_allowed": False,
            }


KITE_BUDGET_RULES = {
    # Quote REST calls are intentionally paced slowly because continuous BSE state
    # should normally come from the WebSocket plane instead of polling.
    "kite_quote": ApiBudgetRule("kite_quote", min_interval_seconds=1.05, max_retries=3),
    # Historical REST is paced below the documented 3 req/s ceiling.
    "kite_historical": ApiBudgetRule("kite_historical", min_interval_seconds=0.36, max_retries=3),
    # Instrument master is a low-frequency metadata call; one per second is ample.
    "kite_instruments": ApiBudgetRule("kite_instruments", min_interval_seconds=1.0, max_retries=2),
    "kite_other_read": ApiBudgetRule("kite_other_read", min_interval_seconds=0.5, max_retries=2),
}

KITE_API_GOVERNOR = ApiGovernor(KITE_BUDGET_RULES)


def kite_bucket_for_path(path: str) -> str:
    value = path.lower()
    if value.startswith("/quote"):
        return "kite_quote"
    if "/historical/" in value:
        return "kite_historical"
    if value.startswith("/instruments"):
        return "kite_instruments"
    return "kite_other_read"
