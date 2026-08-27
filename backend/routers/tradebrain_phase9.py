"""Phase 9+ API: Zerodha Kite market-data-only boundary and source preference."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.tradebrain.kite_data import (
    KITE_DOCS_URL,
    KiteDataOnlyClient,
    kite_data_boundary,
    sync_kite_history,
)
from backend.tradebrain.kite_history_range import sync_kite_history_range
from backend.tradebrain.kite_stream import kite_stream_boundary, latest_kite_quote
from backend.tradebrain.market_source_policy import market_source_status, sync_preferred_history

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain-phase9"])


class KiteQuoteRequest(BaseModel):
    instruments: list[str] = Field(min_length=1, max_length=1000)
    kind: Literal["full", "ohlc", "ltp"] = "ltp"


class KiteHistorySyncRequest(BaseModel):
    exchange: Literal["NSE", "BSE"]
    symbol: str = Field(min_length=1, max_length=40)
    interval: Literal["minute", "3minute", "5minute", "10minute", "15minute", "30minute", "60minute", "day"]
    from_time: str
    to_time: str
    instrument_token: int | None = Field(default=None, gt=0)


class PreferredHistoryRequest(BaseModel):
    exchange: Literal["NSE", "BSE"]
    symbol: str = Field(min_length=1, max_length=40)
    interval: Literal["1m", "3m", "5m", "10m", "15m", "30m", "60m", "1h", "1d"]
    from_time: str
    to_time: str
    allow_yahoo_fallback: bool = True


def _client() -> KiteDataOnlyClient:
    try:
        return KiteDataOnlyClient()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/phase9/doctrine")
def phase9_doctrine():
    return {
        "phase": 9,
        "kite_docs": KITE_DOCS_URL,
        **kite_data_boundary(),
        "live_websocket": kite_stream_boundary(),
        "source_policy": market_source_status(),
        "credentials_are_never_returned": True,
        "order_routes_added": False,
    }


@router.get("/phase9/data/status")
def phase9_data_status():
    return {
        **market_source_status(),
        "live_websocket_boundary": kite_stream_boundary(),
    }


@router.get("/phase9/kite/boundary")
def phase9_kite_boundary():
    return {**kite_data_boundary(), "live_websocket": kite_stream_boundary()}


@router.post("/phase9/kite/quote")
def phase9_kite_quote(data: KiteQuoteRequest):
    try:
        return {
            "data": _client().quote(data.instruments, kind=data.kind),
            "credential_role": "MARKET_DATA_ONLY",
            "order_api_enabled": False,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Kite quote failed: {exc}") from exc


@router.post("/phase9/kite/sync-history")
def phase9_kite_sync_history(data: KiteHistorySyncRequest):
    try:
        return sync_kite_history(**data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Kite historical sync failed: {exc}") from exc


@router.post("/phase9/kite/sync-history-range")
def phase9_kite_sync_history_range(data: KiteHistorySyncRequest):
    try:
        return sync_kite_history_range(**data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Kite historical range sync failed: {exc}") from exc


@router.post("/phase9/data/sync-preferred-history")
def phase9_preferred_history(data: PreferredHistoryRequest):
    try:
        return sync_preferred_history(**data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Preferred historical sync failed: {exc}") from exc


@router.get("/phase9/kite/live/latest/{exchange}/{symbol}")
def phase9_latest_live_quote(exchange: Literal["NSE", "BSE"], symbol: str):
    item = latest_kite_quote(exchange, symbol)
    if item is None:
        raise HTTPException(status_code=404, detail="No persisted Kite WebSocket quote for this instrument")
    return {
        "quote": item,
        "credential_role": "MARKET_DATA_ONLY",
        "live_ticks_are_finalized_candles": False,
        "order_api_enabled": False,
    }
