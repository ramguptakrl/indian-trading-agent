"""Research-only sample weighting for Trade Brain v0.14 ML.

Weights combine (1) economic significance after modeled friction and (2) temporal uniqueness
of the label window.  This is a challenger experiment only; the frozen baseline optimizer is
unchanged until weighted models prove themselves under the same chronology, stress, CPCV,
and replay gates.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable

import numpy as np
import pandas as pd

from backend.tradebrain.ml_models import DEFAULT_RANDOM_STATE, ModelSpec, build_model

METHOD_VERSION = "BSE_ML_SAMPLE_WEIGHTING_V1"


@dataclass(frozen=True)
class WeightingConfig:
    min_weight: float = 0.25
    max_weight: float = 4.0
    friction_floor_pct: float = 0.01
    economic_power: float = 0.5
    uniqueness_power: float = 1.0

    def validate(self) -> None:
        if not 0.0 < self.min_weight <= self.max_weight:
            raise ValueError("weight bounds are invalid")
        if self.friction_floor_pct <= 0.0:
            raise ValueError("friction_floor_pct must be positive")
        if self.economic_power < 0.0 or self.uniqueness_power < 0.0:
            raise ValueError("weight powers must be non-negative")


def _numeric_matrix(frame: pd.DataFrame, feature_columns: Iterable[str]) -> pd.DataFrame:
    columns = tuple(str(value) for value in feature_columns)
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise ValueError(f"Feature frame missing columns: {missing[:12]}")
    work = frame.loc[:, list(columns)].copy()
    for column in columns:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    return work


def temporal_uniqueness_weights(frame: pd.DataFrame) -> np.ndarray:
    """Approximate sample uniqueness as inverse active label-window concurrency at entry."""

    required = {"ts_close", "label_end"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Weighting frame missing chronology columns: {sorted(missing)}")
    starts = pd.to_datetime(frame["ts_close"], utc=True)
    ends = pd.to_datetime(frame["label_end"], utc=True)
    if (ends < starts).any():
        raise ValueError("label_end cannot precede ts_close")

    order = np.argsort(starts.to_numpy())
    sorted_starts = starts.iloc[order].reset_index(drop=True)
    sorted_ends = ends.iloc[order].reset_index(drop=True)
    active_ends: list[pd.Timestamp] = []
    sorted_weights = np.ones(len(frame), dtype=float)

    for idx, start in enumerate(sorted_starts):
        active_ends = [end for end in active_ends if end >= start]
        active_ends.append(sorted_ends.iloc[idx])
        sorted_weights[idx] = 1.0 / float(len(active_ends))

    weights = np.empty(len(frame), dtype=float)
    weights[order] = sorted_weights
    return weights


def friction_aware_sample_weights(
    frame: pd.DataFrame,
    *,
    config: WeightingConfig = WeightingConfig(),
) -> tuple[np.ndarray, dict[str, Any]]:
    """Build normalized weights using only already-matured training outcomes."""

    config.validate()
    required = {"label_gross_return_pct", "label_net_return_pct", "ts_close", "label_end"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Weighting frame missing columns: {sorted(missing)}")

    gross = pd.to_numeric(frame["label_gross_return_pct"], errors="coerce").to_numpy(dtype=float)
    net = pd.to_numeric(frame["label_net_return_pct"], errors="coerce").to_numpy(dtype=float)
    friction = np.maximum(np.abs(gross - net), float(config.friction_floor_pct))
    economic_ratio = np.abs(net) / friction
    economic = np.power(np.maximum(economic_ratio, 1e-12), float(config.economic_power))
    uniqueness = temporal_uniqueness_weights(frame)
    combined = economic * np.power(np.maximum(uniqueness, 1e-12), float(config.uniqueness_power))

    finite = np.isfinite(combined) & (combined > 0.0)
    if not finite.all():
        replacement = float(np.nanmedian(combined[finite])) if finite.any() else 1.0
        combined = np.where(finite, combined, replacement)
    mean = float(np.mean(combined)) or 1.0
    weights = combined / mean
    weights = np.clip(weights, float(config.min_weight), float(config.max_weight))
    weights = weights / (float(np.mean(weights)) or 1.0)

    return weights.astype(float), {
        "method_version": METHOD_VERSION,
        "config": asdict(config),
        "rows": int(len(frame)),
        "mean_weight": float(np.mean(weights)) if len(weights) else 0.0,
        "min_weight": float(np.min(weights)) if len(weights) else 0.0,
        "max_weight": float(np.max(weights)) if len(weights) else 0.0,
        "mean_uniqueness": float(np.mean(uniqueness)) if len(uniqueness) else 0.0,
        "uses_matured_outcomes_only": True,
        "future_features_used": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def fit_friction_weighted_model(
    frame: pd.DataFrame,
    *,
    feature_columns: Iterable[str],
    spec: ModelSpec,
    target_column: str = "label_net_positive",
    random_state: int = DEFAULT_RANDOM_STATE,
    config: WeightingConfig = WeightingConfig(),
):
    """Fit a research challenger using sklearn's estimator-level sample_weight support."""

    if target_column not in frame.columns:
        raise ValueError(f"Training frame missing target column: {target_column}")
    if len(frame) < 20:
        raise ValueError("At least 20 chronological training rows are required")
    y = pd.to_numeric(frame[target_column], errors="raise").astype(int).to_numpy()
    if set(y.tolist()) != {0, 1}:
        raise ValueError("Training labels must contain both positive and negative outcomes")
    weights, metadata = friction_aware_sample_weights(frame, config=config)
    model = build_model(spec, random_state=random_state)
    model.fit(_numeric_matrix(frame, feature_columns), y, model__sample_weight=weights)
    return model, metadata
