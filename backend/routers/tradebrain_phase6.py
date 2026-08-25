"""Phase 6 API: resident INTRADAY base costs plus active SWING MTF economics."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.tradebrain.bse_scope import require_bse_trade_target
from backend.tradebrain.equity_costs import (
    calculate_equity_trade_costs,
    cost_profile,
    data_credential_boundary,
    solve_exit_price_for_net_profit,
)
from backend.tradebrain.mtf_economics import mtf_rule_snapshot
from backend.tradebrain.mtf_paper_ledger import (
    close_mtf_paper_position,
    get_mtf_paper_position,
    list_mtf_paper_positions,
    mtf_paper_stats,
    open_mtf_paper_position,
)
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
    ticker: str = Field(default="BSE", min_length=1, max_length=40)
    exchange: Literal["NSE"] = "NSE"
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
    funded_amount: float | None = Field(default=None, gt=0)
    mtf_eligible_verified: bool | None = None
    purchase_date_count: int = Field(default=1, gt=0)


class PaperPositionClose(BaseModel):
    exit_price: float = Field(gt=0)
    exit_timestamp: str | None = None
    interest_days: int | None = Field(default=None, ge=0)
    rms_squareoff_orders: int = Field(default=0, ge=0)


def _bad_request(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_any_paper_position(position_id: str):
    try:
        return {**get_mtf_paper_position(position_id), "ledger_kind": "SWING_MTF"}
    except ValueError:
        return {**get_paper_position(position_id), "ledger_kind": "INTRADAY_CASH"}


def _close_any_paper_position(position_id: str, data: PaperPositionClose):
    try:
        mtf = get_mtf_paper_position(position_id)
    except ValueError:
        mtf = None
    if mtf is not None:
        if data.interest_days is None or data.interest_days < 1:
            raise HTTPException(
                status_code=400,
                detail="A positive interest_days value is required to close an active SWING MTF paper position.",
            )
        return {
            **_bad_request(
                close_mtf_paper_position,
                position_id,
                exit_price=data.exit_price,
                interest_days=data.interest_days,
                exit_timestamp=data.exit_timestamp,
                rms_squareoff_orders=data.rms_squareoff_orders,
            ),
            "ledger_kind": "SWING_MTF",
        }
    if data.interest_days not in {None, 0} or data.rms_squareoff_orders:
        raise HTTPException(status_code=400, detail="MTF close fields are not valid for an INTRADAY cash paper position.")
    return {
        **_bad_request(
            close_paper_position,
            position_id=position_id,
            exit_price=data.exit_price,
            exit_timestamp=data.exit_timestamp,
        ),
        "ledger_kind": "INTRADAY_CASH",
    }


@router.get("/phase6/doctrine")
def phase6_doctrine():
    return {
        "phase": 6,
        "tradebrain_version": "0.13.0",
        **product_boundary(),
        "base_equity_cost_engine": "RESIDENT_TRANSACTION_COST_COMPONENT",
        "active_swing_cost_engine": "RESIDENT_EQUITY_PLUS_ZERODHA_MTF",
        "swing_funding": "MTF_ONLY",
        "paper_ledger": "INTRADAY_CASH_PLUS_SWING_MTF_EXPLICIT_FUNDING",
        "legacy_full_notional_swing_access": False,
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
    ticker = require_bse_trade_target(data.ticker)
    if data.mode == "SWING":
        if data.direction != "LONG":
            raise HTTPException(status_code=400, detail="Active SWING MTF is LONG-only.")
        if data.funded_amount is None or data.mtf_eligible_verified is not True:
            raise HTTPException(
                status_code=400,
                detail="SWING paper entry requires current MTF eligibility verification and funded_amount.",
            )
        return {
            **_bad_request(
                open_mtf_paper_position,
                account_id=data.account_id,
                ticker=ticker,
                exchange=data.exchange,
                quantity=data.quantity,
                entry_price=data.entry_price,
                funded_amount=data.funded_amount,
                mtf_eligible_verified=True,
                entry_timestamp=data.entry_timestamp,
                slippage_bps=data.slippage_bps,
                transaction_charge_pct_override=data.transaction_charge_pct_override,
                dp_base_rupees=data.dp_base_rupees,
                purchase_date_count=data.purchase_date_count,
                data_source=data.data_source,
                notes=data.notes,
            ),
            "ledger_kind": "SWING_MTF",
        }
    if data.funded_amount is not None or data.mtf_eligible_verified is not None:
        raise HTTPException(status_code=400, detail="MTF funding fields are only valid for SWING.")
    return {
        **_bad_request(
            open_paper_position,
            account_id=data.account_id,
            ticker=ticker,
            exchange=data.exchange,
            mode="INTRADAY",
            direction=data.direction,
            quantity=data.quantity,
            entry_price=data.entry_price,
            entry_timestamp=data.entry_timestamp,
            slippage_bps=data.slippage_bps,
            transaction_charge_pct_override=data.transaction_charge_pct_override,
            dp_base_rupees=data.dp_base_rupees,
            data_source=data.data_source,
            notes=data.notes,
        ),
        "ledger_kind": "INTRADAY_CASH",
    }


@router.get("/phase6/paper/positions/{position_id}")
def phase6_get_paper_position(position_id: str):
    return _bad_request(_get_any_paper_position, position_id)


@router.post("/phase6/paper/positions/{position_id}/close")
def phase6_close_paper_position(position_id: str, data: PaperPositionClose):
    return _close_any_paper_position(position_id, data)


@router.get("/phase6/paper/accounts/{account_id}/positions")
def phase6_list_paper_positions(
    account_id: str,
    status: Literal["OPEN", "CLOSED"] | None = Query(default=None),
):
    intraday = _bad_request(list_paper_positions, account_id=account_id, status=status)
    mtf = _bad_request(list_mtf_paper_positions, account_id=account_id, status=status)
    positions = [
        *({**item, "ledger_kind": "INTRADAY_CASH"} for item in intraday),
        *({**item, "ledger_kind": "SWING_MTF"} for item in mtf),
    ]
    positions.sort(key=lambda item: str(item.get("entry_timestamp") or ""), reverse=True)
    return {"positions": positions, "count": len(positions)}


@router.get("/phase6/paper/stats")
def phase6_paper_stats():
    legacy = paper_ledger_stats()
    mtf = mtf_paper_stats()
    return {
        "intraday_cash": legacy,
        "swing_mtf": mtf,
        "active_swing_paper_permission": True,
        "active_swing_funding": "MTF_ONLY",
        "legacy_full_notional_swing_permission": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
