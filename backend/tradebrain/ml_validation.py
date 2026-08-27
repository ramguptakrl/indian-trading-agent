"""Chronological validation helpers for Trade Brain v0.14 ML.

No random K-fold validation is used for trading claims. Dataset rows carry an explicit
label_end timestamp so purge/embargo logic can remove samples whose outcome window leaks
across a later evaluation boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

METHOD_VERSION = "BSE_ML_CHRONOLOGY_V1"


@dataclass(frozen=True)
class Chronology:
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    oos_start: str
    oos_end: str
    holdout_start: str | None = None
    holdout_end: str | None = None
    embargo_days: int = 1

    def validate(self) -> None:
        values = [_ts(x) for x in (
            self.train_start, self.train_end, self.validation_start,
            self.validation_end, self.oos_start, self.oos_end,
        )]
        if not (values[0] < values[1] <= values[2] < values[3] <= values[4] < values[5]):
            raise ValueError("Chronology ranges must be ordered and non-overlapping")
        if self.embargo_days < 0:
            raise ValueError("embargo_days must be >= 0")
        if self.holdout_start and self.holdout_end:
            h0, h1 = _ts(self.holdout_start), _ts(self.holdout_end)
            if not values[5] <= h0 < h1:
                raise ValueError("Holdout must begin at/after the OOS end")


DEFAULT_CHRONOLOGY = Chronology(
    train_start="2017-01-01T00:00:00+00:00",
    train_end="2023-01-01T00:00:00+00:00",
    validation_start="2023-01-01T00:00:00+00:00",
    validation_end="2025-01-01T00:00:00+00:00",
    oos_start="2025-01-01T00:00:00+00:00",
    oos_end="2026-01-01T00:00:00+00:00",
    holdout_start="2026-01-01T00:00:00+00:00",
    holdout_end="2026-08-22T00:00:00+00:00",
    embargo_days=1,
)


def _ts(value: str | pd.Timestamp) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def _window(
    frame: pd.DataFrame,
    *,
    start: str,
    end: str,
    next_boundary: str | None,
    embargo_days: int,
) -> pd.DataFrame:
    feature_time = pd.to_datetime(frame["ts_close"], utc=True)
    label_end = pd.to_datetime(frame["label_end"], utc=True)
    start_ts = _ts(start)
    end_ts = _ts(end)
    mask = (feature_time >= start_ts) & (feature_time < end_ts)
    if next_boundary:
        boundary = _ts(next_boundary) - pd.Timedelta(days=embargo_days)
        mask &= label_end < boundary
    return frame.loc[mask].copy().reset_index(drop=True)


def chronological_split(
    frame: pd.DataFrame,
    *,
    chronology: Chronology = DEFAULT_CHRONOLOGY,
) -> dict[str, pd.DataFrame]:
    chronology.validate()
    required = {"ts_close", "label_end", "label_net_positive", "label_net_return_pct"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset missing chronology columns: {sorted(missing)}")
    result = {
        "TRAIN": _window(
            frame,
            start=chronology.train_start,
            end=chronology.train_end,
            next_boundary=chronology.validation_start,
            embargo_days=chronology.embargo_days,
        ),
        "VALIDATION": _window(
            frame,
            start=chronology.validation_start,
            end=chronology.validation_end,
            next_boundary=chronology.oos_start,
            embargo_days=chronology.embargo_days,
        ),
        "OOS": _window(
            frame,
            start=chronology.oos_start,
            end=chronology.oos_end,
            next_boundary=chronology.holdout_start,
            embargo_days=chronology.embargo_days,
        ),
    }
    if chronology.holdout_start and chronology.holdout_end:
        result["HOLDOUT"] = _window(
            frame,
            start=chronology.holdout_start,
            end=chronology.holdout_end,
            next_boundary=None,
            embargo_days=0,
        )
    return result


def max_drawdown_from_returns(returns_pct: Iterable[float]) -> float:
    values = np.asarray(list(returns_pct), dtype=float)
    if len(values) == 0:
        return 0.0
    equity = np.cumprod(1.0 + values / 100.0)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity / peak - 1.0) * 100.0
    return float(abs(np.min(drawdown)))


def worst_losing_streak(returns_pct: Iterable[float]) -> int:
    worst = current = 0
    for value in returns_pct:
        if float(value) < 0.0:
            current += 1
            worst = max(worst, current)
        else:
            current = 0
    return worst


def _return_moments(returns: np.ndarray) -> tuple[float, float]:
    if len(returns) < 3:
        return 0.0, 3.0
    centered = returns - float(np.mean(returns))
    m2 = float(np.mean(centered ** 2))
    if m2 <= 0.0:
        return 0.0, 3.0
    skew = float(np.mean(centered ** 3) / (m2 ** 1.5))
    kurt = float(np.mean(centered ** 4) / (m2 ** 2))
    return skew, max(kurt, 1.0)


def trading_metrics(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    *,
    threshold: float,
    slippage_bps: float,
    friction_multiplier: float = 1.0,
) -> dict[str, Any]:
    if len(frame) != len(probabilities):
        raise ValueError("Probability count does not match evaluation rows")
    y = frame["label_net_positive"].astype(int).to_numpy()
    probabilities = np.asarray(probabilities, dtype=float)
    selected = probabilities >= float(threshold)
    selected_frame = frame.loc[selected].copy()
    extra_friction_pct = max(0.0, float(friction_multiplier) - 1.0) * 2.0 * float(slippage_bps) * 0.01
    returns = selected_frame["label_net_return_pct"].astype(float).to_numpy() - extra_friction_pct
    gross_profit = float(returns[returns > 0.0].sum()) if len(returns) else 0.0
    gross_loss = float(-returns[returns < 0.0].sum()) if len(returns) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0.0 else (999.0 if gross_profit > 0.0 else 0.0)
    return_std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    trade_sharpe = float(np.mean(returns) / return_std) if return_std > 0.0 else 0.0
    return_skewness, return_kurtosis = _return_moments(returns)
    years = pd.to_datetime(selected_frame["ts_close"], utc=True).dt.year if len(selected_frame) else pd.Series(dtype=int)
    year_expectancy = {}
    for year in sorted(set(years.tolist())):
        vals = returns[years.to_numpy() == year]
        year_expectancy[str(year)] = float(np.mean(vals)) if len(vals) else 0.0
    regimes = selected_frame.get("regime")
    regime_expectancy = {}
    if regimes is not None:
        for regime in sorted(set(str(x) for x in regimes.fillna("UNKNOWN").tolist())):
            mask = regimes.fillna("UNKNOWN").astype(str).to_numpy() == regime
            vals = returns[mask]
            regime_expectancy[regime] = float(np.mean(vals)) if len(vals) else 0.0
    if len(set(y.tolist())) > 1:
        roc_auc = float(roc_auc_score(y, probabilities))
        logloss = float(log_loss(y, np.clip(probabilities, 1e-7, 1 - 1e-7), labels=[0, 1]))
    else:
        roc_auc = None
        logloss = None
    brier = float(brier_score_loss(y, probabilities)) if len(y) else None
    return {
        "rows": int(len(frame)),
        "trades": int(selected.sum()),
        "coverage_pct": float(selected.mean() * 100.0) if len(selected) else 0.0,
        "win_rate_pct": float((returns > 0.0).mean() * 100.0) if len(returns) else 0.0,
        "mean_net_return_pct": float(np.mean(returns)) if len(returns) else 0.0,
        "median_net_return_pct": float(np.median(returns)) if len(returns) else 0.0,
        "std_net_return_pct": return_std,
        "trade_sharpe": trade_sharpe,
        "return_skewness": return_skewness,
        "return_kurtosis": return_kurtosis,
        "sum_net_return_pct": float(np.sum(returns)) if len(returns) else 0.0,
        "profit_factor": float(profit_factor),
        "max_drawdown_pct": max_drawdown_from_returns(returns),
        "worst_losing_streak": worst_losing_streak(returns),
        "brier_score": brier,
        "roc_auc": roc_auc,
        "log_loss": logloss,
        "year_expectancy_pct": year_expectancy,
        "regime_expectancy_pct": regime_expectancy,
        "friction_multiplier": float(friction_multiplier),
        "extra_friction_pct_per_trade": float(extra_friction_pct),
    }


def robustness_score(
    normal: dict[str, Any],
    stress_15x: dict[str, Any],
    stress_20x: dict[str, Any],
    *,
    min_trades: int,
) -> float:
    if int(normal["trades"]) < int(min_trades):
        return float("-inf")
    expectancy = float(normal["mean_net_return_pct"])
    pf = min(float(normal["profit_factor"]), 5.0)
    dd = float(normal["max_drawdown_pct"])
    win = float(normal["win_rate_pct"]) / 100.0
    brier = float(normal["brier_score"] or 0.25)
    years = normal.get("year_expectancy_pct") or {}
    year_stability = sum(float(v) >= 0.0 for v in years.values()) / len(years) if years else 0.0
    regimes = normal.get("regime_expectancy_pct") or {}
    regime_stability = sum(float(v) >= -0.05 for v in regimes.values()) / len(regimes) if regimes else 0.0
    stress_penalty = 0.0
    if float(stress_15x["mean_net_return_pct"]) <= 0.0:
        stress_penalty += 0.5
    if float(stress_20x["mean_net_return_pct"]) <= 0.0:
        stress_penalty += 1.0
    return float(
        expectancy * 1.5
        + pf * 0.15
        + win * 0.25
        + year_stability * 0.15
        + regime_stability * 0.10
        - dd * 0.10
        - brier * 0.50
        - stress_penalty
    )


def expanding_walk_forward_windows(
    frame: pd.DataFrame,
    *,
    first_test_year: int,
    last_test_year: int,
    min_train_rows: int = 200,
) -> list[tuple[pd.DataFrame, pd.DataFrame, str]]:
    times = pd.to_datetime(frame["ts_close"], utc=True)
    windows = []
    for year in range(int(first_test_year), int(last_test_year) + 1):
        test_start = pd.Timestamp(f"{year}-01-01T00:00:00Z")
        test_end = pd.Timestamp(f"{year + 1}-01-01T00:00:00Z")
        train = frame.loc[times < test_start].copy().reset_index(drop=True)
        test = frame.loc[(times >= test_start) & (times < test_end)].copy().reset_index(drop=True)
        if len(train) >= min_train_rows and len(test) > 0:
            windows.append((train, test, str(year)))
    return windows
