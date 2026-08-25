"""API for manually recording actual BSE Ltd broker trades after Trade Brain advisories."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.tradebrain.actual_trade_journal import (
    actual_trade_stats,
    close_actual_trade,
    get_actual_trade,
    list_actual_trades,
    mark_actual_trade,
    record_actual_trade,
)
from backend.tradebrain.bse_scope import BSE_SCOPE, require_bse_trade_target

router = APIRouter(prefix="/api/tradebrain/actual-trades", tags=["tradebrain-actual-trades"])


class ActualTradeCreate(BaseModel):
    ticker: str = "BSE"
    exchange: Literal["NSE"] = "NSE"
    mode: Literal["INTRADAY", "SWING"]
    direction: Literal["LONG", "SHORT"]
    quantity: int = Field(gt=0)
    entry_price: float = Field(gt=0)
    entry_timestamp: str | None = None
    advisory_task_id: str | None = Field(default=None, max_length=120)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    broker_order_ref: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("ticker", mode="before")
    @classmethod
    def enforce_bse_ticker(cls, value: str) -> str:
        return require_bse_trade_target(value)


class ActualTradeClose(BaseModel):
    exit_price: float = Field(gt=0)
    quantity: int | None = Field(default=None, gt=0)
    exit_timestamp: str | None = None
    actual_charges_override: float | None = Field(default=None, ge=0)
    broker_order_ref: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)


class ActualTradeMark(BaseModel):
    current_price: float = Field(gt=0)
    source: str = Field(default="MANUAL_OR_MARKET_DATA", max_length=160)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/doctrine")
def doctrine():
    return {
        "observation_kind": "ACTUAL_MANUAL_TRADE",
        "purpose": "Record what the human actually did in BSE Ltd after an advisory; keep it separate from replay and paper outcomes.",
        "instrument": BSE_SCOPE.kite_symbol,
        "isin": BSE_SCOPE.isin,
        "supports": ["INTRADAY", "SWING", "PARTIAL_CLOSE", "ADVISORY_LINK", "MANUAL_BROKER_REFERENCE"],
        "charges": "Resident equity charges are estimated unless a user supplies an actual charge override for a closed slice.",
        "broker_order_execution": False,
        "manual_tracking_only": True,
    }


@router.post("")
def create_actual_trade(data: ActualTradeCreate):
    return _call(record_actual_trade, **data.model_dump())


@router.get("")
def get_actual_trades(
    status: Literal["OPEN", "PARTIALLY_CLOSED", "CLOSED"] | None = Query(default=None),
    advisory_task_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    rows = _call(
        list_actual_trades,
        status=status,
        advisory_task_id=advisory_task_id,
        limit=limit,
    )
    return {"trades": rows, "count": len(rows)}


@router.get("/stats")
def get_actual_trade_stats():
    return actual_trade_stats()


@router.get("/{trade_id}")
def get_one_actual_trade(trade_id: str):
    return _call(get_actual_trade, trade_id)


@router.post("/{trade_id}/close")
def close_one_actual_trade(trade_id: str, data: ActualTradeClose):
    return _call(close_actual_trade, trade_id=trade_id, **data.model_dump())


@router.post("/{trade_id}/mark")
def mark_one_actual_trade(trade_id: str, data: ActualTradeMark):
    return _call(mark_actual_trade, trade_id=trade_id, **data.model_dump())
