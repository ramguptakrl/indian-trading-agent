"""Phase 9 API: Zerodha Kite Connect market-data-only boundary."""

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


def _client() -> KiteDataOnlyClient:
    try:
        return KiteDataOnlyClient()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/phase9/doctrine")
def phase9_doctrine():
    return {
        "phase": 9,
        "tradebrain_version": "0.10.0",
        "kite_docs": KITE_DOCS_URL,
        **kite_data_boundary(),
        "credentials_are_never_returned": True,
        "order_routes_added": False,
    }


@router.get("/phase9/kite/boundary")
def phase9_kite_boundary():
    return kite_data_boundary()


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
