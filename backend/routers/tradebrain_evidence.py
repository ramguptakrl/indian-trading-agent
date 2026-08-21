"""Trade Brain descriptive evidence endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from backend.tradebrain.evidence_baseline import build_evidence_baseline, latest_evidence_baseline
from backend.tradebrain.market_data_store import find_series

router = APIRouter(prefix="/api/tradebrain/evidence", tags=["tradebrain-evidence"])


@router.get("/baseline/{exchange}/{symbol}")
def evidence_baseline(
    exchange: str,
    symbol: str,
    as_of: str | None = Query(default=None),
    intraday_interval: str = Query(default="5m"),
    source_key: str | None = Query(default=None),
    persist: bool = Query(default=True),
):
    series = find_series(exchange, symbol, source_key=source_key)
    if series is None:
        raise HTTPException(status_code=404, detail="No audited market series found; sync market data first")
    try:
        return build_evidence_baseline(
            series["series_id"],
            as_of=as_of,
            intraday_interval=intraday_interval,
            persist=persist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/latest/{exchange}/{symbol}")
def latest_baseline(exchange: str, symbol: str, source_key: str | None = Query(default=None)):
    series = find_series(exchange, symbol, source_key=source_key)
    if series is None:
        raise HTTPException(status_code=404, detail="No audited market series found")
    latest = latest_evidence_baseline(series["series_id"])
    if latest is None:
        raise HTTPException(status_code=404, detail="No persisted evidence baseline found")
    return latest


@router.get("/doctrine")
def evidence_doctrine():
    return {
        "descriptive_before_strategic": True,
        "strategy_edge_claimed": False,
        "win_rate_claimed": False,
        "cross_price_era_returns_excluded": True,
        "only_completed_bars_at_or_before_as_of": True,
        "hypotheses_must_enter_frozen_walk_forward_before_promotion": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
