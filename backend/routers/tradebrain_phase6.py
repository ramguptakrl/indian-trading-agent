"""Phase 6 API: resident INTRADAY base costs plus active SWING MTF economics."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.tradebrain.equity_costs import (
    calculate_equity_trade_costs,
    cost_profile,
    data_credential_boundary,
    solve_exit_price_for_net_profit,
)
from backend.tradebrain.mtf_economics import mtf_rule_snapshot
from backend.tradebrain.paper_ledger import (
    close_paper_position,
    create_paper_account,
    get_paper_account,
    get_paper_position,
    list_paper_positions,
    open_paper_position,
    paper_ledger_stats,
)
from backend.tradebrain.swing_mtf import (
    calculate_swing_mtf_trade_costs,
    solve_swing_mtf_exit_price_for_net_profit,
)
from backend.tradebrain.trade_modes import product_boundary

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain-phase6"])


class EquityCostRequest(BaseModel):
    mode: Literal["INTRADAY", "SWING"]
    exchange: Literal["NSE", "BSE"]
    direction: Literal["LONG", "SHORT"]
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    slippage_bps: float = Field(default=0.0, ge=0, le=500)
    transaction_charge_pct_override: float | None = Field(default=None, ge=0)
    dp_base_rupees: float | None = Field(default=None, ge=0)


class NetTargetRequest(BaseModel):
    mode: Literal["INTRADAY", "SWING"]
    exchange: Literal["NSE", "BSE"]
    direction: Literal["LONG", "SHORT"]
    entry_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    desired_net_profit: float
    slippage_bps: float = Field(default=0.0, ge=0, le=500)
    transaction_charge_pct_override: float | None = Field(default=None, ge=0)
    dp_base_rupees: float | None = Field(default=None, ge=0)


class SwingMtfCostRequest(BaseModel):
    exchange: Literal["NSE", "BSE"] = "NSE"
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    funded_amount: float = Field(gt=0)
    interest_days: int = Field(ge=0)
    slippage_bps: float = Field(default=0.0, ge=0, le=500)
    transaction_charge_pct_override: float | None = Field(default=None, ge=0)
    dp_base_rupees: float | None = Field(default=None, ge=0)
    purchase_date_count: int = Field(default=1, gt=0)
    rms_squareoff_orders: int = Field(default=0, ge=0)


class SwingMtfNetTargetRequest(BaseModel):
    exchange: Literal["NSE", "BSE"] = "NSE"
    entry_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    funded_amount: float = Field(gt=0)
    interest_days: int = Field(ge=0)
    desired_net_profit: float
    slippage_bps: float = Field(default=0.0, ge=0, le=500)
    transaction_charge_pct_override: float | None = Field(default=None, ge=0)
    dp_base_rupees: float | None = Field(default=None, ge=0)
    purchase_date_count: int = Field(default=1, gt=0)
    rms_squareoff_orders: int = Field(default=0, ge=0)


class PaperAccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    starting_cash: float = Field(gt=0)


class PaperPositionOpen(BaseModel):
    account_id: str = Field(min_length=5)
    ticker: str = Field(min_length=1, max_length=40)
    exchange: Literal["NSE", "BSE"]
    mode: Literal["INTRADAY", "SWING"]
    direction: Literal["LONG", "SHORT"]
    quantity: int = Field(gt=0)
    entry_price: float = Field(gt=0)
    entry_timestamp: str | None = None
    slippage_bps: float = Field(default=0.0, ge=0, le=500)
    transaction_charge_pct_override: float | None = Field(default=None, ge=0)
    dp_base_rupees: float | None = Field(default=None, ge=0)
    data_source: str = Field(default="MANUAL_OR_AUDITED_DATA", max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class PaperPositionClose(BaseModel):
    exit_price: float = Field(gt=0)
    exit_timestamp: str | None = None


def _bad_request(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/phase6/doctrine")
def phase6_doctrine():
    return {
        "phase": 6,
        "tradebrain_version": "0.13.0",
        **product_boundary(),
        "base_equity_cost_engine": "RESIDENT_TRANSACTION_COST_COMPONENT",
        "active_swing_cost_engine": "RESIDENT_EQUITY_PLUS_ZERODHA_MTF",
        "swing_funding": "MTF_ONLY",
        "legacy_phase6_paper_ledger": "INTRADAY_ACTIVE; DIRECT SWING ACCESS IS COMPATIBILITY-ONLY",
        "kite_or_other_broker_credential": data_credential_boundary(),
        "automatic_execution": False,
        "orders_endpoint_in_phase6": False,
    }


@router.get("/phase6/cost-profile")
def phase6_cost_profile():
    result = cost_profile()
    return {
        **result,
        "profile_role": "BASE_EQUITY_TRANSACTION_COST_COMPONENT",
        "active_swing_funding": "MTF_ONLY",
        "mtf_incremental_profile": mtf_rule_snapshot(),
    }


@router.get("/phase6/mtf-rules")
def phase6_mtf_rules():
    return {
        **mtf_rule_snapshot(),
        "active_trade_mode": "SWING",
        "direction": "LONG_ONLY",
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


@router.get("/phase6/data-credential-boundary")
def phase6_data_credential_boundary():
    return data_credential_boundary()


@router.post("/phase6/equity-costs")
def phase6_equity_costs(data: EquityCostRequest):
    if data.mode == "SWING":
        raise HTTPException(
            status_code=400,
            detail="Active SWING is MTF-only. Use /api/tradebrain/phase6/swing-mtf-costs.",
        )
    return _bad_request(calculate_equity_trade_costs, **data.model_dump())


@router.post("/phase6/net-target")
def phase6_net_target(data: NetTargetRequest):
    if data.mode == "SWING":
        raise HTTPException(
            status_code=400,
            detail="Active SWING is MTF-only. Use /api/tradebrain/phase6/swing-mtf-net-target.",
        )
    payload = data.model_dump()
    desired = payload.pop("desired_net_profit")
    price = _bad_request(solve_exit_price_for_net_profit, desired_net_profit=desired, **payload)
    return {
        "required_raw_exit_price": price,
        "desired_net_profit": desired,
        "mode": data.mode,
        "direction": data.direction,
        "mtf_used": False,
        "funding_interest": 0.0,
    }


@router.post("/phase6/swing-mtf-costs")
def phase6_swing_mtf_costs(data: SwingMtfCostRequest):
    return _bad_request(calculate_swing_mtf_trade_costs, **data.model_dump())


@router.post("/phase6/swing-mtf-net-target")
def phase6_swing_mtf_net_target(data: SwingMtfNetTargetRequest):
    payload = data.model_dump()
    desired = payload.pop("desired_net_profit")
    price = _bad_request(
        solve_swing_mtf_exit_price_for_net_profit,
        desired_net_profit=desired,
        **payload,
    )
    return {
        "required_raw_exit_price": price,
        "desired_net_profit": desired,
        "mode": "SWING",
        "direction": "LONG",
        "swing_funding": "MTF",
        "funded_amount": data.funded_amount,
        "interest_days": data.interest_days,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


@router.post("/phase6/paper/accounts")
def phase6_create_paper_account(data: PaperAccountCreate):
    return _bad_request(create_paper_account, **data.model_dump())


@router.get("/phase6/paper/accounts/{account_id}")
def phase6_get_paper_account(account_id: str):
    return _bad_request(get_paper_account, account_id)


@router.post("/phase6/paper/positions")
def phase6_open_paper_position(data: PaperPositionOpen):
    if data.mode == "SWING":
        raise HTTPException(
            status_code=400,
            detail=(
                "The legacy Phase-6 paper position endpoint does not model MTF funding. "
                "Active SWING must not be represented as own-cash paper delivery."
            ),
        )
    return _bad_request(open_paper_position, **data.model_dump())


@router.get("/phase6/paper/positions/{position_id}")
def phase6_get_paper_position(position_id: str):
    return _bad_request(get_paper_position, position_id)


@router.post("/phase6/paper/positions/{position_id}/close")
def phase6_close_paper_position(position_id: str, data: PaperPositionClose):
    return _bad_request(close_paper_position, position_id=position_id, **data.model_dump())


@router.get("/phase6/paper/accounts/{account_id}/positions")
def phase6_list_paper_positions(
    account_id: str,
    status: Literal["OPEN", "CLOSED"] | None = Query(default=None),
):
    positions = _bad_request(list_paper_positions, account_id=account_id, status=status)
    return {"positions": positions, "count": len(positions)}


@router.get("/phase6/paper/stats")
def phase6_paper_stats():
    stats = paper_ledger_stats()
    return {
        **stats,
        "active_swing_paper_permission": False,
        "reason": "Legacy paper ledger has no MTF funding fields; active SWING own-cash representation is blocked at API boundary.",
    }
