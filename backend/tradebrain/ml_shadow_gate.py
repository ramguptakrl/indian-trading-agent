"""Prospective shadow-buffer qualification for Trade Brain v0.14 ML.

A model may become integration-eligible only after a verified sequence of live shadow market
sessions with the exact same frozen artifact.  This module does not promote models; it only
produces auditable evidence for later human review.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

import pandas as pd

from backend.tradebrain.ml_promotion import DEFAULT_PROMOTION_THRESHOLDS, PromotionThresholds

METHOD_VERSION = "BSE_ML_SHADOW_GATE_V1"


def _session(value: Any) -> str | None:
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize("UTC")
        return parsed.tz_convert("Asia/Kolkata").date().isoformat()
    except Exception:
        return None


def evaluate_shadow_buffer(
    predictions: Iterable[dict[str, Any]],
    *,
    model_id: str,
    verified_market_sessions: Iterable[str],
    thresholds: PromotionThresholds = DEFAULT_PROMOTION_THRESHOLDS,
) -> dict[str, Any]:
    """Evaluate the trailing continuous shadow-session streak for one frozen artifact.

    `verified_market_sessions` must come from the official exchange-calendar layer.  Missing
    calendar evidence fails closed instead of guessing around holidays or special sessions.
    """

    thresholds.validate()
    rows = [row for row in predictions if str(row.get("model_id")) == str(model_id)]
    expected = sorted({str(x) for x in verified_market_sessions if str(x)})
    failures: list[str] = []

    if not expected:
        failures.append("VERIFIED_MARKET_SESSION_CALENDAR_REQUIRED")

    hashes = {str(row.get("model_sha256") or "") for row in rows}
    if "" in hashes:
        failures.append("SHADOW_ARTIFACT_HASH_MISSING")
        hashes.discard("")
    if len(hashes) != 1:
        failures.append("SHADOW_ARTIFACT_CHANGED_OR_RETUNED")

    if any(bool(row.get("retuned_during_shadow_session")) for row in rows):
        failures.append("RETUNE_OCCURRED_DURING_SHADOW_BUFFER")

    observed_sessions: set[str] = set()
    for row in rows:
        value = row.get("shadow_session_ist") or _session(row.get("as_of"))
        if value:
            observed_sessions.add(str(value))

    trailing_streak: list[str] = []
    if expected and observed_sessions:
        last_observed = max(observed_sessions)
        eligible_expected = [day for day in expected if day <= last_observed]
        for day in reversed(eligible_expected):
            if day in observed_sessions:
                trailing_streak.append(day)
            else:
                break
        trailing_streak.reverse()

    required = int(thresholds.min_shadow_sessions)
    if len(trailing_streak) < required:
        failures.append("SHADOW_BUFFER_BELOW_30_CONTINUOUS_MARKET_SESSIONS")

    passed = not failures
    return {
        "method_version": METHOD_VERSION,
        "model_id": str(model_id),
        "passed": passed,
        "verdict": "SHADOW_BUFFER_PASS" if passed else "SHADOW_BUFFER_REJECTED",
        "failures": failures,
        "observed_sessions": len(observed_sessions),
        "continuous_trailing_market_sessions": len(trailing_streak),
        "trailing_session_start": trailing_streak[0] if trailing_streak else None,
        "trailing_session_end": trailing_streak[-1] if trailing_streak else None,
        "artifact_hashes_seen": sorted(hashes),
        "thresholds": asdict(thresholds),
        "verified_calendar_required": True,
        "automatic_promotion": False,
        "human_review_still_required": True,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
