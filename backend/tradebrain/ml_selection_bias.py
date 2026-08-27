"""Researcher-selection-bias evidence for Trade Brain v0.14 ML.

DSR uses only validation-period candidate metrics plus the persistent research ledger's
cumulative candidate count. OOS and holdout are intentionally excluded from DSR construction.
PBO is a separate CPCV matrix diagnostic; both are required before this module can declare the
multiple-testing layer cleared.
"""
from __future__ import annotations

from math import sqrt
from statistics import NormalDist
from typing import Any

import numpy as np

from backend.tradebrain.ml_multiple_testing import (
    DEFAULT_MULTIPLE_TESTING_THRESHOLDS,
    expected_max_sharpe,
)

METHOD_VERSION = "BSE_ML_SELECTION_BIAS_V1"
_NORMAL = NormalDist()


def _finite_trial_sharpes(trials: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for trial in trials:
        validation = trial.get("validation") or {}
        try:
            value = float(validation.get("trade_sharpe"))
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            values.append(value)
    return values


def evaluate_dsr_from_optimizer(
    result: Any,
    *,
    cumulative_candidate_count: int,
) -> dict[str, Any]:
    """Compute DSR from validation-only trial metrics stored by the optimizer."""
    winner = getattr(result, "winner", None) or {}
    validation = winner.get("validation") or {}
    trials = list(getattr(result, "trials", None) or [])
    trial_sharpes = _finite_trial_sharpes(trials)

    try:
        n = int(validation.get("trades") or 0)
        sr = float(validation.get("trade_sharpe"))
        skew = float(validation.get("return_skewness"))
        kurt = float(validation.get("return_kurtosis"))
    except (TypeError, ValueError):
        n, sr, skew, kurt = 0, 0.0, 0.0, 3.0

    effective_trials = max(int(cumulative_candidate_count), len(trial_sharpes), 1)
    null = expected_max_sharpe(trial_sharpes, effective_trials=effective_trials)
    benchmark = float(null["expected_max_sharpe_under_null"])
    denominator_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if n < 2 or denominator_term <= 0.0:
        z_score = float("-inf")
        probability = 0.0
    else:
        z_score = float((sr - benchmark) * sqrt(n - 1.0) / sqrt(denominator_term))
        probability = float(_NORMAL.cdf(z_score))

    threshold = DEFAULT_MULTIPLE_TESTING_THRESHOLDS
    sufficient = n >= threshold.min_returns_for_dsr and len(trial_sharpes) >= 2
    passed = bool(sufficient and probability >= threshold.min_dsr_probability)
    return {
        "method_version": METHOD_VERSION,
        "passed": passed,
        "verdict": "DSR_PASS" if passed else "DSR_REJECTED",
        "selected_validation_metrics": {
            "trades": n,
            "trade_sharpe": sr,
            "return_skewness": skew,
            "return_kurtosis": kurt,
        },
        "deflated_sharpe_probability": probability,
        "minimum_probability": threshold.min_dsr_probability,
        "z_score": z_score,
        "multiple_trial_null": null,
        "current_run_trial_sharpes": len(trial_sharpes),
        "cumulative_candidate_count": effective_trials,
        "selection_period": "VALIDATION_ONLY",
        "oos_used": False,
        "holdout_used": False,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def multiple_testing_clearance(
    *,
    dsr: dict[str, Any] | None,
    pbo: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fail closed until both DSR and CPCV PBO have passed."""
    dsr_payload = dict(dsr or {})
    pbo_payload = dict(pbo or {})
    failures: list[str] = []
    if not dsr_payload:
        failures.append("DSR_EVIDENCE_MISSING")
    elif not bool(dsr_payload.get("passed")):
        failures.append("DSR_REJECTED")
    if not pbo_payload:
        failures.append("PBO_EVIDENCE_MISSING")
    elif not bool(pbo_payload.get("passed")):
        failures.append("PBO_REJECTED")
    passed = not failures
    return {
        "method_version": METHOD_VERSION,
        "passed": passed,
        "verdict": "MULTIPLE_TESTING_CLEAR" if passed else "MULTIPLE_TESTING_REJECTED",
        "failures": failures,
        "dsr": dsr_payload or None,
        "pbo": pbo_payload or None,
        "oos_used_for_selection_bias_estimation": False,
        "holdout_used": False,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
