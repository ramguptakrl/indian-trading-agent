"""Paired BSE analysis endpoint: independent INTRADAY and SWING graph runs."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from backend.routers.analysis import _run_analysis_sync, _tasks
from backend.tradebrain.bse_scope import require_bse_trade_target
from tradingagents.default_config import DEFAULT_CONFIG

router = APIRouter(prefix="/api/analysis", tags=["analysis-horizons"])
_TERMINAL_TASK_STATES = {"completed", "error"}


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


def _run_after_task(
    task_id: str,
    ticker: str,
    trade_date: str,
    config: dict,
    analysts: list[str],
    wait_for_task_id: str | None,
) -> None:
    """Run one independent graph after a paired predecessor stops using AI capacity.

    The two horizon decisions remain completely separate. We only serialize their LLM
    workload so free/low-quota Groq and Gemini accounts are not hit by two full multi-agent
    graphs at the exact same time. This reduces avoidable 429 bursts without allowing
    either horizon to substitute for the other.
    """
    if wait_for_task_id:
        while True:
            predecessor = _tasks.get(wait_for_task_id)
            if predecessor is None or predecessor.get("status") in _TERMINAL_TASK_STATES:
                break
            time.sleep(0.25)
        # Give provider-side counters a small chance to settle between full graph runs.
        time.sleep(1.0)

    _run_analysis_sync(task_id, ticker, trade_date, config, analysts)


def _launch(
    req: HorizonAnalysisRequest,
    mode: Literal["INTRADAY", "SWING"],
    *,
    wait_for_task_id: str | None = None,
) -> str:
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
        "provider_wait_for_task_id": wait_for_task_id,
    }
    thread = threading.Thread(
        target=_run_after_task,
        args=(task_id, "BSE", req.trade_date, config, list(req.analysts), wait_for_task_id),
        daemon=True,
        name=f"tradebrain-{mode.lower()}-{task_id}",
    )
    thread.start()
    return task_id


@router.post("/run-horizons")
def run_horizon_pair(req: HorizonAnalysisRequest):
    """Launch two separate graphs with quota-safe provider scheduling."""
    intraday = _launch(req, "INTRADAY")
    swing = _launch(req, "SWING", wait_for_task_id=intraday)
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
        "provider_load_scheduling": "SERIALIZED_INDEPENDENT_HORIZONS",
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
        "provider_load_scheduling": "SERIALIZED_INDEPENDENT_HORIZONS",
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
