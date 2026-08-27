"""Versioned local artifact registry for Trade Brain v0.14 ML.

Artifacts live under TRADEBRAIN_DATA_DIR and are never broker commands. Promotion is staged,
audited, and cannot reach CHAMPION without explicit human approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from backend.tradebrain.ml_models import METHOD_VERSION as MODEL_METHOD_VERSION, feature_schema_hash
from backend.tradebrain.ml_optimizer import OptimizationResult, serializable_result
from backend.tradebrain.ml_promotion import DEFAULT_PROMOTION_THRESHOLDS

METHOD_VERSION = "BSE_ML_REGISTRY_V1"

STAGE_RESEARCH = "RESEARCH_CANDIDATE"
STAGE_HISTORICAL_PASS = "HISTORICAL_WALKFORWARD_PASS"
STAGE_FROZEN = "FROZEN_CHALLENGER"
STAGE_SHADOW = "SHADOW"
STAGE_ELIGIBLE = "ELIGIBLE_FOR_HUMAN_APPROVED_INTEGRATION"
STAGE_CHAMPION = "CHAMPION"

STAGES = (
    STAGE_RESEARCH,
    STAGE_HISTORICAL_PASS,
    STAGE_FROZEN,
    STAGE_SHADOW,
    STAGE_ELIGIBLE,
    STAGE_CHAMPION,
)

_SAFE_MODEL_ID = re.compile(r"^[A-Z0-9_:-]{8,160}$")


def registry_root(path: str | Path | None = None) -> Path:
    if path is not None:
        root = Path(path).expanduser()
    else:
        configured = os.getenv("TRADEBRAIN_DATA_DIR")
        base = Path(configured).expanduser() if configured else Path.home() / ".tradingagents" / "tradebrain"
        root = base / "ml_registry"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _atomic_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _safe_id(model_id: str) -> str:
    value = str(model_id).strip().upper()
    if not _SAFE_MODEL_ID.match(value):
        raise ValueError("Unsafe or invalid ML model_id")
    return value


def _dir(model_id: str, root: str | Path | None = None) -> Path:
    return registry_root(root) / _safe_id(model_id)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _walk_forward_pass(rows: list[dict[str, Any]]) -> bool:
    if len(rows) < 2:
        return False
    positive = 0
    robust = 0
    for row in rows:
        normal = row.get("normal") or {}
        stress = row.get("stress_15x") or {}
        if float(normal.get("mean_net_return_pct") or 0.0) > 0.0:
            positive += 1
        if float(stress.get("mean_net_return_pct") or 0.0) > 0.0:
            robust += 1
    required = max(2, (len(rows) + 1) // 2)
    return positive >= required and robust >= required


def _model_id(result: OptimizationResult) -> str:
    if not result.winner:
        raise ValueError("Cannot create model ID without optimizer winner")
    payload = {
        "task": result.task,
        "dataset": result.metadata.get("dataset_snapshot_hash"),
        "family": result.winner.get("family"),
        "params": result.winner.get("params"),
        "features": list(result.feature_columns),
        "threshold": result.winner.get("threshold"),
        "optimizer_method": result.metadata.get("method_version"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:12].upper()
    return f"{result.task}_{digest}"


def register_optimization(
    result: OptimizationResult,
    *,
    code_version: str,
    root: str | Path | None = None,
) -> dict[str, Any]:
    if result.model is None or result.winner is None:
        raise ValueError("Only fitted optimizer candidates can be registered")
    if result.status not in {"OOS_PASS", "OOS_REJECTED"}:
        raise ValueError(f"Optimizer result is not registerable: {result.status}")

    model_id = _model_id(result)
    directory = _dir(model_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / "model.joblib"
    joblib.dump(result.model, model_path, compress=3)
    model_sha = _hash_file(model_path)

    feature_hash = feature_schema_hash(result.feature_columns)
    created = datetime.now(timezone.utc).isoformat()
    metadata = {
        "registry_method_version": METHOD_VERSION,
        "model_method_version": MODEL_METHOD_VERSION,
        "model_id": model_id,
        "task": result.task,
        "stage": STAGE_RESEARCH,
        "created_at": created,
        "updated_at": created,
        "code_version": str(code_version),
        "model_sha256": model_sha,
        "family": result.winner.get("family"),
        "hyperparameters": result.winner.get("params") or {},
        "probability_threshold": result.winner.get("threshold"),
        "feature_columns": list(result.feature_columns),
        "feature_schema_hash": feature_hash,
        "dataset_snapshot_hash": result.metadata.get("dataset_snapshot_hash"),
        "feature_method_version": result.metadata.get("feature_method_version"),
        "label_method_version": result.metadata.get("label_method_version"),
        "label_spec": result.metadata.get("label_spec"),
        "cost_profile_key": result.metadata.get("cost_profile_key"),
        "mtf_profile_key": result.metadata.get("mtf_profile_key"),
        "chronology_rows": result.metadata.get("rows") or {},
        "holdout_evaluated": False,
        "oos_used_for_hyperparameter_selection": False,
        "validation": result.winner.get("validation"),
        "oos": result.oos_metrics,
        "oos_stress_15x": result.oos_stress_15x,
        "oos_stress_20x": result.oos_stress_20x,
        "walk_forward": result.walk_forward,
        "feature_baseline": result.metadata.get("feature_baseline") or {},
        "historical_walk_forward_pass": bool(
            result.status == "OOS_PASS" and _walk_forward_pass(result.walk_forward)
        ),
        "promotion_quality": None,
        "cpcv_robustness": None,
        "shadow_buffer_evidence": None,
        "promotion_history": [
            {
                "at": created,
                "from": None,
                "to": STAGE_RESEARCH,
                "reason": "REGISTERED_OPTIMIZER_OUTPUT",
                "human_approved": False,
            }
        ],
        "automatic_policy_change": False,
        "advisory_weight_enabled": False,
        "human_review_required_for_advisory_integration": True,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
    _atomic_json(directory / "metadata.json", metadata)
    _atomic_json(directory / "trials.json", serializable_result(result)["trials"])
    _atomic_json(
        directory / "result_summary.json",
        {k: v for k, v in serializable_result(result).items() if k != "trials"},
    )
    return metadata


def read_metadata(model_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    path = _dir(model_id, root) / "metadata.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown ML model artifact: {model_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("ML artifact metadata is malformed")
    return data


def load_model(model_id: str, *, root: str | Path | None = None):
    directory = _dir(model_id, root)
    metadata = read_metadata(model_id, root=root)
    path = directory / "model.joblib"
    if not path.exists():
        raise FileNotFoundError(f"ML model payload missing: {model_id}")
    actual = _hash_file(path)
    if actual != metadata.get("model_sha256"):
        raise ValueError("ML model artifact hash mismatch; refusing stale/tampered model")
    return joblib.load(path), metadata


def _transition(
    model_id: str,
    *,
    target: str,
    reason: str,
    human_approved: bool,
    root: str | Path | None,
    evidence_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = read_metadata(model_id, root=root)
    if evidence_updates:
        metadata.update(evidence_updates)
    current = str(metadata.get("stage"))
    allowed = {
        STAGE_RESEARCH: {STAGE_HISTORICAL_PASS},
        STAGE_HISTORICAL_PASS: {STAGE_FROZEN},
        STAGE_FROZEN: {STAGE_SHADOW},
        STAGE_SHADOW: {STAGE_ELIGIBLE},
        STAGE_ELIGIBLE: {STAGE_CHAMPION},
        STAGE_CHAMPION: set(),
    }
    if target not in allowed.get(current, set()):
        raise ValueError(f"Invalid ML promotion transition: {current} -> {target}")
    if target == STAGE_HISTORICAL_PASS:
        if not metadata.get("historical_walk_forward_pass"):
            raise ValueError("Historical/OOS robustness criteria are not satisfied")
        if not bool((metadata.get("promotion_quality") or {}).get("passed")):
            raise ValueError("Hardened historical promotion-quality gate is not satisfied")
        if not bool((metadata.get("cpcv_robustness") or {}).get("passed")):
            raise ValueError("Purged CPCV robustness gate is not satisfied")
    if target in {STAGE_FROZEN, STAGE_ELIGIBLE, STAGE_CHAMPION} and not human_approved:
        raise PermissionError(f"{target} requires explicit human approval")
    if target == STAGE_SHADOW and current != STAGE_FROZEN:
        raise ValueError("Only a frozen challenger may enter shadow mode")
    if target == STAGE_ELIGIBLE:
        shadow = metadata.get("shadow_buffer_evidence") or {}
        if not bool(shadow.get("passed")):
            raise ValueError("30-session prospective shadow buffer has not passed")
        if int(shadow.get("continuous_trailing_market_sessions") or 0) < int(
            DEFAULT_PROMOTION_THRESHOLDS.min_shadow_sessions
        ):
            raise ValueError("Prospective shadow buffer is shorter than the required market sessions")
        hashes = list(shadow.get("artifact_hashes_seen") or [])
        if hashes != [str(metadata.get("model_sha256") or "")]:
            raise ValueError("Shadow buffer was not produced by one unchanged frozen artifact")

    now = datetime.now(timezone.utc).isoformat()
    metadata["stage"] = target
    metadata["updated_at"] = now
    metadata["advisory_weight_enabled"] = bool(target == STAGE_CHAMPION and human_approved)
    history = list(metadata.get("promotion_history") or [])
    history.append(
        {
            "at": now,
            "from": current,
            "to": target,
            "reason": str(reason)[:500],
            "human_approved": bool(human_approved),
        }
    )
    metadata["promotion_history"] = history
    _atomic_json(_dir(model_id, root) / "metadata.json", metadata)
    return metadata


def mark_historical_pass(
    model_id: str,
    *,
    promotion_quality: dict[str, Any],
    cpcv_robustness: dict[str, Any],
    root: str | Path | None = None,
) -> dict[str, Any]:
    return _transition(
        model_id,
        target=STAGE_HISTORICAL_PASS,
        reason="OOS_WALK_FORWARD_HARD_GATE_AND_CPCV_PASS",
        human_approved=False,
        root=root,
        evidence_updates={
            "promotion_quality": dict(promotion_quality),
            "cpcv_robustness": dict(cpcv_robustness),
        },
    )


def freeze_challenger(
    model_id: str,
    *,
    reason: str,
    human_approved: bool,
    root: str | Path | None = None,
) -> dict[str, Any]:
    return _transition(
        model_id,
        target=STAGE_FROZEN,
        reason=reason,
        human_approved=human_approved,
        root=root,
    )


def enable_shadow(model_id: str, *, root: str | Path | None = None) -> dict[str, Any]:
    return _transition(
        model_id,
        target=STAGE_SHADOW,
        reason="FROZEN_CHALLENGER_ENTERED_SHADOW_INFERENCE",
        human_approved=False,
        root=root,
    )


def mark_integration_eligible(
    model_id: str,
    *,
    reason: str,
    human_approved: bool,
    shadow_buffer_evidence: dict[str, Any],
    root: str | Path | None = None,
) -> dict[str, Any]:
    return _transition(
        model_id,
        target=STAGE_ELIGIBLE,
        reason=reason,
        human_approved=human_approved,
        root=root,
        evidence_updates={"shadow_buffer_evidence": dict(shadow_buffer_evidence)},
    )


def promote_champion(
    model_id: str,
    *,
    reason: str,
    human_approved: bool,
    root: str | Path | None = None,
) -> dict[str, Any]:
    return _transition(
        model_id,
        target=STAGE_CHAMPION,
        reason=reason,
        human_approved=human_approved,
        root=root,
    )


def list_models(*, task: str | None = None, root: str | Path | None = None) -> list[dict[str, Any]]:
    rows = []
    for directory in registry_root(root).iterdir():
        if not directory.is_dir() or not (directory / "metadata.json").exists():
            continue
        try:
            data = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if task and str(data.get("task")) != str(task):
            continue
        rows.append(data)
    return sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)
