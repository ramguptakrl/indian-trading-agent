"""Look-ahead-safe replay and event -> future-price-effect study for Phase 3."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.db import DB_PATH
from backend.tradebrain.corporate_event_store import get_event
from backend.tradebrain.market_data import derive_timeframe, validate_bars
from backend.tradebrain.market_data_store import (
    find_series,
    get_series,
    list_issues,
    query_bars,
    store_event_price_effect,
)

IST = ZoneInfo("Asia/Kolkata")
EVENT_EFFECT_METHOD = "FIRST_BAR_OPEN_AT_OR_AFTER_EVENT_TO_NTH_TRADING_SESSION_CLOSE_V1"


def _connect_read(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _events_as_of(series: dict[str, Any], as_of: str, *, limit: int = 100, db_path: str | None = None) -> list[dict[str, Any]]:
    conn = _connect_read(db_path)
    try:
        clauses = ["announced_at IS NOT NULL", "announced_at<=?"]
        args: list[Any] = [as_of]
        if series.get("issuer_entity_id"):
            clauses.append("issuer_entity_id=?")
            args.append(series["issuer_entity_id"])
        else:
            clauses.extend(["exchange=?", "listing_symbol=?"])
            args.extend([series["exchange"], series["symbol"]])
        args.append(max(1, min(limit, 1000)))
        rows = conn.execute(
            f"""
            SELECT event_id, exchange, listing_symbol, isin, issuer_entity_id,
                   subject, category, importance, importance_basis, announced_at,
                   source_key, source_url, attachment_url, identity_status
            FROM tb_corporate_events
            WHERE {' AND '.join(clauses)}
            ORDER BY announced_at DESC
            LIMIT ?
            """,
            args,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def build_replay_snapshot(
    *,
    exchange: str,
    symbol: str,
    as_of: str,
    intervals: list[str] | None = None,
    source_key: str | None = None,
    derive_missing_from: str | None = None,
    bars_per_interval: int = 500,
    event_limit: int = 100,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Reconstruct only evidence that was closed/known at `as_of`."""
    cutoff = _parse_utc(as_of).isoformat()
    series = find_series(exchange, symbol, source_key=source_key, db_path=db_path)
    if series is None:
        raise ValueError(f"No audited market series for {exchange.upper()}:{symbol.upper()}")

    requested = intervals or [series.get("base_interval") or "1d"]
    frames: dict[str, Any] = {}
    for interval in requested:
        bars = query_bars(
            series["series_id"], interval, as_of=cutoff, limit=max(1, bars_per_interval), db_path=db_path
        )
        if not bars and derive_missing_from and interval != derive_missing_from:
            derive_timeframe(
                series["series_id"], source_interval=derive_missing_from,
                target_interval=interval, as_of=cutoff, db_path=db_path,
            )
            bars = query_bars(
                series["series_id"], interval, as_of=cutoff,
                limit=max(1, bars_per_interval), db_path=db_path,
            )
        # Return the most recent N without querying future bars.
        if len(bars) > bars_per_interval:
            bars = bars[-bars_per_interval:]
        latest_close = bars[-1]["ts_close"] if bars else None
        frames[interval] = {
            "bars": bars,
            "bar_count": len(bars),
            "latest_completed_bar_close": latest_close,
            "lookahead_check": latest_close is None or _parse_utc(latest_close) <= _parse_utc(cutoff),
        }

    events = _events_as_of(series, cutoff, limit=event_limit, db_path=db_path)
    issues = list_issues(series["series_id"], unresolved_only=True, db_path=db_path)
    return {
        "series": series,
        "as_of": cutoff,
        "frames": frames,
        "events_known_by_as_of": events,
        "open_market_data_issues": issues,
        "replay_contract": {
            "future_bars_excluded": True,
            "incomplete_bars_excluded": True,
            "future_events_excluded": True,
            "derived_bars_use_only_source_bars_closed_by_as_of": True,
            "calendar_note": "Regular NSE/BSE session checks are clock-based; official holiday calendar validation is a separate source concern.",
        },
        "all_lookahead_checks_pass": all(frame["lookahead_check"] for frame in frames.values()),
    }


