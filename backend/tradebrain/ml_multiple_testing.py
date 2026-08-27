"""Multiple-testing diagnostics for Trade Brain v0.14 ML.

Temporal purging prevents look-ahead leakage; it does not prevent researcher selection bias.
This module provides two complementary diagnostics:

* Deflated Sharpe Ratio (DSR): probabilistic Sharpe adjusted for the expected best result
  among many attempted candidates.
* Probability of Backtest Overfitting (PBO): how often the in-sample winner ranks in the
  bottom half out-of-sample across a strategy-by-fold matrix.

The diagnostics are research-only. They do not train, promote, or place orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import e
from statistics import NormalDist
from typing import Any, Iterable, Sequence

import numpy as np

METHOD_VERSION = "BSE_ML_MULTIPLE_TESTING_V1"
_EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()


@dataclass(frozen=True)
class MultipleTestingThresholds:
    min_dsr_probability: float = 0.95
    max_pbo: float = 0.10
    min_returns_for_dsr: int = 30
    min_strategies_for_pbo: int = 3
    min_folds_for_pbo: int = 6

    def validate(self) -> None:
        if not 0.5 < self.min_dsr_probability < 1.0:
            raise ValueError("min_dsr_probability must be in (0.5,1)")
        if not 0.0 <= self.max_pbo < 0.5:
            raise ValueError("max_pbo must be in [0,0.5)")
        if self.min_returns_for_dsr < 10:
            raise ValueError("min_returns_for_dsr is too small")
        if self.min_strategies_for_pbo < 3 or self.min_folds_for_pbo < 3:
            raise ValueError("PBO minimum dimensions are too small")


DEFAULT_MULTIPLE_TESTING_THRESHOLDS = MultipleTestingThresholds()


def _finite(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    return array[np.isfinite(array)]


def trade_sharpe(returns_pct: Iterable[float]) -> float:
    """Unannualized per-trade Sharpe, keeping all research candidates in the same units."""
    values = _finite(returns_pct)
    if len(values) < 2:
        return 0.0
    std = float(np.std(values, ddof=1))
    return float(np.mean(values) / std) if std > 0.0 else 0.0


def return_moments(returns_pct: Iterable[float]) -> dict[str, float]:
    values = _finite(returns_pct)
    if len(values) < 3:
        return {"skewness": 0.0, "kurtosis": 3.0}
    centered = values - float(np.mean(values))
    m2 = float(np.mean(centered ** 2))
    if m2 <= 0.0:
        return {"skewness": 0.0, "kurtosis": 3.0}
    skew = float(np.mean(centered ** 3) / (m2 ** 1.5))
    kurt = float(np.mean(centered ** 4) / (m2 ** 2))
    return {"skewness": skew, "kurtosis": max(kurt, 1.0)}


def probabilistic_sharpe_ratio(
    returns_pct: Iterable[float],
    *,
    benchmark_sharpe: float = 0.0,
) -> dict[str, float | int]:
    """Probability that observed Sharpe exceeds a benchmark Sharpe.

    Uses the Bailey/Lopez de Prado finite-sample correction for skewness and kurtosis. Sharpe
    is intentionally per-trade/unannualized so the estimate and benchmark use identical units.
    """
    values = _finite(returns_pct)
    n = int(len(values))
    sr = trade_sharpe(values)
    moments = return_moments(values)
    skew = float(moments["skewness"])
    kurt = float(moments["kurtosis"])
    denominator_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if n < 2 or denominator_term <= 0.0:
        probability = 0.0
        z_score = float("-inf")
    else:
        z_score = float((sr - float(benchmark_sharpe)) * np.sqrt(n - 1.0) / np.sqrt(denominator_term))
        probability = float(_NORMAL.cdf(z_score))
    return {
        "observations": n,
        "sharpe": sr,
        "benchmark_sharpe": float(benchmark_sharpe),
        "skewness": skew,
        "kurtosis": kurt,
        "z_score": z_score,
        "probability": probability,
    }


def expected_max_sharpe(
    trial_sharpes: Iterable[float],
    *,
    effective_trials: int | None = None,
) -> dict[str, float | int]:
    """Expected maximum Sharpe under a zero-edge multiple-trial null.

    `effective_trials` may exceed the supplied sample of trial Sharpes when a persistent
    research ledger records additional attempted configurations. Using raw trial count is
    conservative when candidates are correlated; the ledger separately tracks hypothesis
    families so kill-budget logic need not pretend every threshold is independent.
    """
    values = _finite(trial_sharpes)
    n = max(int(effective_trials or len(values)), int(len(values)), 1)
    if len(values) >= 2:
        sigma = float(np.std(values, ddof=1))
    else:
        sigma = 0.0
    if n <= 1 or sigma <= 0.0:
        expected = 0.0
    else:
        p1 = min(max(1.0 - 1.0 / n, 1e-12), 1.0 - 1e-12)
        p2 = min(max(1.0 - 1.0 / (n * e), 1e-12), 1.0 - 1e-12)
        z1 = _NORMAL.inv_cdf(p1)
        z2 = _NORMAL.inv_cdf(p2)
        expected = float(sigma * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2))
    return {
        "observed_trial_sharpes": int(len(values)),
        "effective_trials": n,
        "trial_sharpe_std": sigma,
        "expected_max_sharpe_under_null": expected,
    }


def deflated_sharpe_ratio(
    selected_returns_pct: Iterable[float],
    trial_sharpes: Iterable[float],
    *,
    effective_trials: int | None = None,
    thresholds: MultipleTestingThresholds = DEFAULT_MULTIPLE_TESTING_THRESHOLDS,
) -> dict[str, Any]:
    """Return DSR evidence for one validation-selected candidate."""
    thresholds.validate()
    selected = _finite(selected_returns_pct)
    expected = expected_max_sharpe(trial_sharpes, effective_trials=effective_trials)
    psr = probabilistic_sharpe_ratio(
        selected,
        benchmark_sharpe=float(expected["expected_max_sharpe_under_null"]),
    )
    sufficient = len(selected) >= thresholds.min_returns_for_dsr
    passed = bool(sufficient and float(psr["probability"]) >= thresholds.min_dsr_probability)
    return {
        "method_version": METHOD_VERSION,
        "passed": passed,
        "verdict": "DSR_PASS" if passed else "DSR_REJECTED",
        "selected_candidate": psr,
        "multiple_trial_null": expected,
        "minimum_probability": thresholds.min_dsr_probability,
        "minimum_selected_returns": thresholds.min_returns_for_dsr,
        "sufficient_selected_returns": sufficient,
        "selection_period": "VALIDATION_ONLY",
        "oos_used": False,
        "holdout_used": False,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def probability_backtest_overfitting(
    in_sample_scores: Sequence[Sequence[float]],
    out_of_sample_scores: Sequence[Sequence[float]],
    *,
    strategy_ids: Sequence[str] | None = None,
    thresholds: MultipleTestingThresholds = DEFAULT_MULTIPLE_TESTING_THRESHOLDS,
) -> dict[str, Any]:
    """Estimate PBO from aligned CPCV IS/OOS strategy score matrices.

    Rows are CPCV combinations/folds and columns are the *same* competing strategy
    configurations. Higher score must mean better performance. For every row, the best IS
    strategy is selected and its OOS percentile rank is measured. PBO is the fraction whose
    OOS percentile is at/below the median.
    """
    thresholds.validate()
    ins = np.asarray(in_sample_scores, dtype=float)
    outs = np.asarray(out_of_sample_scores, dtype=float)
    if ins.ndim != 2 or outs.ndim != 2 or ins.shape != outs.shape:
        raise ValueError("PBO matrices must be aligned two-dimensional arrays")
    folds, strategies = ins.shape
    ids = list(strategy_ids or [f"STRATEGY_{idx}" for idx in range(strategies)])
    if len(ids) != strategies:
        raise ValueError("strategy_ids length does not match score matrix")

    rows: list[dict[str, Any]] = []
    for fold in range(folds):
        valid = np.isfinite(ins[fold]) & np.isfinite(outs[fold])
        indices = np.flatnonzero(valid)
        if len(indices) < thresholds.min_strategies_for_pbo:
            continue
        best_index = int(indices[np.argmax(ins[fold, indices])])
        oos_values = outs[fold, indices]
        selected_oos = float(outs[fold, best_index])
        # Mid-rank percentile handles ties without claiming false precision.
        less = float(np.sum(oos_values < selected_oos))
        equal = float(np.sum(oos_values == selected_oos))
        percentile = float((less + 0.5 * equal) / len(oos_values))
        clipped = min(max(percentile, 1e-9), 1.0 - 1e-9)
        rows.append({
            "fold": fold + 1,
            "best_is_strategy": ids[best_index],
            "best_is_score": float(ins[fold, best_index]),
            "selected_oos_score": selected_oos,
            "selected_oos_percentile": percentile,
            "logit_rank": float(np.log(clipped / (1.0 - clipped))),
            "below_oos_median": bool(percentile <= 0.5),
            "strategies_ranked": int(len(indices)),
        })

    usable = len(rows)
    pbo = float(np.mean([row["below_oos_median"] for row in rows])) if rows else 1.0
    sufficient = bool(
        strategies >= thresholds.min_strategies_for_pbo
        and usable >= thresholds.min_folds_for_pbo
    )
    passed = bool(sufficient and pbo <= thresholds.max_pbo)
    return {
        "method_version": METHOD_VERSION,
        "passed": passed,
        "verdict": "PBO_PASS" if passed else "PBO_REJECTED",
        "pbo": pbo,
        "maximum_pbo": thresholds.max_pbo,
        "matrix_folds": int(folds),
        "matrix_strategies": int(strategies),
        "usable_folds": usable,
        "sufficient_matrix": sufficient,
        "rows": rows,
        "requires_same_strategy_set_across_is_oos": True,
        "cpcv_required": True,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def multiple_testing_thresholds() -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "thresholds": asdict(DEFAULT_MULTIPLE_TESTING_THRESHOLDS),
        "raw_candidate_trials_and_hypothesis_families_must_be_tracked_separately": True,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
