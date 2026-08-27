"""Population Stability Index (PSI) feature-drift helpers for Trade Brain v0.14 ML.

The reference distribution must be built from the discovery sample (TRAIN + VALIDATION), not
OOS or holdout.  PSI is observational evidence for deciding whether a separate research
retraining cycle is justified.  It never mutates a model or trading policy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

METHOD_VERSION = "BSE_ML_PSI_DRIFT_V1"
CORE_DRIFT_FEATURES = (
    "natr_14_pct",
    "atr_14",
    "relative_volume_20",
    "candle_range_pct",
    "vwap_distance_pct",
)


@dataclass(frozen=True)
class PSIDriftConfig:
    bins: int = 10
    watch_threshold: float = 0.10
    alert_threshold: float = 0.25
    min_reference_rows: int = 100
    min_recent_rows: int = 20
    epsilon: float = 1e-6

    def validate(self) -> None:
        if self.bins < 3:
            raise ValueError("PSI bins must be >= 3")
        if not 0.0 < self.watch_threshold < self.alert_threshold:
            raise ValueError("PSI thresholds must satisfy 0 < watch < alert")
        if self.min_reference_rows < 20 or self.min_recent_rows < 10:
            raise ValueError("PSI minimum row counts are too small")
        if self.epsilon <= 0.0:
            raise ValueError("PSI epsilon must be positive")


def _finite(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return values.to_numpy(dtype=float)


def _edges(values: np.ndarray, bins: int) -> np.ndarray:
    quantiles = np.linspace(0.0, 1.0, int(bins) + 1)
    raw = np.quantile(values, quantiles)
    unique = np.unique(raw)
    if len(unique) < 3:
        return np.asarray([], dtype=float)
    internal = unique[1:-1]
    return np.concatenate(([-np.inf], internal, [np.inf])).astype(float)


def _proportions(values: np.ndarray, edges: np.ndarray, epsilon: float) -> np.ndarray:
    counts, _ = np.histogram(values, bins=edges)
    proportions = counts.astype(float) / max(1, int(counts.sum()))
    proportions = np.maximum(proportions, float(epsilon))
    return proportions / proportions.sum()


def build_psi_baseline(
    frame: pd.DataFrame,
    feature_columns: Iterable[str],
    *,
    config: PSIDriftConfig = PSIDriftConfig(),
) -> dict[str, Any]:
    """Build quantile-bin reference distributions from discovery data only."""

    config.validate()
    allowed = set(str(x) for x in feature_columns)
    features: dict[str, Any] = {}
    for name in CORE_DRIFT_FEATURES:
        if name not in allowed or name not in frame.columns:
            continue
        values = _finite(frame[name])
        if len(values) < config.min_reference_rows:
            continue
        edges = _edges(values, config.bins)
        if len(edges) < 3:
            continue
        expected = _proportions(values, edges, config.epsilon)
        features[name] = {
            "reference_rows": int(len(values)),
            "bin_edges": [float(x) for x in edges],
            "expected_proportions": [float(x) for x in expected],
        }
    return {
        "method_version": METHOD_VERSION,
        "config": asdict(config),
        "features": features,
        "reference_period": "TRAIN_PLUS_VALIDATION_ONLY",
        "oos_used": False,
        "holdout_used": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def psi_feature_report(
    recent: pd.DataFrame,
    baseline: dict[str, Any] | None,
    *,
    config: PSIDriftConfig = PSIDriftConfig(),
) -> dict[str, Any]:
    """Calculate PSI for core features against a stored discovery baseline."""

    config.validate()
    stored = baseline or {}
    features = stored.get("features") or {}
    if not features:
        return {
            "status": "BASELINE_NOT_AVAILABLE",
            "method_version": METHOD_VERSION,
            "details": [],
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    details: list[dict[str, Any]] = []
    alerts = watches = 0
    for name, reference in features.items():
        if name not in recent.columns:
            details.append({"feature": name, "status": "MISSING_CURRENT_FEATURE", "psi": None})
            alerts += 1
            continue
        values = _finite(recent[name])
        if len(values) < config.min_recent_rows:
            details.append({
                "feature": name,
                "status": "INSUFFICIENT_RECENT_ROWS",
                "psi": None,
                "recent_rows": int(len(values)),
            })
            continue
        edges = np.asarray(reference.get("bin_edges") or [], dtype=float)
        expected = np.asarray(reference.get("expected_proportions") or [], dtype=float)
        if len(edges) < 3 or len(expected) != len(edges) - 1:
            details.append({"feature": name, "status": "MALFORMED_BASELINE", "psi": None})
            alerts += 1
            continue
        observed = _proportions(values, edges, config.epsilon)
        expected_safe = np.maximum(expected, config.epsilon)
        expected_safe = expected_safe / expected_safe.sum()
        psi_terms = (observed - expected_safe) * np.log(observed / expected_safe)
        psi = float(np.sum(psi_terms))
        if psi >= config.alert_threshold:
            status = "DRIFT_ALERT"
            alerts += 1
        elif psi >= config.watch_threshold:
            status = "WATCH"
            watches += 1
        else:
            status = "STABLE"
        details.append({
            "feature": name,
            "status": status,
            "psi": psi,
            "recent_rows": int(len(values)),
            "reference_rows": int(reference.get("reference_rows") or 0),
            "observed_proportions": [float(x) for x in observed],
        })

    overall = "DRIFT_ALERT" if alerts else ("WATCH" if watches else "STABLE")
    return {
        "status": overall,
        "method_version": METHOD_VERSION,
        "features_checked": len(details),
        "features_alert": alerts,
        "features_watch": watches,
        "details": details,
        "reference_period": stored.get("reference_period"),
        "oos_used_in_reference": bool(stored.get("oos_used")),
        "holdout_used_in_reference": bool(stored.get("holdout_used")),
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
