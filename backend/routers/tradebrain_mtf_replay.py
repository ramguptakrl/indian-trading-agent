"""Active BSE SWING MTF replay API. Advisory/research only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.tradebrain.mtf_replay import evaluate_swing_mtf_replay, list_mtf_replays

router = APIRouter(prefix="/api/tradebrain/mtf-replay", tags=["tradebrain-mtf-replay"])


class SwingMtfReplayRequest(BaseModel):
    plan_id: str = Field(min_length=4)
    series_id: str = Field(min_length=4)
    quantity: int = Field(gt=0)
    funded_amount: float = Field(gt=0)
    interest_days: int = Field(gt=0)
    mtf_eligible_verified: bool
    interval: str = Field(default="5m", min_length=2, max_length=16)
    max_sessions: int = Field(default=10, gt=0, le=60)
    as_of: str | None = None
    slippage_bps: float = Field(default=0.0, ge=0, le=500)
    transaction_charge_pct_override: float | None = Field(default=None, ge=0)
    dp_base_rupees: float | None = Field(default=None, ge=0)
    purchase_date_count: int = Field(default=1, gt=0)
    rms_squareoff_orders: int = Field(default=0, ge=0)
    persist: bool = True


@router.post("/evaluate")
def evaluate_mtf_replay(data: SwingMtfReplayRequest):
    try:
        return evaluate_swing_mtf_replay(**data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/results")
def mtf_replay_results(
    plan_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    return {
        "results": list_mtf_replays(plan_id=plan_id, limit=limit),
        "swing_funding": "ZERODHA_MTF_ONLY",
        "interest_days_rule": "EXPLICIT_SCENARIO_REQUIRED_NOT_GUESSED",
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
