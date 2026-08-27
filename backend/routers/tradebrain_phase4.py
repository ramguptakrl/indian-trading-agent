"""Phase 4 Trade Brain API: strict replay outcomes and Focus Instrument Lab."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.tradebrain.focus_lab import (
    backfill_replay_outcomes,
    classify_instrument_regime,
    crash_guard_calibration,
    evaluate_plan_replay_outcome,
    event_category_relevance,
    focus_cohort_report,
    study_level_reliability,
)
from backend.tradebrain.focus_lab_store import focus_lab_stats, get_replay_outcome
from backend.tradebrain.market_data_store import get_series

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain-phase4"])


class ReplayOutcomeRequest(BaseModel):
    series_id: str | None = None
    interval: str = "5m"
    max_sessions: int = Field(default=10, ge=1, le=250)
    as_of: str | None = None
    persist: bool = True


class BackfillRequest(BaseModel):
    exchange: str | None = None
    ticker: str | None = None
    interval: str = "5m"
    max_sessions: int = Field(default=10, ge=1, le=250)
    as_of: str | None = None
    limit: int = Field(default=10000, ge=1, le=100000)


class LevelStudyRequest(BaseModel):
    interval: str = "5m"
    level_type: str
    level_price: float = Field(gt=0)
    tolerance_pct: float = Field(default=0.20, gt=0, le=10)
    reaction_pct: float = Field(default=0.50, gt=0, le=50)
    break_pct: float = Field(default=0.30, gt=0, le=50)
    horizon_bars: int = Field(default=6, ge=1, le=500)
    as_of: str | None = None
    persist: bool = True


def _require_series(series_id: str):
    series = get_series(series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Audited market series not found")
    return series


@router.post("/outcomes/{plan_id}/replay")
def replay_plan_outcome(plan_id: str, data: ReplayOutcomeRequest):
    try:
        return evaluate_plan_replay_outcome(
            plan_id,
            series_id=data.series_id,
            interval=data.interval,
            max_sessions=data.max_sessions,
            as_of=data.as_of,
            persist=data.persist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/outcomes/{plan_id}/replay/{series_id}")
def get_saved_replay_outcome(plan_id: str, series_id: str, interval: str = Query("5m")):
    result = get_replay_outcome(plan_id, series_id, interval)
    if result is None:
        raise HTTPException(status_code=404, detail="Replay outcome not found")
    return result


@router.post("/outcomes/backfill")
def backfill_outcomes(data: BackfillRequest):
    if data.exchange and data.exchange.upper() not in {"NSE", "BSE"}:
        raise HTTPException(status_code=400, detail="exchange must be NSE or BSE")
    return backfill_replay_outcomes(
        exchange=data.exchange.upper() if data.exchange else None,
        ticker=data.ticker.upper() if data.ticker else None,
        interval=data.interval,
        max_sessions=data.max_sessions,
        as_of=data.as_of,
        limit=data.limit,
    )


@router.get("/focus-lab/stats")
def get_focus_lab_stats():
    return focus_lab_stats()


@router.get("/focus-lab/{series_id}/regime")
def get_focus_regime(series_id: str, as_of: str = Query(..., description="Offset-aware ISO timestamp")):
    _require_series(series_id)
    try:
        return classify_instrument_regime(series_id, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/focus-lab/{series_id}/cohorts")
def get_focus_cohorts(series_id: str, interval: str = Query("5m")):
    _require_series(series_id)
    return focus_cohort_report(series_id=series_id, interval=interval)


@router.get("/focus-lab/{series_id}/crash-guard")
def get_crash_guard_calibration(series_id: str, interval: str = Query("5m")):
    _require_series(series_id)
    return crash_guard_calibration(series_id=series_id, interval=interval)


@router.post("/focus-lab/{series_id}/levels")
def study_focus_level(series_id: str, data: LevelStudyRequest):
    _require_series(series_id)
    try:
        return study_level_reliability(
            series_id=series_id,
            interval=data.interval,
            level_type=data.level_type,
            level_price=data.level_price,
            tolerance_pct=data.tolerance_pct,
            reaction_pct=data.reaction_pct,
            break_pct=data.break_pct,
            horizon_bars=data.horizon_bars,
            as_of=data.as_of,
            persist=data.persist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/focus-lab/{series_id}/event-relevance")
def get_event_relevance(
    series_id: str,
    horizon_sessions: int = Query(5, ge=1, le=250),
):
    _require_series(series_id)
    return event_category_relevance(series_id=series_id, horizon_sessions=horizon_sessions)


@router.get("/focus-lab/doctrine")
def focus_lab_doctrine():
    return {
        "phase": 4,
        "profile": "FOCUS_INSTRUMENT_LAB",
        "observation_kind": "HYPOTHETICAL_REPLAY",
        "real_outcome_boundary": "Replay never overwrites tb_trade_plan_outcomes/manual-real outcomes",
        "entry_rule": "Only a candle opening at/after plan evaluation may trigger entry",
        "ambiguity_rule": "Entry+exit threshold in one candle, or TP+SL in one candle, is AMBIGUOUS; intrabar order is never guessed",
        "mae_mfe_rule": "Entry candle is excluded; unknown post-exit extremes in the exit candle are excluded",
        "regime_rule": "Instrument regime uses only audited completed 1d bars available by as_of",
        "level_rule": "Support/resistance reliability is a transparent research heuristic with non-overlapping touch windows",
        "crash_guard_rule": "Existing Crash Guard states are audited counterfactually; this endpoint cannot change the hard gate",
        "event_rule": "Event-category movement is association, not causal attribution",
        "promotion_rule": "No soft metric may become a hard rule without separate challenger/walk-forward validation",
        "execution": "OFF",
    }
