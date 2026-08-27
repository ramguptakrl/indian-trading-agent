"""Adaptive after-market ML research orchestration for Trade Brain v0.14.

Discovery and retraining are intentionally different:

* A task with no frozen/shadow-capable model may continue bounded calendar-cadence discovery.
* A task that already has a frozen/shadow/eligible/champion model is NOT retrained merely
  because a week or month elapsed.  Its current artifact stays frozen.  Feature/model drift
  can recommend a separate research challenger, and that challenger is trained only in an
  after-market study mode.

Nothing in this module changes advisory weights, promotes a champion, or sends broker orders.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from backend.tradebrain.ml_drift import model_drift_report
from backend.tradebrain.ml_labels import build_labeled_dataset
from backend.tradebrain.ml_registry import (
    STAGE_CHAMPION,
    STAGE_ELIGIBLE,
    STAGE_FROZEN,
    STAGE_SHADOW,
    list_models,
)
from backend.tradebrain.ml_retraining import retraining_recommendation
from backend.tradebrain.ml_supervisor import ALLOWED_TRAINING_MODES, TASK_ORDER, run_ml_research_cycle
from backend.tradebrain.schedule import get_operating_mode

IST = ZoneInfo("Asia/Kolkata")
METHOD_VERSION = "BSE_ML_ADAPTIVE_CYCLE_V1"
ACTIVE_STAGES = {STAGE_FROZEN, STAGE_SHADOW, STAGE_ELIGIBLE, STAGE_CHAMPION}


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".tradingagents" / "tradebrain"


def default_adaptive_state_path() -> Path:
    path = _data_root() / "ml_adaptive_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def latest_active_models(
    tasks: Iterable[str],
    *,
    registry_path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for task in tuple(str(x) for x in tasks):
        for metadata in list_models(task=task, root=registry_path):
            if str(metadata.get("stage")) in ACTIVE_STAGES:
                result[task] = metadata
                break
    return result


def _watch_count(previous: int, drift: dict[str, Any]) -> int:
    feature = str((drift.get("feature_drift") or {}).get("status") or "UNKNOWN")
    performance = str((drift.get("shadow_performance") or {}).get("status") or "UNKNOWN")
    if "DRIFT_ALERT" in {feature, performance}:
        return 0
    if "WATCH" in {feature, performance}:
        return max(0, int(previous)) + 1
    return 0


def run_adaptive_ml_cycle(
    series_id: str,
    *,
    now: datetime | None = None,
    as_of: str | None = None,
    tasks: Iterable[str] = TASK_ORDER,
    deep_search: bool = False,
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
    selected_tasks = tuple(str(x) for x in tasks)
    unknown = [task for task in selected_tasks if task not in TASK_ORDER]
    if unknown:
        raise ValueError(f"Unsupported adaptive ML tasks: {unknown}")

    operating = get_operating_mode(
        current,
        exchange="NSE",
        db_path=db_path,
        require_verified_calendar=False,
    )
    mode = str(operating.get("mode") or "UNKNOWN")
    if mode not in ALLOWED_TRAINING_MODES:
        return {
            "status": "SKIPPED_NOT_TRAINING_TIME",
            "method_version": METHOD_VERSION,
            "operating_mode": operating,
            "heavy_training_during_market": False,
            "adaptive_retraining": True,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    state_file = Path(state_path).expanduser() if state_path else default_adaptive_state_path()
    state = _load(state_file)
    active = latest_active_models(selected_tasks, registry_path=registry_path)
    discovery_tasks = tuple(task for task in selected_tasks if task not in active)
    triggered_tasks: list[str] = []
    decisions: dict[str, Any] = {}

    for task, metadata in active.items():
        model_id = str(metadata.get("model_id") or "")
        try:
            bundle = build_labeled_dataset(
                series_id,
                task=task,
                as_of=cutoff,
                db_path=db_path,
            )
            drift = model_drift_report(
                model_id,
                bundle,
                labeled_bundle=bundle,
                registry_root=registry_path,
            )
            count_key = f"watch_sessions::{model_id}"
            count = _watch_count(int(state.get(count_key) or 0), drift)
            state[count_key] = count
            recommendation = retraining_recommendation(
                feature_drift=drift.get("feature_drift"),
                shadow_performance=drift.get("shadow_performance"),
                operating_mode=mode,
                consecutive_watch_sessions=count,
            )
            if recommendation.get("research_retrain_recommended"):
                triggered_tasks.append(task)
            decisions[task] = {
                "mode": "DRIFT_GOVERNED_ACTIVE_MODEL",
                "model_id": model_id,
                "model_stage": metadata.get("stage"),
                "drift": drift,
                "retraining": recommendation,
                "calendar_cadence_can_retrain_active_model": False,
            }
        except Exception as exc:
            decisions[task] = {
                "mode": "DRIFT_GOVERNED_ACTIVE_MODEL",
                "model_id": model_id,
                "model_stage": metadata.get("stage"),
                "status": "DRIFT_CHECK_FAILED_SAFE",
                "error": f"{type(exc).__name__}:{str(exc)[:500]}",
                "research_retrain_recommended": False,
                "calendar_cadence_can_retrain_active_model": False,
            }

    discovery_run = None
    if discovery_tasks:
        discovery_run = run_ml_research_cycle(
            series_id,
            now=current,
            as_of=cutoff,
            tasks=discovery_tasks,
            deep_search=deep_search,
            force=False,
            cadence_days=cadence_days,
            code_version=code_version,
            registry_path=registry_path,
            db_path=db_path,
        )
        for task in discovery_tasks:
            decisions.setdefault(task, {})
            decisions[task].update(
                {
                    "mode": "BOUNDED_DISCOVERY_NO_ACTIVE_MODEL",
                    "calendar_cadence_allowed_for_discovery": True,
                }
            )

    triggered_run = None
    unique_triggered = tuple(dict.fromkeys(triggered_tasks))
    if unique_triggered:
        triggered_run = run_ml_research_cycle(
            series_id,
            now=current,
            as_of=cutoff,
            tasks=unique_triggered,
            deep_search=deep_search,
            force=True,
            cadence_days=cadence_days,
            code_version=code_version,
            registry_path=registry_path,
            db_path=db_path,
        )

    state["last_adaptive_check_at_ist"] = current.isoformat()
    state["last_active_model_ids"] = {task: row.get("model_id") for task, row in active.items()}
    state["method_version"] = METHOD_VERSION
    _save(state_file, state)

    if unique_triggered:
        status = "RESEARCH_RETRAIN_TRIGGERED"
    elif discovery_run is not None:
        status = str(discovery_run.get("status") or "DISCOVERY_CHECKED")
    else:
        status = "STABLE_ACTIVE_MODELS_NO_RETRAIN"

    return {
        "status": status,
        "method_version": METHOD_VERSION,
        "operating_mode": operating,
        "as_of": cutoff,
        "active_models": {task: row.get("model_id") for task, row in active.items()},
        "discovery_tasks": list(discovery_tasks),
        "drift_triggered_tasks": list(unique_triggered),
        "task_decisions": decisions,
        "discovery_run": discovery_run,
        "triggered_research_run": triggered_run,
        "state_path": str(state_file),
        "active_model_mutated": False,
        "automatic_promotion": False,
        "automatic_advisory_integration": False,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
