"""Trade Brain descriptive and prospective evidence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.tradebrain.audit_txt import audit_learning
from backend.tradebrain.evidence_baseline import build_evidence_baseline, latest_evidence_baseline
from backend.tradebrain.market_data_store import find_series
from backend.tradebrain.prospective_gap import (
    collect_prospective_gap_observations,
    stored_prospective_gap_observations,
)

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
        result = build_evidence_baseline(
            series["series_id"],
            as_of=as_of,
            intraday_interval=intraday_interval,
            persist=persist,
        )
        audit_learning(
            "EVIDENCE_BASELINE_BUILT",
            {
                "exchange": exchange.upper(),
                "symbol": symbol.upper(),
                "series_id": series["series_id"],
                "as_of": as_of,
                "intraday_interval": intraday_interval,
                "persist": persist,
                "result": result,
            },
            interpretation=(
                "Descriptive evidence update only. It may inform later hypotheses, but it does not by itself "
                "establish strategy edge, win rate, or trade authorization."
            ),
        )
        return result
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


@router.post("/prospective-gap-001/check/{exchange}/{symbol}")
def prospective_gap_check(
    exchange: str,
    symbol: str,
    as_of: str | None = Query(default=None),
    source_key: str | None = Query(default=None),
    persist: bool = Query(default=True),
):
    series = find_series(exchange, symbol, source_key=source_key)
    if series is None:
        raise HTTPException(status_code=404, detail="No audited market series found")
    try:
        result = collect_prospective_gap_observations(
            series["series_id"],
            as_of=as_of,
            persist=persist,
            require_verified_calendar=True,
        )
        audit_learning(
            "PROSPECTIVE_GAP_001_CHECK",
            {
                "exchange": exchange.upper(),
                "symbol": symbol.upper(),
                "series_id": series["series_id"],
                "as_of": as_of,
                "persist": persist,
                "result": result,
            },
            interpretation=(
                "Prospective evidence is preserved as future-only validation. Pre-freeze observations must not be "
                "backfilled to make the hypothesis appear validated; review only after the predefined evidence gates."
            ),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/prospective-gap-001/observations/{exchange}/{symbol}")
def prospective_gap_observations(
    exchange: str,
    symbol: str,
    source_key: str | None = Query(default=None),
):
    series = find_series(exchange, symbol, source_key=source_key)
    if series is None:
        raise HTTPException(status_code=404, detail="No audited market series found")
    return {
        "series_id": series["series_id"],
        "observations": stored_prospective_gap_observations(series["series_id"]),
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


@router.get("/doctrine")
def evidence_doctrine():
    return {
        "descriptive_before_strategic": True,
        "strategy_edge_claimed": False,
        "win_rate_claimed": False,
        "cross_price_era_returns_excluded": True,
        "only_completed_bars_at_or_before_as_of": True,
        "historical_exploration_cannot_validate_discovered_hypothesis": True,
        "prospective_gap_hypothesis_freeze_date": "2026-08-21",
        "hypotheses_must_enter_frozen_future_or_untouched_validation_before_promotion": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
        "human_readable_txt_audit": True,
        "hidden_chain_of_thought_persisted": False,
    }
