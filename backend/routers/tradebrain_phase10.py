"""Phase 10 API: fail-closed end-to-end advisory validation."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.tradebrain.advisory_pipeline import evaluate_final_advisory, parse_agent_candidate
from backend.tradebrain.advisory_store import get_final_advisory

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain-phase10"])


class CandidateParseRequest(BaseModel):
    final_trade_decision: str = Field(min_length=1, max_length=50000)


class FinalAdvisoryRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=40)
    exchange: Literal["NSE", "BSE"] = "NSE"
    final_trade_decision: str = Field(min_length=1, max_length=50000)
    evaluated_at: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    crash_guard: Literal["NORMAL", "ELEVATED", "SEVERE"]
    broker_allows_trade: bool
    require_verified_calendar: bool = True
    slippage_bps: float = Field(default=0.0, ge=0, le=500)


@router.get("/phase10/doctrine")
def phase10_doctrine():
    return {
        "phase": 10,
        "tradebrain_version": "0.11.0",
        "final_pipeline": [
            "STRICT_STRUCTURED_AI_CANDIDATE_PARSE",
            "VERIFIED_EXCHANGE_CALENDAR",
            "EXPLICIT_CRASH_GUARD_STATE",
            "EXPLICIT_BROKER_EXCHANGE_PERMISSION",
            "DETERMINISTIC_HARD_RULE_GATE",
            "HUMAN_APPROVED_SOFT_RUNTIME",
            "RESIDENT_TRANSACTION_COST_SCENARIOS",
            "ADVISORY_ONLY_OUTPUT",
        ],
        "free_form_trade_inference": False,
        "raw_buy_sell_signal_output": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
        "order_endpoint_present": False,
        "mtf_enabled": False,
        "active_modes": ["INTRADAY", "SWING"],
    }


@router.post("/phase10/parse-candidate")
def phase10_parse_candidate(data: CandidateParseRequest):
    return parse_agent_candidate(data.final_trade_decision)


@router.post("/phase10/final-advisory")
def phase10_final_advisory(data: FinalAdvisoryRequest):
    try:
        return evaluate_final_advisory(**data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/phase10/analysis/{task_id}")
def phase10_analysis_boundary(task_id: str):
    result = get_final_advisory(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No persisted Trade Brain final advisory for task")
    return result


@router.get("/phase10/acceptance-boundary")
def phase10_acceptance_boundary():
    return {
        "trader_profile": "RESIDENT_INDIAN",
        "active_modes": ["INTRADAY", "SWING"],
        "mtf_enabled": False,
        "nri_kite_credential_role": "MARKET_DATA_ONLY",
        "order_execution_enabled": False,
        "raw_agent_buy_sell_is_trade_permission": False,
        "verified_calendar_required_by_default": True,
        "crash_guard_must_be_explicit": True,
        "broker_permission_must_be_explicit": True,
        "soft_parameter_runtime_requires_human_approved_active_version": True,
    }
