"""Shadow inference and prospective evidence logging for Trade Brain v0.14 ML.

Shadow evidence is informational only. It cannot place orders, modify protected rules, or
change advisory weights. Feature/artifact mismatches fail closed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from backend.tradebrain.ml_features import FeatureBundle
from backend.tradebrain.ml_models import feature_schema_hash, predict_positive_probability
from backend.tradebrain.ml_registry import (
    STAGE_CHAMPION,
    STAGE_ELIGIBLE,
    STAGE_SHADOW,
    load_model,
)

METHOD_VERSION = "BSE_ML_SHADOW_V1"
_ALLOWED = {STAGE_SHADOW, STAGE_ELIGIBLE, STAGE_CHAMPION}
IST = ZoneInfo("Asia/Kolkata")


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".tradingagents" / "tradebrain"


def default_shadow_log_path() -> Path:
    path = _data_root() / "ml_shadow" / "predictions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def _session_ist(value: Any) -> str:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed.tz_convert(IST).date().isoformat()


def shadow_infer(
    model_id: str,
    bundle: FeatureBundle,
    *,
    registry_root: str | Path | None = None,
    persist: bool = True,
    log_path: str | Path | None = None,
) -> dict[str, Any]:
    model, metadata = load_model(model_id, root=registry_root)
    stage = str(metadata.get("stage") or "")
    if stage not in _ALLOWED:
        raise PermissionError(f"ML artifact is not shadow-enabled: {stage or 'UNKNOWN'}")

    expected_columns = tuple(str(x) for x in metadata.get("feature_columns") or [])
    if not expected_columns:
        raise ValueError("ML artifact has no feature schema")
    if feature_schema_hash(expected_columns) != str(metadata.get("feature_schema_hash") or ""):
        raise ValueError("ML artifact feature schema hash is inconsistent")

    missing = [name for name in expected_columns if name not in bundle.frame.columns]
    if missing:
        raise ValueError(f"Current feature bundle is incompatible with artifact: {missing[:12]}")
    expected_method = metadata.get("feature_method_version")
    actual_method = bundle.metadata.get("method_version")
    if expected_method and actual_method and str(expected_method) != str(actual_method):
        raise ValueError(
            f"Feature method mismatch: artifact={expected_method} current={actual_method}"
        )
    if bundle.frame.empty:
        raise ValueError("Current feature bundle has no completed bars")

    row = bundle.frame.tail(1).copy()
    as_of = str(row.iloc[0].get("ts_close"))
    probability = float(
        predict_positive_probability(model, row, feature_columns=expected_columns)[0]
    )
    threshold = float(metadata.get("probability_threshold") or 0.5)
    oos = metadata.get("oos") or {}
    model_sha256 = str(metadata.get("model_sha256") or "")
    if not model_sha256:
        raise ValueError("ML artifact metadata has no model hash; refusing unauditable shadow inference")
    result = {
        "method_version": METHOD_VERSION,
        "model_id": metadata["model_id"],
        "model_sha256": model_sha256,
        "model_status": stage,
        "task": metadata.get("task"),
        "as_of": as_of,
        "shadow_session_ist": _session_ist(as_of),
        "probability_net_positive": probability,
        "probability_threshold": threshold,
        "model_signal": "POSITIVE_EDGE" if probability >= threshold else "NO_MODEL_EDGE",
        "oos_mean_net_return_pct": oos.get("mean_net_return_pct"),
        "oos_profit_factor": oos.get("profit_factor"),
        "oos_brier_score": oos.get("brier_score"),
        "dataset_snapshot_hash": metadata.get("dataset_snapshot_hash"),
        "feature_schema_hash": metadata.get("feature_schema_hash"),
        "feature_method_version": actual_method,
        "retuned_during_shadow_session": False,
        "shadow_only": True,
        "advisory_weight_applied": False,
        "automatic_policy_change": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
    if persist:
        path = Path(log_path).expanduser() if log_path else default_shadow_log_path()
        record = {
            **result,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _append_jsonl(path, record)
        result["shadow_log_path"] = str(path)
    return result


def load_shadow_predictions(
    *,
    model_id: str | None = None,
    path: str | Path | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    source = Path(path).expanduser() if path else default_shadow_log_path()
    if not source.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if model_id and str(item.get("model_id")) != str(model_id):
            continue
        rows.append(item)
    return rows[-max(1, int(limit)) :]
