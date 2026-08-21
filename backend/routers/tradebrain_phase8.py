"""Phase 8 API: verified exchange calendar and operating session state."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.tradebrain.exchange_calendar import (
    NSE_HOLIDAY_API,
    calendar_stats,
    collect_nse_cash_calendar,
    session_for_date,
    upsert_verified_session_override,
)
from backend.tradebrain.schedule import get_operating_mode

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain-phase8"])


class VerifiedSessionOverride(BaseModel):
    exchange: Literal["NSE", "BSE"]
    session_date: str
    session_type: Literal["CLOSED", "SPECIAL_OPEN"]
    source_url: str = Field(min_length=12)
    description: str = Field(min_length=3, max_length=500)
    source_sha256: str = Field(min_length=64, max_length=64)
    open_time: str | None = None
    close_time: str | None = None


def _bad(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/phase8/doctrine")
def phase8_doctrine():
    return {
        "phase": 8,
        "tradebrain_version": "0.9.0",
        "calendar_source": "OFFICIAL_EXCHANGE_EVIDENCE",
        "nse_cash_holiday_api": NSE_HOLIDAY_API,
        "weekday_only_calendar_is_verified": False,
        "special_session_requires_verified_times": True,
        "unknown_calendar_fail_closed_available": True,
        "intraday_hard_times_unchanged": {"no_fresh_entry": "15:10 IST", "flat_before": "15:15 IST"},
    }


@router.post("/phase8/calendar/nse/refresh")
def phase8_refresh_nse_calendar():
    try:
        return collect_nse_cash_calendar()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE official calendar refresh failed: {exc}") from exc


@router.get("/phase8/calendar/{exchange}/{session_date}")
def phase8_calendar_day(exchange: Literal["NSE", "BSE"], session_date: str):
    return _bad(session_for_date, session_date, exchange=exchange)


@router.post("/phase8/calendar/verified-session-override")
def phase8_verified_session_override(data: VerifiedSessionOverride):
    return _bad(upsert_verified_session_override, **data.model_dump())


@router.get("/phase8/calendar/stats")
def phase8_calendar_stats():
    return calendar_stats()


@router.get("/phase8/operating-mode/{exchange}")
def phase8_operating_mode(exchange: Literal["NSE", "BSE"], require_verified: bool = True):
    return get_operating_mode(exchange=exchange, require_verified_calendar=require_verified)
