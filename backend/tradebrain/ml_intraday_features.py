"""Compact, leakage-safe feature challenger for noisy intraday BSE tasks.

This is deliberately a challenger, not a replacement for the full feature engine.  It uses
only fields already produced point-in-time by Trade Brain and prunes highly correlated
signals without looking at labels or future outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle

METHOD_VERSION = "BSE_ML_INTRADAY_COMPACT_V1"

# Ordered by structural usefulness.  No synthetic order-flow feature is claimed because the
# audited historical store currently contains OHLCV, not historical order-book imbalance.
CORE_INTRADAY_FEATURE_PRIORITY = (
    "mtf_alignment_score",
    "mtf_daily_trend",
    "mtf_4h_trend",
    "mtf_1h_trend",
    "relative_volume_20",
    "natr_14_pct",
    "vwap_distance_pct",
    "opening_range_position",
    "distance_prev_high_pct",
    "distance_prev_low_pct",
    "gap_pct",
    "adx_14",
    "dmi_spread",
    "rsi_14",
    "macd_hist",
)


@dataclass(frozen=True)
class CompactFeatureConfig:
    max_features: int = 15
    max_abs_correlation: float = 0.92
    min_features: int = 8

    def validate(self) -> None:
        if self.max_features < 1 or self.min_features < 1:
            raise ValueError("feature counts must be positive")
        if self.min_features > self.max_features:
            raise ValueError("min_features cannot exceed max_features")
        if not 0.0 < self.max_abs_correlation < 1.0:
            raise ValueError("max_abs_correlation must be in (0,1)")


def compact_feature_columns(
    bundle: FeatureBundle,
    *,
    config: CompactFeatureConfig = CompactFeatureConfig(),
) -> tuple[str, ...]:
    """Select core features using only contemporaneous feature values, never labels."""

    config.validate()
    available = [name for name in CORE_INTRADAY_FEATURE_PRIORITY if name in bundle.feature_columns]
    if not available:
        return ()

    frame = bundle.frame
    selected: list[str] = []
    for candidate in available:
        if len(selected) >= config.max_features:
            break
        values = pd.to_numeric(frame[candidate], errors="coerce").replace([np.inf, -np.inf], np.nan)
        if values.notna().sum() < 20:
            continue
        reject = False
        for existing in selected:
            other = pd.to_numeric(frame[existing], errors="coerce").replace([np.inf, -np.inf], np.nan)
            pair = pd.concat([values, other], axis=1).dropna()
            if len(pair) < 20:
                continue
            corr = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
            if np.isfinite(corr) and abs(corr) >= config.max_abs_correlation:
                reject = True
                break
        if not reject:
            selected.append(candidate)
    return tuple(selected)


def compact_intraday_bundle(
    bundle: FeatureBundle,
    *,
    config: CompactFeatureConfig = CompactFeatureConfig(),
) -> FeatureBundle:
    """Return the same point-in-time rows with a compact feature schema for challenger tests."""

    task = str(bundle.metadata.get("task") or "")
    if task not in {"BSE_INTRADAY_LONG", "BSE_INTRADAY_SHORT"}:
        raise ValueError("Compact intraday feature challenger is only for intraday tasks")
    columns = compact_feature_columns(bundle, config=config)
    if len(columns) < config.min_features:
        raise ValueError(
            f"Insufficient reproducible compact intraday features: {len(columns)} < {config.min_features}"
        )
    metadata: dict[str, Any] = dict(bundle.metadata)
    metadata.update(
        {
            "compact_feature_method_version": METHOD_VERSION,
            "compact_feature_config": asdict(config),
            "compact_feature_columns": list(columns),
            "feature_selection_used_labels": False,
            "feature_selection_used_future_outcomes": False,
            "order_flow_imbalance_claimed": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    )
    return FeatureBundle(frame=bundle.frame.copy(), feature_columns=columns, metadata=metadata)
