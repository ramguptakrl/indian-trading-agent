"""After-market self-training supervisor for Trade Brain v0.14 ML.

The supervisor matures point-in-time datasets, runs controlled research competitions, records
all accepted/rejected trials, and may advance a robust model only to the historical-pass
stage. It cannot freeze a challenger, enable advisory weighting, or place broker orders.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from backend.tradebrain.ml_cpcv import evaluate_cpcv_candidate
from backend.tradebrain.ml_labels import (
    TASK_INTRADAY_LONG,
    TASK_INTRADAY_SHORT,
    TASK_SWING_LONG_MTF,
    build_labeled_dataset,
)
from backend.tradebrain.ml_optimizer import OptimizerConfig, optimize_labeled_dataset, serializable_result
from backend.tradebrain.ml_promotion import evaluate_historical_promotion
from backend.tradebrain.ml_registry import mark_historical_pass, register_optimization, registry_root
from backend.tradebrain.ml_validation import DEFAULT_CHRONOLOGY
from backend.tradebrain.schedule import get_operating_mode

IST = ZoneInfo("Asia/Kolkata")
METHOD_VERSION = "BSE_ML_SUPERVISOR_V1"
TASK_ORDER = (TASK_INTRADAY_LONG, TASK_INTRADAY_SHORT, TASK_SWING_LONG_MTF)
ALLOWED_TRAINING_MODES = {"POST_MARKET_STUDY", "STUDY_REPLAY"}


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".tradingagents" / "tradebrain"


def default_state_path() -> Path:
    path = _data_root() / "ml_supervisor_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _run_dir(run_id: str) -> Path:
    path = _data_root() / "ml_runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_result(run_id: str, task: str, payload: dict[str, Any]) -> str:
    path = _run_dir(run_id) / f"{task}.json"
    _save(path, payload)
    return str(path)


def _run_id(series_id: str, as_of: str, deep: bool) -> str:
    digest = hashlib.sha256(f"{series_id}|{as_of}|{int(deep)}|{METHOD_VERSION}".encode()).hexdigest()[:12]
    date = str(as_of)[:10].replace("-", "")
    return f"MLRUN_{date}_{digest.upper()}"


def _due(last_run: str | None, current: datetime, cadence_days: int) -> bool:
    if not last_run:
        return True
    try:
        previous = datetime.fromisoformat(last_run)
    except ValueError:
        return True
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=IST)
    return current >= previous.astimezone(IST) + timedelta(days=max(1, int(cadence_days)))


def _cpcv_evidence(bundle, optimization) -> dict[str, Any]:
    if optimization.status != "OOS_PASS" or not optimization.winner:
        return {
            "passed": False,
            "verdict": "CPCV_NOT_RUN_NO_OOS_PASS",
            "used_for_hyperparameter_selection": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    try:
        cutoff = pd.Timestamp(DEFAULT_CHRONOLOGY.holdout_start)
        pre_holdout = bundle.frame.loc[
            pd.to_datetime(bundle.frame["ts_close"], utc=True) < cutoff
        ].copy()
        return evaluate_cpcv_candidate(
            pre_holdout,
            feature_columns=optimization.feature_columns,
            family=str(optimization.winner.get("family")),
            params=dict(optimization.winner.get("params") or {}),
            threshold=float(optimization.winner.get("threshold")),
        )
    except Exception as exc:
        return {
            "passed": False,
            "verdict": "CPCV_FAILED_SAFE",
            "error": f"{type(exc).__name__}:{str(exc)[:500]}",
            "used_for_hyperparameter_selection": False,
            "automatic_promotion": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }


def run_ml_research_cycle(
    series_id: str,
    *,
    now: datetime | None = None,
    as_of: str | None = None,
    tasks: Iterable[str] = TASK_ORDER,
    deep_search: bool = False,
    force: bool = False,
    cadence_days: int = 7,
    code_version: str | None = None,
    state_path: str | Path | None = None,
    registry_path: str | Path | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    else:
        current = current.astimezone(IST)
    cutoff = as_of or current.isoformat()
    operating = get_operating_mode(
        current,
        exchange="NSE",
        db_path=db_path,
        require_verified_calendar=False,
    )
    if not force and operating.get("mode") not in ALLOWED_TRAINING_MODES:
        return {
            "status": "SKIPPED_NOT_TRAINING_TIME",
            "method_version": METHOD_VERSION,
            "operating_mode": operating,
            "heavy_training_during_market": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    state_file = Path(state_path).expanduser() if state_path else default_state_path()
    state = _load(state_file)
    last_key = "last_deep_run_at_ist" if deep_search else "last_light_run_at_ist"
    if not force and not _due(state.get(last_key), current, cadence_days):
        return {
            "status": "SKIPPED_CADENCE",
            "method_version": METHOD_VERSION,
            "deep_search": bool(deep_search),
            "last_run_at_ist": state.get(last_key),
            "cadence_days": int(cadence_days),
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    selected_tasks = tuple(str(task) for task in tasks)
    unknown = [task for task in selected_tasks if task not in TASK_ORDER]
    if unknown:
        raise ValueError(f"Unsupported ML supervisor tasks: {unknown}")

    run_id = _run_id(series_id, cutoff, deep_search)
    version = code_version or os.getenv("TRADEBRAIN_CODE_VERSION") or "LOCAL_UNSPECIFIED"
    config = OptimizerConfig(deep_search=bool(deep_search))
    task_results: dict[str, Any] = {}

    for task in selected_tasks:
        try:
            bundle = build_labeled_dataset(
                series_id,
                task=task,
                as_of=cutoff,
                db_path=db_path,
            )
            optimization = optimize_labeled_dataset(bundle, config=config)
            serial = serializable_result(optimization)
            promotion_quality = evaluate_historical_promotion(optimization)
            cpcv = _cpcv_evidence(bundle, optimization)
            registered = None
            if optimization.status == "OOS_PASS":
                registered = register_optimization(
                    optimization,
                    code_version=version,
                    root=registry_path,
                )
                if (
                    registered.get("historical_walk_forward_pass")
                    and promotion_quality.get("passed")
                    and cpcv.get("passed")
                ):
                    registered = mark_historical_pass(
                        registered["model_id"],
                        root=registry_path,
                    )
            record = {
                **serial,
                "dataset_metadata": bundle.metadata,
                "promotion_quality": promotion_quality,
                "cpcv_robustness": cpcv,
                "registered_model": registered,
                "run_id": run_id,
                "supervisor_method_version": METHOD_VERSION,
                "automatic_freeze": False,
                "automatic_shadow_enable": False,
                "automatic_advisory_integration": False,
                "hard_rules_modified": False,
                "advisory_only": True,
                "trade_authorization": False,
                "order_execution_allowed": False,
            }
            artifact_path = _write_result(run_id, task, record)
            task_results[task] = {
                "status": optimization.status,
                "dataset_rows": int(len(bundle.frame)),
                "dataset_snapshot_hash": bundle.metadata.get("dataset_snapshot_hash"),
                "trial_count": len(optimization.trials),
                "promotion_quality_verdict": promotion_quality.get("verdict"),
                "promotion_quality_failures": promotion_quality.get("failures") or [],
                "cpcv_verdict": cpcv.get("verdict"),
                "cpcv_passed": bool(cpcv.get("passed")),
                "registered_model_id": (registered or {}).get("model_id"),
                "registered_stage": (registered or {}).get("stage"),
                "artifact_path": artifact_path,
            }
        except Exception as exc:
            failure = {
                "status": "FAILED_SAFE",
                "task": task,
                "error_type": type(exc).__name__,
                "error": str(exc)[:800],
                "run_id": run_id,
                "automatic_policy_change": False,
                "advisory_only": True,
                "trade_authorization": False,
                "order_execution_allowed": False,
            }
            artifact_path = _write_result(run_id, task, failure)
            task_results[task] = {**failure, "artifact_path": artifact_path}

    statuses = [str(item.get("status")) for item in task_results.values()]
    success_like = {
        "OOS_PASS",
        "OOS_REJECTED",
        "NO_ROBUST_CANDIDATE",
        "INSUFFICIENT_DATA",
        "INSUFFICIENT_CHRONOLOGY",
    }
    overall = "SUCCESS" if all(status in success_like for status in statuses) else "SUCCESS_WITH_RESEARCH_WARNINGS"
    state[last_key] = current.isoformat()
    state["last_run_id"] = run_id
    state["last_status"] = overall
    state["method_version"] = METHOD_VERSION
    _save(state_file, state)

    return {
        "status": overall,
        "method_version": METHOD_VERSION,
        "run_id": run_id,
        "deep_search": bool(deep_search),
        "cadence_days": int(cadence_days),
        "as_of": cutoff,
        "code_version": version,
        "tasks": task_results,
        "registry_root": str(registry_root(registry_path)),
        "state_path": str(state_file),
        "learning_boundary": {
            "llm_weights_modified": False,
            "hard_rules_modified": False,
            "soft_parameters_auto_promoted": False,
            "model_auto_promoted_to_champion": False,
            "human_review_required_for_freeze": True,
            "human_review_required_for_advisory_integration": True,
        },
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
