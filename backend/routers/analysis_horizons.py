"""Paired BSE analysis endpoint: independent INTRADAY and SWING graph runs."""

from __future__ import annotations

import threading
import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from backend.routers.analysis import _run_analysis_sync, _tasks
from backend.tradebrain.bse_scope import require_bse_trade_target
from tradingagents.default_config import DEFAULT_CONFIG

router = APIRouter(prefix="/api/analysis", tags=["analysis-horizons"])


class HorizonAnalysisRequest(BaseModel):
    ticker: str = "BSE"
    trade_date: str
    analysts: list[Literal["market", "social", "news", "fundamentals"]] = ["market", "news", "fundamentals"]
    max_debate_rounds: int = Field(default=1, ge=1, le=10)
    max_risk_discuss_rounds: int = Field(default=1, ge=1, le=10)
    output_language: str = Field(default="English", min_length=2, max_length=80)

    @field_validator("ticker", mode="before")
    @classmethod
    def enforce_bse_scope(cls, value: str) -> str:
        return require_bse_trade_target(value)


def _task_id(mode: str) -> str:
    prefix = "id" if mode == "INTRADAY" else "sw"
    return f"{prefix}-{str(uuid.uuid4())[:8]}"


def _launch(req: HorizonAnalysisRequest, mode: Literal["INTRADAY", "SWING"]) -> str:
    task_id = _task_id(mode)
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = req.max_debate_rounds
    config["max_risk_discuss_rounds"] = req.max_risk_discuss_rounds
    config["output_language"] = req.output_language
    config["requested_trade_mode"] = mode

    _tasks[task_id] = {
        "status": "pending",
        "ticker": "BSE",
        "trade_date": req.trade_date,
        "analysts": list(req.analysts),
        "requested_trade_mode": mode,
        "paired_horizon_run": True,
    }
    thread = threading.Thread(
        target=_run_analysis_sync,
        args=(task_id, "BSE", req.trade_date, config, list(req.analysts)),
        daemon=True,
        name=f"tradebrain-{mode.lower()}-{task_id}",
    )
    thread.start()
    return task_id


@router.post("/run-horizons")
def run_horizon_pair(req: HorizonAnalysisRequest):
    """Launch two separate graphs; neither horizon can silently substitute for the other."""
    intraday = _launch(req, "INTRADAY")
    swing = _launch(req, "SWING")
    pair_id = f"pair-{str(uuid.uuid4())[:8]}"
    return {
        "pair_id": pair_id,
        "ticker": "BSE",
        "trade_date": req.trade_date,
        "tasks": {
            "INTRADAY": intraday,
            "SWING": swing,
        },
        "independent_graph_runs": True,
        "shared_final_decision": False,
        "horizon_substitution_allowed": False,
        "swing_funding": "ZERODHA_MTF_ONLY",
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


@router.get("/horizon-pair/{intraday_task_id}/{swing_task_id}")
def get_horizon_pair(intraday_task_id: str, swing_task_id: str):
    def public_task(task_id: str, expected_mode: str):
        task = _tasks.get(task_id)
        if task is None:
            return {"task_id": task_id, "status": "unknown", "requested_trade_mode": expected_mode}
        result = task.get("result") if task.get("status") == "completed" else None
        return {
            "task_id": task_id,
            "status": task.get("status"),
            "requested_trade_mode": task.get("requested_trade_mode") or expected_mode,
            "research_label": result.get("research_label") if isinstance(result, dict) else None,
            "tradebrain_advisory": result.get("tradebrain_advisory") if isinstance(result, dict) else None,
            "error": task.get("error") if task.get("status") == "error" else None,
        }

    intraday = public_task(intraday_task_id, "INTRADAY")
    swing = public_task(swing_task_id, "SWING")
    statuses = {intraday["status"], swing["status"]}
    overall = "completed" if statuses == {"completed"} else ("error" if "error" in statuses else "running")
    return {
        "status": overall,
        "ticker": "BSE",
        "plans": {"INTRADAY": intraday, "SWING": swing},
        "independent_graph_runs": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
