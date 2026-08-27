"""Stationary-bootstrap uncertainty estimates for Trade Brain v0.14 ML.

Point estimates can look attractive because of one fortunate ordering of dependent trades.
This module uses a Politis-Romano style stationary bootstrap: random block lengths are
geometrically distributed and blocks wrap through the original trade sequence, preserving
local temporal dependence better than IID resampling.

Only already-selected evaluation returns are resampled. The bootstrap never changes model
parameters, trade thresholds, OOS labels, or policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from backend.tradebrain.ml_validation import max_drawdown_from_returns

METHOD_VERSION = "BSE_ML_STATIONARY_BOOTSTRAP_V1"
DEFAULT_RANDOM_STATE = 271828


@dataclass(frozen=True)
class BootstrapConfig:
    n_resamples: int = 2000
    mean_block_length: float = 8.0
    confidence_level: float = 0.95
    min_trades: int = 100
    random_state: int = DEFAULT_RANDOM_STATE

    def validate(self) -> None:
        if self.n_resamples < 500:
            raise ValueError("n_resamples must be >= 500")
        if self.mean_block_length <= 1.0:
            raise ValueError("mean_block_length must be > 1")
        if not 0.80 <= self.confidence_level < 1.0:
            raise ValueError("confidence_level must be in [0.80,1)")
        if self.min_trades < 20:
            raise ValueError("min_trades is too small")


def _finite(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    return array[np.isfinite(array)]


def profit_factor(returns_pct: Iterable[float]) -> float:
    values = _finite(returns_pct)
    wins = float(values[values > 0.0].sum()) if len(values) else 0.0
    losses = float(-values[values < 0.0].sum()) if len(values) else 0.0
    if losses > 0.0:
        return float(wins / losses)
    return 999.0 if wins > 0.0 else 0.0


def stationary_bootstrap_indices(
    n: int,
    *,
    n_resamples: int,
    mean_block_length: float,
    random_state: int,
) -> np.ndarray:
    """Generate stationary-bootstrap indices with geometrically distributed block lengths."""
    if n < 1:
        return np.empty((0, 0), dtype=int)
    rng = np.random.default_rng(int(random_state))
    restart_probability = 1.0 / float(mean_block_length)
    output = np.empty((int(n_resamples), int(n)), dtype=int)
    for sample in range(int(n_resamples)):
        index = int(rng.integers(0, n))
        for position in range(n):
            if position == 0 or float(rng.random()) < restart_probability:
                index = int(rng.integers(0, n))
            else:
                index = (index + 1) % n
            output[sample, position] = index
    return output


def stationary_bootstrap_confidence(
    returns_pct: Iterable[float],
    *,
    config: BootstrapConfig = BootstrapConfig(),
) -> dict[str, Any]:
    """Estimate confidence intervals for expectancy, profit factor, and max drawdown."""
    config.validate()
    values = _finite(returns_pct)
    n = int(len(values))
    if n < config.min_trades:
        return {
            "method_version": METHOD_VERSION,
            "status": "INSUFFICIENT_TRADES",
            "passed_sample_requirement": False,
            "trades": n,
            "required_trades": config.min_trades,
            "config": asdict(config),
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    indices = stationary_bootstrap_indices(
        n,
        n_resamples=config.n_resamples,
        mean_block_length=config.mean_block_length,
        random_state=config.random_state,
    )
    expectancies = np.empty(config.n_resamples, dtype=float)
    profit_factors = np.empty(config.n_resamples, dtype=float)
    drawdowns = np.empty(config.n_resamples, dtype=float)
    for idx, sampled_indices in enumerate(indices):
        sampled = values[sampled_indices]
        expectancies[idx] = float(np.mean(sampled))
        profit_factors[idx] = profit_factor(sampled)
        drawdowns[idx] = max_drawdown_from_returns(sampled)

    alpha = 1.0 - float(config.confidence_level)
    lower_q = alpha / 2.0
    upper_q = 1.0 - alpha / 2.0

    def interval(samples: np.ndarray) -> dict[str, float]:
        return {
            "lower": float(np.quantile(samples, lower_q)),
            "median": float(np.quantile(samples, 0.50)),
            "upper": float(np.quantile(samples, upper_q)),
        }

    return {
        "method_version": METHOD_VERSION,
        "status": "OK",
        "passed_sample_requirement": True,
        "trades": n,
        "point_estimates": {
            "mean_net_return_pct": float(np.mean(values)),
            "profit_factor": profit_factor(values),
            "max_drawdown_pct": max_drawdown_from_returns(values),
        },
        "confidence_intervals": {
            "mean_net_return_pct": interval(expectancies),
            "profit_factor": interval(profit_factors),
            "max_drawdown_pct": interval(drawdowns),
        },
        "config": asdict(config),
        "temporal_dependence_preserved_by_random_blocks": True,
        "iid_bootstrap_used": False,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def selected_returns_from_probabilities(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    *,
    threshold: float,
    friction_multiplier: float = 2.0,
) -> np.ndarray:
    """Reconstruct selected post-friction trade returns from a frozen prediction vector."""
    probabilities = np.asarray(probabilities, dtype=float)
    if len(frame) != len(probabilities):
        raise ValueError("Probability count does not match frame rows")
    selected = probabilities >= float(threshold)
    work = frame.loc[selected].copy()
    gross = pd.to_numeric(work["label_gross_return_pct"], errors="coerce").astype(float)
    net = pd.to_numeric(work["label_net_return_pct"], errors="coerce").astype(float)
    base_friction = gross - net
    stressed = gross - base_friction * float(friction_multiplier)
    return _finite(stressed.to_numpy(dtype=float))


def bootstrap_promotion_verdict(
    report: dict[str, Any] | None,
    *,
    min_pf_lower: float = 1.0,
    min_expectancy_lower_pct: float = 0.0,
    max_drawdown_upper_pct: float = 25.0,
) -> dict[str, Any]:
    """Fail closed unless the full 95% uncertainty envelope clears promotion boundaries."""
    payload = dict(report or {})
    failures: list[str] = []
    if payload.get("status") != "OK":
        failures.append("BOOTSTRAP_CONFIDENCE_NOT_AVAILABLE")
    intervals = payload.get("confidence_intervals") or {}
    pf_lower = float(((intervals.get("profit_factor") or {}).get("lower") or 0.0))
    expectancy_lower = float(((intervals.get("mean_net_return_pct") or {}).get("lower") or -999.0))
    drawdown_upper = float(((intervals.get("max_drawdown_pct") or {}).get("upper") or 999.0))
    if pf_lower <= float(min_pf_lower):
        failures.append("BOOTSTRAP_95_PF_LOWER_NOT_ABOVE_1")
    if expectancy_lower <= float(min_expectancy_lower_pct):
        failures.append("BOOTSTRAP_95_EXPECTANCY_LOWER_NOT_POSITIVE")
    if drawdown_upper > float(max_drawdown_upper_pct):
        failures.append("BOOTSTRAP_95_DRAWDOWN_UPPER_ABOVE_25_PCT")
    passed = not failures
    return {
        "method_version": METHOD_VERSION,
        "passed": passed,
        "verdict": "BOOTSTRAP_CONFIDENCE_PASS" if passed else "BOOTSTRAP_CONFIDENCE_REJECTED",
        "failures": failures,
        "checks": {
            "profit_factor_95_lower": pf_lower,
            "expectancy_95_lower_pct": expectancy_lower,
            "max_drawdown_95_upper_pct": drawdown_upper,
        },
        "thresholds": {
            "min_pf_lower": float(min_pf_lower),
            "min_expectancy_lower_pct": float(min_expectancy_lower_pct),
            "max_drawdown_upper_pct": float(max_drawdown_upper_pct),
        },
        "report": payload or None,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
