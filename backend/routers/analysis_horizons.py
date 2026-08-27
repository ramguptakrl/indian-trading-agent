"""Paired BSE analysis: shared research once, independent horizon decisions."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from backend.routers.analysis import _analysis_advisory, _tasks
from backend.tradebrain.bse_scope import require_bse_trade_target
from backend.tradebrain.trade_date import normalize_trade_date
from backend.ws import manager
from tradingagents.default_config import DEFAULT_CONFIG

router = APIRouter(prefix="/api/analysis", tags=["analysis-horizons"])
SHARED_RESEARCH_VERSION = "BSE_SHARED_RESEARCH_PACK_V1"


class HorizonAnalysisRequest(BaseModel):
    ticker: str = "BSE"
    trade_date: str
    analysts: list[Literal["market", "social", "news", "fundamentals"]] = [
        "market",
        "news",
        "fundamentals",
    ]
    max_debate_rounds: int = Field(default=1, ge=1, le=10)
    max_risk_discuss_rounds: int = Field(default=1, ge=1, le=10)
    output_language: str = Field(default="English", min_length=2, max_length=80)

    @field_validator("ticker", mode="before")
    @classmethod
    def enforce_bse_scope(cls, value: str) -> str:
        return require_bse_trade_target(value)

    @field_validator("trade_date", mode="before")
    @classmethod
    def canonicalize_trade_date(cls, value: object) -> str:
        return normalize_trade_date(value)


def _task_id(mode: str) -> str:
    prefix = "id" if mode == "INTRADAY" else "sw"
    return f"{prefix}-{str(uuid.uuid4())[:8]}"


def _register_task(
    req: HorizonAnalysisRequest,
    mode: Literal["INTRADAY", "SWING"],
    *,
    pair_id: str,
    shared_research_pack_id: str,
) -> str:
    task_id = _task_id(mode)
    _tasks[task_id] = {
        "status": "pending",
        "stage": "shared_research",
        "ticker": "BSE",
        "trade_date": req.trade_date,
        "analysts": list(req.analysts),
        "requested_trade_mode": mode,
        "paired_horizon_run": True,
        "pair_id": pair_id,
        "shared_research_pack_id": shared_research_pack_id,
        "shared_analyst_research": True,
        "shared_final_decision": False,
    }
    return task_id


def _pair_config(req: HorizonAnalysisRequest) -> dict:
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = req.max_debate_rounds
    config["max_risk_discuss_rounds"] = req.max_risk_discuss_rounds
    config["output_language"] = req.output_language
    return config


def _run_shared_pair(
    req: HorizonAnalysisRequest,
    intraday_task_id: str,
    swing_task_id: str,
    shared_research_pack_id: str,
) -> None:
    """Research common evidence once, then run two independent decision graphs."""
    # Heavy graph/LLM imports stay inside the background worker so API model/unit tests do
    # not require the full LangChain runtime merely to validate request/architecture code.
    from backend.tradebrain.shared_horizon_runtime import (
        build_shared_research_pack,
        run_horizon_from_shared_pack,
    )

    shared_loop = asyncio.new_event_loop()
    task_ids = (intraday_task_id, swing_task_id)

    def fanout(payload: dict) -> None:
        for task_id in task_ids:
            shared_loop.run_until_complete(manager.send_event(task_id, payload))

    for task_id in task_ids:
        _tasks[task_id]["status"] = "running"
        _tasks[task_id]["stage"] = "shared_research"

    fanout({
        "type": "heartbeat",
        "chunk": 0,
        "last_activity": "Building one shared BSE analyst research pack for both horizons...",
        "shared_research": True,
        "shared_research_pack_id": shared_research_pack_id,
    })

    try:
        def on_shared_report(field: str, content: str) -> None:
            fanout({
                "type": "report",
                "section": field,
                "content": content,
                "shared_research": True,
                "shared_research_pack_id": shared_research_pack_id,
            })

        shared_pack = build_shared_research_pack(
            ticker="BSE",
            trade_date=req.trade_date,
            config=_pair_config(req),
            selected_analysts=list(req.analysts),
            pack_id=shared_research_pack_id,
            on_report=on_shared_report,
        )
        for task_id in task_ids:
            _tasks[task_id]["shared_research_provider"] = shared_pack["provider"]
            _tasks[task_id]["shared_research_llm_failover_used"] = shared_pack[
                "llm_failover_used"
            ]
            _tasks[task_id]["shared_context_as_of"] = shared_pack["context_as_of"]
            _tasks[task_id]["shared_context_status"] = shared_pack["context_status"]

        fanout({
            "type": "heartbeat",
            "chunk": 0,
            "last_activity": "Shared analyst research complete. Forking independent horizon decisions...",
            "shared_research": True,
            "shared_research_complete": True,
            "shared_research_pack_id": shared_research_pack_id,
        })
    except Exception as exc:
        message = str(exc)
        for task_id in task_ids:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["stage"] = "error"
            _tasks[task_id]["error"] = message
        fanout({"type": "error", "message": message})
        shared_loop.close()
        return

    shared_loop.close()

    # Same immutable research pack, separate downstream reasoning and verdicts. Keep the
    # heavy decision chains serialized to avoid avoidable free-tier provider 429 bursts.
    run_horizon_from_shared_pack(
        task_id=intraday_task_id,
        ticker="BSE",
        trade_date=req.trade_date,
        mode="INTRADAY",
        selected_analysts=list(req.analysts),
        shared_pack=shared_pack,
        tasks=_tasks,
        analysis_advisory=_analysis_advisory,
    )
    time.sleep(1.0)
    run_horizon_from_shared_pack(
        task_id=swing_task_id,
        ticker="BSE",
        trade_date=req.trade_date,
        mode="SWING",
        selected_analysts=list(req.analysts),
        shared_pack=shared_pack,
        tasks=_tasks,
        analysis_advisory=_analysis_advisory,
    )


@router.post("/run-horizons")
def run_horizon_pair(req: HorizonAnalysisRequest):
    """Launch one shared analyst pass followed by two independent horizon decisions."""
    pair_id = f"pair-{str(uuid.uuid4())[:8]}"
    shared_research_pack_id = f"research-{str(uuid.uuid4())[:8]}"
    intraday = _register_task(
        req,
        "INTRADAY",
        pair_id=pair_id,
        shared_research_pack_id=shared_research_pack_id,
    )
    swing = _register_task(
        req,
        "SWING",
        pair_id=pair_id,
        shared_research_pack_id=shared_research_pack_id,
    )

    thread = threading.Thread(
        target=_run_shared_pair,
        args=(req, intraday, swing, shared_research_pack_id),
        daemon=True,
        name=f"tradebrain-shared-pair-{pair_id}",
    )
    thread.start()

    return {
        "pair_id": pair_id,
        "ticker": "BSE",
        "trade_date": req.trade_date,
        "tasks": {"INTRADAY": intraday, "SWING": swing},
        "graph_architecture": "SHARED_RESEARCH_THEN_INDEPENDENT_DECISIONS",
        "shared_research_pack_id": shared_research_pack_id,
        "shared_research_version": SHARED_RESEARCH_VERSION,
        "shared_data_pull": True,
        "shared_analyst_research": True,
        "independent_graph_runs": True,
        "independent_decision_graph_runs": True,
        "shared_final_decision": False,
        "horizon_substitution_allowed": False,
        "provider_load_scheduling": "SHARED_RESEARCH_ONCE_THEN_SERIAL_DECISIONS",
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
            return {
                "task_id": task_id,
                "status": "unknown",
                "requested_trade_mode": expected_mode,
            }
        result = task.get("result") if task.get("status") == "completed" else None
        return {
            "task_id": task_id,
            "status": task.get("status"),
            "stage": task.get("stage"),
            "requested_trade_mode": task.get("requested_trade_mode") or expected_mode,
            "shared_research_pack_id": task.get("shared_research_pack_id"),
            "shared_research_provider": task.get("shared_research_provider"),
            "research_label": result.get("research_label") if isinstance(result, dict) else None,
            "tradebrain_advisory": result.get("tradebrain_advisory") if isinstance(result, dict) else None,
            "error": task.get("error") if task.get("status") == "error" else None,
        }

    intraday = public_task(intraday_task_id, "INTRADAY")
    swing = public_task(swing_task_id, "SWING")
    statuses = {intraday["status"], swing["status"]}
    overall = (
        "completed"
        if statuses == {"completed"}
        else ("error" if "error" in statuses else "running")
    )
    return {
        "status": overall,
        "ticker": "BSE",
        "plans": {"INTRADAY": intraday, "SWING": swing},
        "graph_architecture": "SHARED_RESEARCH_THEN_INDEPENDENT_DECISIONS",
        "shared_analyst_research": True,
        "independent_graph_runs": True,
        "independent_decision_graph_runs": True,
        "provider_load_scheduling": "SHARED_RESEARCH_ONCE_THEN_SERIAL_DECISIONS",
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
