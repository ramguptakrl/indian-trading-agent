"""Combinatorial purged cross-validation for Trade Brain v0.14 ML.

CPCV is a *secondary historical robustness diagnostic*. It purges target-window overlap and
embargoes observations immediately after each held-out block. Because combinatorial CV may
train on blocks chronologically later than a test block, it must never replace Trade Brain's
causal walk-forward / prequential replay evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from math import comb, ceil
from typing import Any, Iterable

import numpy as np
import pandas as pd

from backend.tradebrain.ml_models import (
    DEFAULT_RANDOM_STATE,
    ModelSpec,
    fit_model,
    predict_positive_probability,
)
from backend.tradebrain.ml_validation import trading_metrics

METHOD_VERSION = "BSE_ML_CPCV_V1"


@dataclass(frozen=True)
class CPCVConfig:
    n_groups: int = 6
    n_test_groups: int = 2
    embargo_days: int = 1
    min_train_rows: int = 100
    min_test_rows: int = 20

    def validate(self) -> None:
        if self.n_groups < 3:
            raise ValueError("n_groups must be >= 3")
        if not 1 <= self.n_test_groups < self.n_groups:
            raise ValueError("n_test_groups must be in [1, n_groups)")
        if self.embargo_days < 0:
            raise ValueError("embargo_days must be >= 0")
        if self.min_train_rows < 1 or self.min_test_rows < 1:
            raise ValueError("minimum row counts must be positive")


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"ts_close", "label_end"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"CPCV frame missing required columns: {sorted(missing)}")
    work = frame.copy().sort_values("ts_close", kind="stable").reset_index(drop=True)
    work["_feature_time"] = pd.to_datetime(work["ts_close"], utc=True)
    work["_label_end"] = pd.to_datetime(work["label_end"], utc=True)
    if (work["_label_end"] < work["_feature_time"]).any():
        raise ValueError("CPCV found label_end before feature timestamp")
    return work


def combinatorial_purged_folds(
    frame: pd.DataFrame,
    *,
    config: CPCVConfig = CPCVConfig(),
) -> list[dict[str, Any]]:
    """Build purged/embargoed CPCV train-test folds without using labels for partitioning."""

    config.validate()
    work = _prepare(frame)
    if len(work) < config.n_groups:
        return []

    group_arrays = [np.asarray(x, dtype=int) for x in np.array_split(np.arange(len(work)), config.n_groups)]
    folds: list[dict[str, Any]] = []

    for fold_number, test_groups in enumerate(combinations(range(config.n_groups), config.n_test_groups), start=1):
        test_indices = np.concatenate([group_arrays[idx] for idx in test_groups])
        candidate_indices = np.concatenate(
            [group_arrays[idx] for idx in range(config.n_groups) if idx not in test_groups]
        )
        test = work.iloc[test_indices].copy()
        candidate = work.iloc[candidate_indices].copy()

        intervals: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
        for group_idx in test_groups:
            block = work.iloc[group_arrays[group_idx]]
            start = block["_feature_time"].min()
            end = block["_label_end"].max()
            embargo_end = end + pd.Timedelta(days=config.embargo_days)
            intervals.append((start, end, embargo_end))

        keep = pd.Series(True, index=candidate.index)
        for start, end, embargo_end in intervals:
            overlaps_target_window = (
                (candidate["_feature_time"] <= end)
                & (candidate["_label_end"] >= start)
            )
            embargoed_after_test = (
                (candidate["_feature_time"] > end)
                & (candidate["_feature_time"] <= embargo_end)
            )
            keep &= ~(overlaps_target_window | embargoed_after_test)

        train = candidate.loc[keep].copy()
        if len(train) < config.min_train_rows or len(test) < config.min_test_rows:
            continue

        drop_cols = ["_feature_time", "_label_end"]
        train_public = train.drop(columns=drop_cols).reset_index(drop=True)
        test_public = test.drop(columns=drop_cols).reset_index(drop=True)
        folds.append(
            {
                "fold": fold_number,
                "test_groups": list(test_groups),
                "train": train_public,
                "test": test_public,
                "train_rows": int(len(train_public)),
                "test_rows": int(len(test_public)),
                "purged_rows": int(len(candidate) - len(train)),
                "test_intervals": [
                    {
                        "start": start.isoformat(),
                        "label_end": end.isoformat(),
                        "embargo_end": embargo_end.isoformat(),
                    }
                    for start, end, embargo_end in intervals
                ],
                "uses_future_blocks_for_diagnostic": True,
                "causal_replay_replacement": False,
                "advisory_only": True,
                "trade_authorization": False,
                "order_execution_allowed": False,
            }
        )
    return folds


def _stressed_frame(frame: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    work = frame.copy()
    gross = pd.to_numeric(work["label_gross_return_pct"], errors="coerce").astype(float)
    net = pd.to_numeric(work["label_net_return_pct"], errors="coerce").astype(float)
    friction = gross - net
    work["label_net_return_pct"] = gross - friction * float(multiplier)
    return work


def evaluate_cpcv_candidate(
    frame: pd.DataFrame,
    *,
    feature_columns: Iterable[str],
    family: str,
    params: dict[str, Any],
    threshold: float,
    config: CPCVConfig = CPCVConfig(),
    random_state: int = DEFAULT_RANDOM_STATE,
    min_selected_trades_per_fold: int = 20,
    min_2x_profit_factor: float = 1.30,
    min_pass_fraction: float = 0.80,
) -> dict[str, Any]:
    """Score one already-frozen candidate across purged/embargoed CPCV folds.

    CPCV never chooses the model family, hyperparameters, features, or threshold here; those
    must already be frozen by the validation-only optimizer.
    """

    if not 0.0 < float(threshold) < 1.0:
        raise ValueError("threshold must be in (0,1)")
    if min_selected_trades_per_fold < 1:
        raise ValueError("min_selected_trades_per_fold must be positive")
    if min_2x_profit_factor <= 1.0:
        raise ValueError("min_2x_profit_factor must be > 1")
    if not 0.0 < min_pass_fraction <= 1.0:
        raise ValueError("min_pass_fraction must be in (0,1]")

    folds = combinatorial_purged_folds(frame, config=config)
    spec = ModelSpec(str(family), dict(params))
    rows: list[dict[str, Any]] = []

    for fold in folds:
        train = fold["train"]
        test = fold["test"]
        if set(pd.to_numeric(train["label_net_positive"], errors="coerce").dropna().astype(int).tolist()) != {0, 1}:
            rows.append({
                "fold": fold["fold"],
                "status": "UNUSABLE_SINGLE_CLASS_TRAIN",
                "test_groups": fold["test_groups"],
            })
            continue
        try:
            model = fit_model(
                train,
                feature_columns=tuple(feature_columns),
                spec=spec,
                random_state=random_state,
            )
            probabilities = predict_positive_probability(
                model,
                test,
                feature_columns=tuple(feature_columns),
            )
            normal = trading_metrics(
                test,
                probabilities,
                threshold=float(threshold),
                slippage_bps=0.0,
                friction_multiplier=1.0,
            )
            stress20 = trading_metrics(
                _stressed_frame(test, 2.0),
                probabilities,
                threshold=float(threshold),
                slippage_bps=0.0,
                friction_multiplier=1.0,
            )
            selected = int(normal.get("trades") or 0)
            expectancy_2x = float(stress20.get("mean_net_return_pct") or 0.0)
            pf_2x = float(stress20.get("profit_factor") or 0.0)
            strict_pass = bool(
                selected >= int(min_selected_trades_per_fold)
                and expectancy_2x > 0.0
                and pf_2x >= float(min_2x_profit_factor)
            )
            catastrophic = bool(
                selected >= int(min_selected_trades_per_fold)
                and (expectancy_2x <= 0.0 or pf_2x < 1.0)
            )
            rows.append({
                "fold": fold["fold"],
                "test_groups": fold["test_groups"],
                "train_rows": fold["train_rows"],
                "test_rows": fold["test_rows"],
                "purged_rows": fold["purged_rows"],
                "selected_trades": selected,
                "normal": normal,
                "stress_20x": stress20,
                "strict_pass": strict_pass,
                "catastrophic": catastrophic,
                "status": "PASS" if strict_pass else "REJECTED",
            })
        except Exception as exc:
            rows.append({
                "fold": fold["fold"],
                "test_groups": fold["test_groups"],
                "status": "MODEL_EVALUATION_FAILED",
                "error": f"{type(exc).__name__}:{str(exc)[:180]}",
            })

    scored = [row for row in rows if "strict_pass" in row]
    pass_count = sum(bool(row["strict_pass"]) for row in scored)
    catastrophic_count = sum(bool(row["catastrophic"]) for row in scored)
    pass_fraction = float(pass_count / len(scored)) if scored else 0.0
    theoretical = comb(config.n_groups, config.n_test_groups)
    minimum_usable = max(3, ceil(theoretical * 0.50))
    passed = bool(
        len(scored) >= minimum_usable
        and pass_fraction >= float(min_pass_fraction)
        and catastrophic_count == 0
    )

    return {
        "method_version": METHOD_VERSION,
        "passed": passed,
        "verdict": "CPCV_ROBUSTNESS_PASS" if passed else "CPCV_ROBUSTNESS_REJECTED",
        "frozen_configuration": {
            "family": str(family),
            "params": dict(params),
            "feature_columns": list(feature_columns),
            "threshold": float(threshold),
        },
        "theoretical_folds": theoretical,
        "usable_scored_folds": len(scored),
        "minimum_usable_folds": minimum_usable,
        "strict_pass_folds": pass_count,
        "pass_fraction": pass_fraction,
        "required_pass_fraction": float(min_pass_fraction),
        "catastrophic_folds": catastrophic_count,
        "min_selected_trades_per_fold": int(min_selected_trades_per_fold),
        "min_2x_profit_factor": float(min_2x_profit_factor),
        "folds": rows,
        "uses_future_blocks_for_diagnostic": True,
        "used_for_hyperparameter_selection": False,
        "causal_walk_forward_still_required": True,
        "prequential_replay_still_required": True,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def cpcv_plan_summary(
    frame: pd.DataFrame,
    *,
    config: CPCVConfig = CPCVConfig(),
) -> dict[str, Any]:
    config.validate()
    folds = combinatorial_purged_folds(frame, config=config)
    return {
        "method_version": METHOD_VERSION,
        "config": asdict(config),
        "theoretical_combinations": comb(config.n_groups, config.n_test_groups),
        "usable_folds": len(folds),
        "purging_enabled": True,
        "embargo_enabled": config.embargo_days > 0,
        "causal_walk_forward_still_required": True,
        "prequential_replay_still_required": True,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
