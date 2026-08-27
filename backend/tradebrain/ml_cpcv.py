"""Combinatorial purged cross-validation folds for Trade Brain v0.14 ML.

CPCV is a *secondary historical robustness diagnostic*.  It purges target-window overlap and
embargoes observations immediately after each held-out block.  Because combinatorial CV may
train on blocks chronologically later than a test block, it must never replace Trade Brain's
causal walk-forward / prequential replay evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from math import comb
from typing import Any

import numpy as np
import pandas as pd

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
