"""Phase 10 API: fail-closed end-to-end advisory validation."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.tradebrain.advisory_pipeline import parse_agent_candidate
from backend.tradebrain.advisory_store import get_final_advisory
from backend.tradebrain.audit_txt import audit_final_advisory
from backend.tradebrain.live_advisory import evaluate_live_guarded_advisory

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
    swing_funding: Literal["MTF", "CNC_OWN_CASH"] | None = None
    mtf_eligible_verified: bool | None = None
    funded_amount: float | None = Field(default=None, ge=0)
    mtf_interest_days: int | None = Field(default=None, ge=0)

    # Live BSE market/data guard inputs. Missing critical range state fails closed.
    last_price: float | None = Field(default=None, gt=0)
    lower_limit: float | None = Field(default=None, gt=0)
    upper_limit: float | None = Field(default=None, gt=0)
    previous_accepted_price: float | None = Field(default=None, gt=0)
    best_bid: float | None = Field(default=None, gt=0)
    best_ask: float | None = Field(default=None, gt=0)
    atr_reference: float | None = Field(default=None, gt=0)
    halt_confirmed: bool = False
    index_move_pct: float | None = None
    official_halt_state: str | None = Field(default=None, max_length=200)


@router.get("/phase10/doctrine")
def phase10_doctrine():
    return {
        "phase": 10,
        "tradebrain_version": "0.13.0",
        "final_pipeline": [
            "STRICT_STRUCTURED_AI_CANDIDATE_PARSE",
            "VERIFIED_EXCHANGE_CALENDAR",
            "LIVE_MARKET_HALT_AND_PRICE_RANGE_GUARDS",
            "FREAK_TICK_DATA_CONFIRMATION",
            "EXPLICIT_CRASH_GUARD_STATE",
            "EXPLICIT_BROKER_EXCHANGE_PERMISSION",
            "DETERMINISTIC_HARD_RULE_GATE",
            "SWING_MTF_ONLY_FUNDING_GATE",
            "HUMAN_APPROVED_SOFT_RUNTIME",
            "RESIDENT_PLUS_MTF_NET_COST_SCENARIOS",
            "ADVISORY_ONLY_OUTPUT",
        ],
        "live_guard_priority": "HALT > PRICE RANGE > DATA QUALITY/FREAK TICK > BROKER/FUNDING > TECHNICAL SETUP > LLM",
        "missing_critical_market_state_fails_closed": True,
        "free_form_trade_inference": False,
        "raw_buy_sell_signal_output": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
        "order_endpoint_present": False,
        "mtf_enabled": True,
        "mtf_scope": "SWING_LONG_ONLY_RESEARCH_AND_COST_MODELING",
        "swing_funding": "MTF_ONLY",
        "cnc_own_cash_active_swing_allowed": False,
        "active_modes": ["INTRADAY", "SWING"],
        "human_readable_txt_audit": True,
        "hidden_chain_of_thought_persisted": False,
    }


@router.post("/phase10/parse-candidate")
def phase10_parse_candidate(data: CandidateParseRequest):
    return parse_agent_candidate(data.final_trade_decision)


@router.post("/phase10/final-advisory")
def phase10_final_advisory(data: FinalAdvisoryRequest):
    try:
        payload = data.model_dump()
        market_keys = {
            "last_price", "lower_limit", "upper_limit", "previous_accepted_price",
            "best_bid", "best_ask", "atr_reference", "halt_confirmed",
            "index_move_pct", "official_halt_state",
        }
        market_inputs = {key: payload.pop(key) for key in market_keys}
        result = evaluate_live_guarded_advisory(**payload, **market_inputs)
        request_audit = data.model_dump(exclude={"final_trade_decision"})
        audit_final_advisory(result, request=request_audit)
        return result
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
        "swing_funding": "MTF_ONLY",
        "mtf_enabled": True,
        "mtf_eligibility_must_be_verified": True,
        "funded_amount_required_for_swing_pass": True,
        "mtf_interest_days_required_for_net_cost_swing_pass": True,
        "live_price_required_for_live_pass": True,
        "broker_price_range_required_for_live_pass": True,
        "freak_tick_confirmation_required_before_live_pass": True,
        "confirmed_halt_blocks_live_pass": True,
        "potential_market_wide_circuit_requires_confirmation": True,
        "nri_kite_credential_role": "MARKET_DATA_ONLY",
        "order_execution_enabled": False,
        "raw_agent_buy_sell_is_trade_permission": False,
        "verified_calendar_required_by_default": True,
        "crash_guard_must_be_explicit": True,
        "broker_permission_must_be_explicit": True,
        "soft_parameter_runtime_requires_human_approved_active_version": True,
        "human_readable_txt_audit": True,
        "hidden_chain_of_thought_persisted": False,
    }
