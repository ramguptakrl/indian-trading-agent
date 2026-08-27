"""Predeclared structural-break research views for Trade Brain v0.14 ML.

BSE's equity-derivatives relaunch date (15 May 2023) is treated as an external business-event
hypothesis, never as a boundary optimized against OOS returns. Old history remains available
as a full-history control and stress evidence.

This module only prepares training views/weights. It does not select a winner, inspect holdout,
promote a model, or place orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

METHOD_VERSION = "BSE_ML_STRUCTURAL_BREAK_V1"
BSE_DERIVATIVES_RELAUNCH_HYPOTHESIS = "BSE_DERIVATIVES_RELAUNCH_2023_05_15"
BREAK_TIMESTAMP_UTC = "2023-05-14T18:30:00Z"  # 15 May 2023 00:00 IST

VARIANT_FULL_HISTORY = "FULL_HISTORY_CONTROL"
VARIANT_PRE_BREAK_DOWNWEIGHTED = "PRE_2023_DOWNWEIGHTED"
VARIANT_POST_BREAK_ONLY = "POST_2023_ONLY"
STRUCTURAL_VARIANTS = (
    VARIANT_FULL_HISTORY,
    VARIANT_PRE_BREAK_DOWNWEIGHTED,
    VARIANT_POST_BREAK_ONLY,
)


@dataclass(frozen=True)
class StructuralBreakConfig:
    break_timestamp_utc: str = BREAK_TIMESTAMP_UTC
    pre_break_weight: float = 0.25

    def validate(self) -> None:
        timestamp = pd.Timestamp(self.break_timestamp_utc)
        if timestamp.tzinfo is None:
            raise ValueError("break_timestamp_utc must be timezone-aware")
        if not 0.0 < float(self.pre_break_weight) <= 1.0:
            raise ValueError("pre_break_weight must be in (0,1]")


def structural_training_view(
    frame: pd.DataFrame,
    *,
    variant: str,
    config: StructuralBreakConfig = StructuralBreakConfig(),
) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    """Return a label-agnostic structural training view and deterministic row weights."""
    config.validate()
    if variant not in STRUCTURAL_VARIANTS:
        raise ValueError(f"Unsupported structural-break variant: {variant}")
    if "ts_close" not in frame.columns:
        raise ValueError("Structural-break frame requires ts_close")

    work = frame.copy().sort_values("ts_close", kind="stable").reset_index(drop=True)
    times = pd.to_datetime(work["ts_close"], utc=True)
    boundary = pd.Timestamp(config.break_timestamp_utc).tz_convert("UTC")
    before = times < boundary

    if variant == VARIANT_POST_BREAK_ONLY:
        view = work.loc[~before].copy().reset_index(drop=True)
        weights = np.ones(len(view), dtype=float)
        pre_rows = 0
        post_rows = int(len(view))
    else:
        view = work
        if variant == VARIANT_PRE_BREAK_DOWNWEIGHTED:
            weights = np.where(before.to_numpy(), float(config.pre_break_weight), 1.0).astype(float)
        else:
            weights = np.ones(len(view), dtype=float)
        pre_rows = int(before.sum())
        post_rows = int((~before).sum())

    metadata = {
        "method_version": METHOD_VERSION,
        "hypothesis_id": BSE_DERIVATIVES_RELAUNCH_HYPOTHESIS,
        "variant": variant,
        "break_timestamp_utc": boundary.isoformat(),
        "break_date_ist": "2023-05-15",
        "boundary_predeclared_from_external_business_event": True,
        "boundary_selected_using_model_performance": False,
        "pre_break_weight": float(config.pre_break_weight) if variant == VARIANT_PRE_BREAK_DOWNWEIGHTED else 1.0,
        "input_rows": int(len(frame)),
        "output_rows": int(len(view)),
        "pre_break_rows_in_view": pre_rows,
        "post_break_rows_in_view": post_rows,
        "labels_used_to_construct_view": False,
        "oos_used_to_choose_boundary": False,
        "holdout_used_to_choose_boundary": False,
        "full_history_control_required": True,
        "old_history_deleted": False,
        "automatic_promotion": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
        "config": asdict(config),
    }
    return view, weights, metadata


def structural_distribution_report(
    frame: pd.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    config: StructuralBreakConfig = StructuralBreakConfig(),
    discovery_end: str = "2025-01-01T00:00:00Z",
) -> dict[str, Any]:
    """Describe pre/post feature shifts using discovery-period features only.

    This is diagnostic evidence, not a test that proves causation and not a rule that chooses
    the break date.
    """
    config.validate()
    if "ts_close" not in frame.columns:
        raise ValueError("Structural-break frame requires ts_close")
    times = pd.to_datetime(frame["ts_close"], utc=True)
    boundary = pd.Timestamp(config.break_timestamp_utc).tz_convert("UTC")
    end = pd.Timestamp(discovery_end).tz_convert("UTC")
    eligible = frame.loc[times < end].copy()
    eligible_times = pd.to_datetime(eligible["ts_close"], utc=True)
    pre = eligible.loc[eligible_times < boundary]
    post = eligible.loc[eligible_times >= boundary]

    details: list[dict[str, Any]] = []
    for name in feature_columns:
        if name not in eligible.columns:
            continue
        left = pd.to_numeric(pre[name], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        right = pd.to_numeric(post[name], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if len(left) < 20 or len(right) < 20:
            continue
        left_mean = float(left.mean())
        right_mean = float(right.mean())
        pooled = max(float(left.std(ddof=0)), float(right.std(ddof=0)), 1e-12)
        details.append({
            "feature": name,
            "pre_rows": int(len(left)),
            "post_rows": int(len(right)),
            "pre_mean": left_mean,
            "post_mean": right_mean,
            "mean_shift_pooled_sigma": float(abs(right_mean - left_mean) / pooled),
            "pre_median": float(left.median()),
            "post_median": float(right.median()),
        })

    return {
        "method_version": METHOD_VERSION,
        "hypothesis_id": BSE_DERIVATIVES_RELAUNCH_HYPOTHESIS,
        "break_date_ist": "2023-05-15",
        "discovery_end": end.isoformat(),
        "pre_rows": int(len(pre)),
        "post_rows": int(len(post)),
        "features": details,
        "boundary_selected_using_model_performance": False,
        "oos_used": False,
        "holdout_used": False,
        "causal_break_claimed": False,
        "automatic_policy_change": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
