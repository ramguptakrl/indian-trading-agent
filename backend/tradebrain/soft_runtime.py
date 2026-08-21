"""Runtime bridge from Phase-5 human-approved soft registry into advisory policy.

Only ACTIVE soft-parameter versions created by the Phase-5 human promotion path may
change a soft runtime preference. Missing, malformed or ambiguous registry state falls
back to the documented default. Hard rules are never read from this registry.
"""

from __future__ import annotations

import math
from typing import Any

from backend.tradebrain.challenger_store import list_soft_parameter_versions
from backend.tradebrain.trade_modes import to_active_mode

DEFAULT_SOFT_RUNTIME = {
    "INTRADAY": {
        "parameter_key": "day_min_reward_risk",
        "parameter_scope": "DAY",
        "default_value": 1.0,
    },
    "SWING": {
        "parameter_key": "swing_min_reward_risk",
        "parameter_scope": "SWING_POSITION",
        "default_value": 3.0,
    },
}


def _valid_positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def effective_reward_risk_preference(mode: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Return the effective soft R:R preference with full audit provenance."""

    active_mode = to_active_mode(mode)
    spec = DEFAULT_SOFT_RUNTIME[active_mode]
    default = float(spec["default_value"])
    result: dict[str, Any] = {
        "active_mode": active_mode,
        "parameter_key": spec["parameter_key"],
        "parameter_scope": spec["parameter_scope"],
        "value": default,
        "source": "DEFAULT_SOFT_PREFERENCE",
        "version": None,
        "source_experiment_id": None,
        "approved_by": None,
        "activated_at": None,
        "registry_applied": False,
        "hard_policy_mutated": False,
        "warning": None,
    }

    try:
        versions = list_soft_parameter_versions(
            parameter_key=spec["parameter_key"], active_only=True, db_path=db_path
        )
    except Exception as exc:  # fail-safe: research preference may degrade to default, never fail open
        result["warning"] = f"Soft registry unavailable; default retained: {type(exc).__name__}"
        return result

    matches = [
        row for row in versions
        if str(row.get("parameter_scope") or "") == spec["parameter_scope"]
        and str(row.get("status") or "").upper() == "ACTIVE"
    ]
    if not matches:
        return result

    # There should be one ACTIVE row per key/scope. If storage is corrupted, refuse to
    # guess which value wins and retain the documented default.
    if len(matches) != 1:
        result["warning"] = f"Expected one ACTIVE soft version; found {len(matches)}. Default retained."
        return result

    row = matches[0]
    value = _valid_positive_number(row.get("value"))
    if value is None:
        result["warning"] = "ACTIVE soft version has invalid value; default retained."
        return result
    if not str(row.get("approved_by") or "").strip() or not str(row.get("approval_note") or "").strip():
        result["warning"] = "ACTIVE soft version lacks human approval provenance; default retained."
        return result

    result.update(
        {
            "value": value,
            "source": "HUMAN_APPROVED_SOFT_REGISTRY",
            "version": int(row.get("version") or 0),
            "source_experiment_id": row.get("source_experiment_id"),
            "approved_by": row.get("approved_by"),
            "activated_at": row.get("activated_at"),
            "registry_applied": True,
        }
    )
    return result


def effective_soft_runtime(*, db_path: str | None = None) -> dict[str, Any]:
    return {
        mode: effective_reward_risk_preference(mode, db_path=db_path)
        for mode in ("INTRADAY", "SWING")
    }
