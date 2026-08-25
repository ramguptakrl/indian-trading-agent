"""Automatic local evidence context for the BSE Position Guardian.

This module never fetches unaudited live web data. It reads Trade Brain's point-in-time
official corporate-event memory, first-seen news archive, and audited completed BSE daily
bars. Missing evidence stays UNKNOWN rather than being guessed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.corporate_actions import corporate_action_context
from backend.tradebrain.corporate_event_store import list_events
from backend.tradebrain.market_data_store import find_series
from backend.tradebrain.news_archive import query_news_known_by
from backend.tradebrain.regime_hardening import classify_instrument_regime_recent

METHOD_VERSION = "BSE_GUARDIAN_LOCAL_CONTEXT_V1"
IST = ZoneInfo("Asia/Kolkata")
_RANK = {"UNKNOWN": 0, "NORMAL": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4}
_CRITICAL_TERMS = (
    "trading halt", "suspension of trading", "insolvency", "bankruptcy", "default",
    "fraud", "cyber attack", "cyberattack", "data breach", "regulatory ban",
)
_HIGH_TERMS = (
    "penalty", "investigation", "show cause", "enforcement", "search and seizure",
    "system outage", "technical outage", "material litigation",
)


def _dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _max_risk(*values: str) -> str:
    return max((str(value or "UNKNOWN").upper() for value in values), key=lambda x: _RANK.get(x, 0), default="UNKNOWN")


def _text_risk(text: str) -> str:
    lowered = str(text or "").lower()
    if any(term in lowered for term in _CRITICAL_TERMS):
        return "CRITICAL"
    if any(term in lowered for term in _HIGH_TERMS):
        return "HIGH"
    return "NORMAL"


def _event_risk(events: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    recent_cutoff = now - timedelta(hours=48)
    included: list[dict[str, Any]] = []
    risk = "NORMAL"
    for event in events:
        known = _dt(event.get("fetched_at") or event.get("announced_at"))
        if known is None or known > now or known < recent_cutoff:
            continue
        importance = str(event.get("importance") or "").upper()
        category = str(event.get("category") or "").upper()
        text = f"{event.get('subject') or ''} {event.get('details') or ''}"
        text_risk = _text_risk(text)
        event_risk = text_risk
        if importance in {"CRITICAL", "HIGH"}:
            event_risk = _max_risk(event_risk, importance)
        elif category in {"REGULATORY", "RESULTS", "EARNINGS"}:
            event_risk = _max_risk(event_risk, "ELEVATED")
        risk = _max_risk(risk, event_risk)
        included.append({
            "event_id": event.get("event_id"),
            "category": category or None,
            "importance": importance or None,
            "first_known_at": known.isoformat(),
            "derived_risk": event_risk,
            "subject": str(event.get("subject") or "")[:240],
        })
    return {"risk": risk, "recent_events": included[:30], "window_hours": 48}


def _news_risk(news: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    recent_cutoff = now - timedelta(hours=24)
    included: list[dict[str, Any]] = []
    risk = "NORMAL"
    for item in news:
        first_seen = _dt(item.get("first_seen_at"))
        if first_seen is None or first_seen > now or first_seen < recent_cutoff:
            continue
        text = f"{item.get('title') or ''} {item.get('summary') or ''}"
        item_risk = _text_risk(text)
        if item_risk == "NORMAL":
            item_risk = "ELEVATED"
        risk = _max_risk(risk, item_risk)
        included.append({
            "article_id": item.get("article_id"),
            "title": str(item.get("title") or "")[:240],
            "first_seen_at": first_seen.isoformat(),
            "derived_risk": item_risk,
            "source": item.get("source"),
        })
    return {"risk": risk, "recent_news": included[:30], "window_hours": 24}


def _correction_from_regime(regime: dict[str, Any]) -> str:
    label = str(regime.get("regime") or "UNKNOWN").upper()
    close = regime.get("close")
    sma20 = regime.get("sma20")
    sma50 = regime.get("sma50")
    if label == "HIGH_VOL":
        if all(isinstance(x, (int, float)) for x in (close, sma20, sma50)) and float(close) < float(sma20) < float(sma50):
            return "HIGH_VOL_TREND_DOWN"
        return "HIGH_VOL"
    if label == "TREND_DOWN":
        return "TREND_DOWN"
    if label == "TREND_UP":
        return "TREND_UP"
    if label == "RANGE":
        return "RANGE"
    return "UNKNOWN"


def build_guardian_context(
    *,
    evaluated_at: str | datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = _dt(evaluated_at) or datetime.now(timezone.utc)
    # Inbox status is a human workflow state, not an evidence-retention boundary.
    # Reviewed/archived official events must remain available to point-in-time risk logic.
    events = list_events(status=None, limit=500, db_path=db_path)
    official = _event_risk(events, now=now)
    action = corporate_action_context(
        events,
        session_date=now.astimezone(IST).date(),
        known_by=now,
    )

    try:
        news = query_news_known_by(now, relevance="BSE_DIRECT", limit=100, db_path=db_path)
        news_state = _news_risk(news, now=now)
    except Exception as exc:
        news_state = {
            "risk": "UNKNOWN",
            "recent_news": [],
            "status": "UNAVAILABLE",
            "error_type": type(exc).__name__,
        }

    event_risk = _max_risk(official["risk"], news_state["risk"])
    if action.get("mechanical_gap_risk"):
        event_risk = _max_risk(event_risk, "ELEVATED")

    series = find_series("NSE", "BSE", db_path=db_path)
    if series:
        try:
            regime = classify_instrument_regime_recent(
                str(series["series_id"]), as_of=now.isoformat(), db_path=db_path
            )
            correction_state = _correction_from_regime(regime)
            correction_status = "AUDITED_BSE_DAILY_CONTEXT"
        except Exception as exc:
            regime = {"regime": "UNKNOWN", "error_type": type(exc).__name__}
            correction_state = "UNKNOWN"
            correction_status = "UNAVAILABLE"
    else:
        regime = {"regime": "UNKNOWN", "reason": "No audited NSE:BSE market series is stored"}
        correction_state = "UNKNOWN"
        correction_status = "NO_AUDITED_BSE_SERIES"

    return {
        "method_version": METHOD_VERSION,
        "evaluated_at": now.isoformat(),
        "event_risk": event_risk,
        "official_event_context": official,
        "news_context": news_state,
        "corporate_action_context": action,
        "correction_state": correction_state,
        "correction_context_status": correction_status,
        "audited_bse_regime": regime,
        "broader_market_correction_state": "UNKNOWN",
        "broader_market_correction_auto_complete": False,
        "hard_external_web_fetch_used": False,
        "unknown_evidence_is_not_guessed": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