def audit_series_interval(
    series_id: str,
    interval: str,
    *,
    start: str | None = None,
    end: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    bars = query_bars(series_id, interval, start=start, end=end, limit=500000, db_path=db_path)
    issues = validate_bars(bars, interval)
    return {
        "series_id": series_id,
        "interval": interval,
        "bars_checked": len(bars),
        "issues": issues,
        "issue_count": len(issues),
        "calendar_verified": False,
        "meaning": "Geometry, spacing and regular-session audit; does not infer exchange holidays from missing daily sessions.",
    }


def _event_matches_series(event: dict[str, Any], series: dict[str, Any]) -> bool:
    if event.get("issuer_entity_id") and series.get("issuer_entity_id"):
        return event["issuer_entity_id"] == series["issuer_entity_id"]
    if event.get("isin") and series.get("isin"):
        return event["isin"] == series["isin"]
    return event.get("exchange") == series.get("exchange") and event.get("listing_symbol") == series.get("symbol")


def compute_event_price_effects(
    event_id: str,
    *,
    series_id: str,
    interval: str = "5m",
    horizons_sessions: list[int] | None = None,
    persist: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Measure post-announcement movement without using a candle already in progress."""
    event = get_event(event_id, db_path=db_path)
    if event is None:
        raise ValueError(f"Unknown corporate event: {event_id}")
    if not event.get("announced_at"):
        raise ValueError("Event has no announced_at timestamp")
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    if not _event_matches_series(event, series):
        raise ValueError("Event identity does not match the requested market series")

    event_time = _parse_utc(event["announced_at"])
    bars = query_bars(series_id, interval, start=event_time.isoformat(), limit=500000, db_path=db_path)
    # Strict rule: first bar must START at/after event time. A candle that started before
    # the event contains pre-event information and is never used as the anchor.
    eligible = [bar for bar in bars if _parse_utc(bar["ts_open"]) >= event_time]
    if not eligible:
        return {
            "event_id": event_id, "series_id": series_id, "interval": interval,
            "status": "NO_FUTURE_BARS", "effects": [],
        }

    anchor = eligible[0]
    anchor_price = float(anchor["open"])
    session_dates: list[date] = []
    for bar in eligible:
        day = _parse_utc(bar["ts_open"]).astimezone(IST).date()
        if day not in session_dates:
            session_dates.append(day)

    horizons = sorted(set(horizons_sessions or [1, 3, 5, 10]))
    effects: list[dict[str, Any]] = []
    for horizon in horizons:
        if horizon < 1:
            continue
        if len(session_dates) < horizon:
            effects.append({
                "event_id": event_id, "series_id": series_id, "interval": interval,
                "horizon_sessions": horizon, "status": "INSUFFICIENT_FUTURE_SESSIONS",
                "available_sessions": len(session_dates),
            })
            continue

        target_day = session_dates[horizon - 1]
        window = [
            bar for bar in eligible
            if _parse_utc(bar["ts_open"]).astimezone(IST).date() <= target_day
        ]
        endpoint = window[-1]
        eras = {bar.get("era_id") for bar in window if bar.get("era_id")}
        crosses_era = len(eras) > 1
        if crosses_era:
            effects.append({
                "event_id": event_id, "series_id": series_id, "interval": interval,
                "horizon_sessions": horizon, "status": "RAW_PRICE_CROSSES_COMPARABILITY_ERA",
                "bars_observed": len(window), "era_ids": sorted(eras),
                "method": EVENT_EFFECT_METHOD,
            })
            continue

        end_price = float(endpoint["close"])
        lows = [float(bar["low"]) for bar in window]
        highs = [float(bar["high"]) for bar in window]
        effect = {
            "event_id": event_id,
            "series_id": series_id,
            "interval": interval,
            "horizon_sessions": horizon,
            "status": "COMPLETE",
            "anchor_bar_open": anchor["ts_open"],
            "anchor_price": anchor_price,
            "end_bar_close": endpoint["ts_close"],
            "end_price": end_price,
            "return_pct": (end_price / anchor_price - 1.0) * 100.0,
            "mae_pct": (min(lows) / anchor_price - 1.0) * 100.0,
            "mfe_pct": (max(highs) / anchor_price - 1.0) * 100.0,
            "bars_observed": len(window),
            "method": EVENT_EFFECT_METHOD,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "raw_price_era_id": next(iter(eras), None),
        }
        if persist:
            store_event_price_effect(effect, db_path=db_path)
        effects.append(effect)

    return {
        "event_id": event_id,
        "series_id": series_id,
        "interval": interval,
        "event_announced_at": event["announced_at"],
        "anchor_rule": "First completed-data series bar whose OPEN timestamp is >= event announcement timestamp",
        "price_mode": series["price_mode"],
        "effects": effects,
        "persisted": persist,
        "lookahead_safe": True,
    }
