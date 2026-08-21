"""Phase 3 Trade Brain API: audited OHLCV, derivation, replay, event effects."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.tradebrain.market_data import (
    YAHOO_SOURCE_KEY,
    derive_standard_timeframes,
    derive_timeframe,
    sync_yahoo_history,
)
from backend.tradebrain.market_data_store import (
    assign_price_eras,
    find_series,
    get_series,
    list_issues,
    market_data_stats,
    query_bars,
    rebuild_vendor_split_eras,
)
from backend.tradebrain.replay import (
    audit_series_interval,
    build_replay_snapshot,
    compute_event_price_effects,
)

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain-phase3"])


class EventPriceEffectRequest(BaseModel):
    series_id: str
    interval: str = "5m"
    horizons_sessions: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])
    persist: bool = True


@router.post("/market-data/sync/yahoo")
def sync_yahoo_market_data(
    exchange: str = Query(..., pattern="^(NSE|BSE|nse|bse)$"),
    symbol: str = Query(..., min_length=1, max_length=40),
    interval: str = Query("1d"),
    start: str | None = Query(None, description="ISO date/datetime; first sync defaults to conservative vendor window"),
    end: str | None = Query(None, description="ISO date/datetime; yfinance end is exclusive"),
    incremental: bool = Query(True),
    overlap_bars: int = Query(2, ge=1, le=100),
):
    try:
        return sync_yahoo_history(
            exchange=exchange.upper(), symbol=symbol.upper(), interval=interval,
            start=start, end=end, incremental=incremental, overlap_bars=overlap_bars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market-data vendor sync failed: {type(exc).__name__}: {exc}") from exc


@router.get("/market-data/stats")
def get_market_data_stats():
    return market_data_stats()


@router.get("/market-data/series/{exchange}/{symbol}")
def get_market_series(exchange: str, symbol: str, source_key: str | None = Query(None)):
    result = find_series(exchange, symbol, source_key=source_key)
    if result is None:
        raise HTTPException(status_code=404, detail="Audited market series not found")
    return result


@router.get("/market-data/series-id/{series_id}")
def get_market_series_by_id(series_id: str):
    result = get_series(series_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Audited market series not found")
    return result


@router.get("/market-data/bars/{series_id}")
def get_audited_bars(
    series_id: str,
    interval: str = Query(...),
    start: str | None = Query(None),
    end: str | None = Query(None),
    as_of: str | None = Query(None, description="Only bars with ts_close <= as_of are returned"),
    limit: int = Query(5000, ge=1, le=100000),
):
    if get_series(series_id) is None:
        raise HTTPException(status_code=404, detail="Audited market series not found")
    bars = query_bars(series_id, interval, start=start, end=end, as_of=as_of, limit=limit)
    return {
        "series_id": series_id,
        "interval": interval,
        "as_of": as_of,
        "bars": bars,
        "bar_count": len(bars),
        "no_lookahead": bool(as_of),
    }


@router.get("/market-data/issues/{series_id}")
def get_market_data_issues(series_id: str, interval: str | None = Query(None)):
    if get_series(series_id) is None:
        raise HTTPException(status_code=404, detail="Audited market series not found")
    return {
        "series_id": series_id,
        "issues": list_issues(series_id, interval=interval),
        "calendar_note": "Intraday regular-session checks do not invent holiday closures; official calendar validation remains separate.",
    }


@router.post("/market-data/derive/{series_id}")
def derive_market_timeframe(
    series_id: str,
    source_interval: str = Query(...),
    target_interval: str = Query(...),
    as_of: str | None = Query(None),
):
    try:
        return derive_timeframe(
            series_id, source_interval=source_interval, target_interval=target_interval, as_of=as_of
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/market-data/derive-standard/{series_id}")
def derive_market_standard_timeframes(
    series_id: str,
    source_interval: str = Query("1m"),
    as_of: str | None = Query(None),
):
    try:
        return derive_standard_timeframes(series_id, source_interval=source_interval, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/market-data/audit/{series_id}")
def audit_market_series(
    series_id: str,
    interval: str = Query(...),
    start: str | None = Query(None),
    end: str | None = Query(None),
):
    if get_series(series_id) is None:
        raise HTTPException(status_code=404, detail="Audited market series not found")
    return audit_series_interval(series_id, interval, start=start, end=end)


@router.post("/market-data/eras/{series_id}/rebuild-vendor-splits")
def rebuild_market_price_eras(series_id: str, interval: str | None = Query(None)):
    if get_series(series_id) is None:
        raise HTTPException(status_code=404, detail="Audited market series not found")
    result = rebuild_vendor_split_eras(series_id)
    assigned = assign_price_eras(series_id, interval) if interval else 0
    return {
        **result,
        "bars_assigned": assigned,
        "rule": "Vendor split markers create RAW-price comparability barriers; they do not auto-adjust prices and are not labelled exchange-verified.",
    }


@router.get("/replay/{exchange}/{symbol}")
def replay_market_state(
    exchange: str,
    symbol: str,
    as_of: str = Query(..., description="Offset-aware ISO timestamp"),
    intervals: str = Query("5m,15m,1h,1d"),
    source_key: str | None = Query(None),
    derive_missing_from: str | None = Query(None),
    bars_per_interval: int = Query(500, ge=1, le=5000),
    event_limit: int = Query(100, ge=0, le=1000),
):
    try:
        requested = [x.strip() for x in intervals.split(",") if x.strip()]
        return build_replay_snapshot(
            exchange=exchange.upper(), symbol=symbol.upper(), as_of=as_of,
            intervals=requested, source_key=source_key, derive_missing_from=derive_missing_from,
            bars_per_interval=bars_per_interval, event_limit=event_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/events/{event_id}/price-effects")
def calculate_event_price_effects(event_id: str, data: EventPriceEffectRequest):
    try:
        return compute_event_price_effects(
            event_id, series_id=data.series_id, interval=data.interval,
            horizons_sessions=data.horizons_sessions, persist=data.persist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/market-data/doctrine")
def market_data_doctrine():
    return {
        "phase": 3,
        "initial_vendor": YAHOO_SOURCE_KEY,
        "initial_vendor_official": False,
        "price_mode": "RAW_UNADJUSTED",
        "identity_rule": "Market series must map to a Phase-1 exchange listing/ISIN",
        "snapshot_rule": "Canonical normalized vendor response is hashed/archived; it is not mislabelled as raw HTTP payload",
        "replay_rule": "Only completed bars with ts_close <= as_of are visible",
        "event_rule": "Only corporate events announced at/before as_of are visible",
        "derivation_rule": "Higher timeframes use only source bars closed by as_of; partial target candles are excluded",
        "corporate_action_rule": "Vendor-reported splits create raw-price comparability barriers, not automatic adjusted truth",
        "execution": "OFF",
    }
