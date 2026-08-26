"""Drift and degradation monitoring for Trade Brain v0.14 ML.

Monitoring is observational. Alerts can downgrade trust in a model but can never promote a
model, rewrite hard policy, or grant broker/order authority.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_models import feature_schema_hash
from backend.tradebrain.ml_registry import read_metadata
from backend.tradebrain.ml_shadow import load_shadow_predictions
from backend.tradebrain.ml_validation import max_drawdown_from_returns, worst_losing_streak

METHOD_VERSION = "BSE_ML_DRIFT_V1"


def _finite(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def feature_drift_report(
    model_id: str,
    bundle: FeatureBundle,
    *,
    registry_root: str | Path | None = None,
    recent_rows: int = 100,
) -> dict[str, Any]:
    metadata = read_metadata(model_id, root=registry_root)
    columns = tuple(str(x) for x in metadata.get("feature_columns") or [])
    if not columns:
        raise ValueError("ML artifact has no feature schema")
    if feature_schema_hash(columns) != str(metadata.get("feature_schema_hash") or ""):
        raise ValueError("ML artifact feature schema hash is inconsistent")
    missing = [name for name in columns if name not in bundle.frame.columns]
    if missing:
        raise ValueError(f"Current feature bundle is incompatible with artifact: {missing[:12]}")
    baseline = metadata.get("feature_baseline") or {}
    if not baseline:
        return {
            "status": "BASELINE_NOT_AVAILABLE",
            "method_version": METHOD_VERSION,
            "model_id": model_id,
            "automatic_policy_change": False,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    recent = bundle.frame.tail(max(20, int(recent_rows))).copy()
    details: list[dict[str, Any]] = []
    severe = watch = 0
    for column in columns:
        base = baseline.get(column) or {}
        values = _finite(recent[column])
        if values.empty or base.get("mean") is None:
            details.append({"feature": column, "status": "INSUFFICIENT", "rows": int(len(values))})
            continue
        current_mean = float(values.mean())
        current_std = float(values.std(ddof=0))
        base_mean = float(base["mean"])
        base_std = abs(float(base.get("std") or 0.0))
        scale = max(base_std, abs(base_mean) * 0.05, 1e-9)
        mean_shift_sigma = abs(current_mean - base_mean) / scale
        missing_pct = float((1.0 - len(values) / max(1, len(recent))) * 100.0)
        missing_delta = abs(missing_pct - float(base.get("missing_pct") or 0.0))
        p05, p95 = base.get("p05"), base.get("p95")
        outside_pct = 0.0
        if p05 is not None and p95 is not None:
            outside_pct = float(((values < float(p05)) | (values > float(p95))).mean() * 100.0)
        if mean_shift_sigma >= 2.5 or outside_pct >= 40.0 or missing_delta >= 20.0:
            status = "DRIFT_ALERT"
            severe += 1
        elif mean_shift_sigma >= 1.5 or outside_pct >= 25.0 or missing_delta >= 10.0:
            status = "WATCH"
            watch += 1
        else:
            status = "STABLE"
        details.append({
            "feature": column,
            "status": status,
            "baseline_mean": base_mean,
            "current_mean": current_mean,
            "baseline_std": base_std,
            "current_std": current_std,
            "mean_shift_sigma": float(mean_shift_sigma),
            "outside_baseline_p05_p95_pct": outside_pct,
            "baseline_missing_pct": float(base.get("missing_pct") or 0.0),
            "current_missing_pct": missing_pct,
            "missing_delta_pct": missing_delta,
        })
    overall = "DRIFT_ALERT" if severe else ("WATCH" if watch else "STABLE")
    return {
        "status": overall,
        "method_version": METHOD_VERSION,
        "model_id": model_id,
        "model_stage": metadata.get("stage"),
        "recent_rows": int(len(recent)),
        "features_checked": len(details),
        "features_alert": severe,
        "features_watch": watch,
        "details": details,
        "automatic_policy_change": False,
        "human_review_required_on_alert": True,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def shadow_performance_report(
    model_id: str,
    labeled_bundle: FeatureBundle,
    *,
    registry_root: str | Path | None = None,
    shadow_log_path: str | Path | None = None,
    min_matured: int = 20,
) -> dict[str, Any]:
    metadata = read_metadata(model_id, root=registry_root)
    predictions = load_shadow_predictions(model_id=model_id, path=shadow_log_path)
    if not predictions:
        return {
            "status": "NO_SHADOW_PREDICTIONS",
            "method_version": METHOD_VERSION,
            "model_id": model_id,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    labels = labeled_bundle.frame.copy()
    labels["_key"] = pd.to_datetime(labels["ts_close"], utc=True).astype(str)
    by_time = {str(row["_key"]): row for _, row in labels.iterrows()}
    matured = []
    for prediction in predictions:
        try:
            key = str(pd.Timestamp(prediction.get("as_of")).tz_convert("UTC"))
        except Exception:
            continue
        row = by_time.get(key)
        if row is None:
            continue
        matured.append((prediction, row))
    if len(matured) < int(min_matured):
        return {
            "status": "INSUFFICIENT_MATURED_SHADOW",
            "method_version": METHOD_VERSION,
            "model_id": model_id,
            "matured": len(matured),
            "required": int(min_matured),
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    probs = np.asarray([float(p["probability_net_positive"]) for p, _ in matured], dtype=float)
    y = np.asarray([int(r["label_net_positive"]) for _, r in matured], dtype=int)
    selected = np.asarray([str(p.get("model_signal")) == "POSITIVE_EDGE" for p, _ in matured], dtype=bool)
    returns = np.asarray([float(r["label_net_return_pct"]) for _, r in matured], dtype=float)[selected]
    brier = float(brier_score_loss(y, probs))
    calibration_gap = float(abs(float(np.mean(probs)) - float(np.mean(y))))
    expectancy = float(np.mean(returns)) if len(returns) else 0.0
    win_rate = float((returns > 0.0).mean() * 100.0) if len(returns) else 0.0
    drawdown = max_drawdown_from_returns(returns)
    streak = worst_losing_streak(returns)
    oos = metadata.get("oos") or {}
    alerts = []
    watches = []
    oos_brier = oos.get("brier_score")
    if oos_brier is not None and brier > max(float(oos_brier) * 1.35, float(oos_brier) + 0.05):
        alerts.append("CALIBRATION_DRIFT")
    elif oos_brier is not None and brier > max(float(oos_brier) * 1.20, float(oos_brier) + 0.03):
        watches.append("CALIBRATION_WATCH")
    oos_expectancy = float(oos.get("mean_net_return_pct") or 0.0)
    if expectancy < 0.0 or (oos_expectancy > 0.0 and expectancy < oos_expectancy * 0.5):
        alerts.append("EXPECTANCY_DEGRADATION")
    elif oos_expectancy > 0.0 and expectancy < oos_expectancy * 0.75:
        watches.append("EXPECTANCY_WATCH")
    oos_win = float(oos.get("win_rate_pct") or 0.0)
    if oos_win and win_rate < oos_win - 15.0:
        alerts.append("WIN_RATE_DRIFT")
    elif oos_win and win_rate < oos_win - 8.0:
        watches.append("WIN_RATE_WATCH")
    oos_dd = float(oos.get("max_drawdown_pct") or 0.0)
    if drawdown > max(oos_dd * 1.5, oos_dd + 5.0):
        alerts.append("DRAWDOWN_DEGRADATION")
    oos_streak = int(oos.get("worst_losing_streak") or 0)
    if streak > max(oos_streak + 3, 5):
        alerts.append("LOSING_STREAK_DEGRADATION")
    status = "DRIFT_ALERT" if alerts else ("WATCH" if watches else "STABLE")
    return {
        "status": status,
        "method_version": METHOD_VERSION,
        "model_id": model_id,
        "matured": len(matured),
        "selected_trades": int(selected.sum()),
        "brier_score": brier,
        "calibration_gap": calibration_gap,
        "realized_mean_net_return_pct": expectancy,
        "realized_win_rate_pct": win_rate,
        "realized_max_drawdown_pct": drawdown,
        "realized_worst_losing_streak": streak,
        "alerts": alerts,
        "watches": watches,
        "automatic_policy_change": False,
        "human_review_required_on_alert": True,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def model_drift_report(
    model_id: str,
    current_features: FeatureBundle,
    *,
    labeled_bundle: FeatureBundle | None = None,
    registry_root: str | Path | None = None,
    shadow_log_path: str | Path | None = None,
    recent_rows: int = 100,
) -> dict[str, Any]:
    feature = feature_drift_report(model_id, current_features, registry_root=registry_root, recent_rows=recent_rows)
    performance = None
    if labeled_bundle is not None:
        performance = shadow_performance_report(model_id, labeled_bundle, registry_root=registry_root, shadow_log_path=shadow_log_path)
    states = {str(feature.get("status")), str((performance or {}).get("status"))}
    overall = "DRIFT_ALERT" if "DRIFT_ALERT" in states else ("WATCH" if "WATCH" in states else "STABLE")
    return {
        "status": overall,
        "method_version": METHOD_VERSION,
        "model_id": model_id,
        "feature_drift": feature,
        "shadow_performance": performance,
        "automatic_retraining": False,
        "automatic_promotion": False,
        "automatic_policy_change": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
