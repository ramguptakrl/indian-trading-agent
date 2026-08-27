"""Drift-triggered retraining policy for Trade Brain v0.14 ML.

This module decides whether a *research* retraining cycle is justified.  It never mutates a
registered model, never retrains during market hours, never promotes automatically, and never
places broker orders.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

METHOD_VERSION = "BSE_ML_RETRAIN_TRIGGER_V1"


@dataclass(frozen=True)
class RetrainingTriggerConfig:
    watch_sessions_before_retrain: int = 5
    require_after_market_mode: bool = True

    def validate(self) -> None:
        if self.watch_sessions_before_retrain < 1:
            raise ValueError("watch_sessions_before_retrain must be positive")


def retraining_recommendation(
    *,
    feature_drift: dict[str, Any] | None,
    shadow_performance: dict[str, Any] | None,
    operating_mode: str,
    consecutive_watch_sessions: int = 0,
    config: RetrainingTriggerConfig = RetrainingTriggerConfig(),
) -> dict[str, Any]:
    """Return a fail-closed recommendation for a new research training cycle.

    A recommendation is not a mutation of the current frozen/shadow artifact.  The existing
    model remains unchanged while any challenger is trained and revalidated separately.
    """

    config.validate()
    mode = str(operating_mode or "UNKNOWN")
    feature_status = str((feature_drift or {}).get("status") or "UNKNOWN")
    performance_status = str((shadow_performance or {}).get("status") or "UNKNOWN")
    performance_alerts = set(str(x) for x in ((shadow_performance or {}).get("alerts") or []))

    hard_trigger_reasons: list[str] = []
    watch_reasons: list[str] = []

    if feature_status == "DRIFT_ALERT":
        hard_trigger_reasons.append("FEATURE_DRIFT_ALERT")
    elif feature_status == "WATCH":
        watch_reasons.append("FEATURE_DRIFT_WATCH")

    if performance_status == "DRIFT_ALERT":
        hard_trigger_reasons.append("MODEL_PERFORMANCE_DRIFT_ALERT")
    elif performance_status == "WATCH":
        watch_reasons.append("MODEL_PERFORMANCE_WATCH")

    for alert in (
        "CALIBRATION_DRIFT",
        "EXPECTANCY_DEGRADATION",
        "DRAWDOWN_DEGRADATION",
        "LOSING_STREAK_DEGRADATION",
    ):
        if alert in performance_alerts:
            hard_trigger_reasons.append(alert)

    persistent_watch = bool(
        watch_reasons and int(consecutive_watch_sessions) >= int(config.watch_sessions_before_retrain)
    )
    if persistent_watch:
        hard_trigger_reasons.append("PERSISTENT_DRIFT_WATCH")

    after_market = mode in {"POST_MARKET_STUDY", "STUDY_REPLAY"}
    raw_trigger = bool(hard_trigger_reasons)
    allowed_now = raw_trigger and (after_market or not config.require_after_market_mode)

    if not raw_trigger:
        verdict = "KEEP_FROZEN_MODEL_NO_RETRAIN"
    elif not allowed_now:
        verdict = "DEFER_RETRAIN_UNTIL_AFTER_MARKET"
    else:
        verdict = "RESEARCH_RETRAIN_RECOMMENDED"

    return {
        "method_version": METHOD_VERSION,
        "verdict": verdict,
        "research_retrain_recommended": bool(allowed_now),
        "trigger_detected": bool(raw_trigger),
        "operating_mode": mode,
        "after_market_required": bool(config.require_after_market_mode),
        "hard_trigger_reasons": sorted(set(hard_trigger_reasons)),
        "watch_reasons": sorted(set(watch_reasons)),
        "consecutive_watch_sessions": int(consecutive_watch_sessions),
        "config": asdict(config),
        "current_model_mutated": False,
        "automatic_promotion": False,
        "automatic_advisory_integration": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
