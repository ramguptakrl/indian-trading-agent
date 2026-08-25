"""Look-ahead-safe audited context injected into live/dated BSE decision graphs."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.corporate_action_eras import sync_official_bse_split_price_eras
from backend.tradebrain.kite_data import KITE_SOURCE_KEY
from backend.tradebrain.market_data_store import find_series
from backend.tradebrain.multi_timeframe import multi_timeframe_snapshot

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = time(15, 30)
CONTEXT_VERSION = "BSE_LIVE_DECISION_CONTEXT_V1"


def _as_of_for_trade_date(trade_date: str, *, now: datetime | None = None) -> datetime:
    requested = date.fromisoformat(str(trade_date))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current_ist = current.astimezone(IST)
    if requested > current_ist.date():
        raise ValueError("Trade Brain cannot build decision context for a future India market date")
    if requested == current_ist.date():
        return current.astimezone(timezone.utc)
    return datetime.combine(requested, MARKET_CLOSE, tzinfo=IST).astimezone(timezone.utc)


def build_bse_decision_context(
    trade_date: str,
    *,
    now: datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Return audited D→4H→1H→15m evidence or an explicit fail-closed absence state."""
    as_of = _as_of_for_trade_date(trade_date, now=now)

    series = find_series(
        "NSE",
        "BSE",
        source_key=KITE_SOURCE_KEY,
        price_mode="RAW_UNADJUSTED",
        db_path=db_path,
    )
    selection = "PREFERRED_KITE_AUDITED_SERIES"
    if series is None:
        series = find_series("NSE", "BSE", price_mode="RAW_UNADJUSTED", db_path=db_path)
        selection = "AUDITED_FALLBACK_SERIES" if series is not None else "NO_AUDITED_SERIES"

    if series is None:
        return {
            "context_version": CONTEXT_VERSION,
            "status": "MISSING_AUDITED_SERIES",
            "ticker": "BSE",
            "exchange": "NSE",
            "as_of": as_of.isoformat(),
            "series_selection": selection,
            "required_hierarchy": ["1D_TREND", "4H_STRUCTURE", "1H_SETUP", "15M_ENTRY_REFINEMENT"],
            "candidate_evidence_complete": False,
            "reason": "No audited NSE:BSE raw-price series is available. Models must not invent timeframe evidence.",
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    # Before any raw-price comparison, let explicit official split ex-dates define the
    # authoritative comparability eras for this audited series. This is idempotent and
    # never changes OHLC values. Dividends do not create a new era.
    official_eras = sync_official_bse_split_price_eras(
        str(series["series_id"]),
        known_by=as_of,
        db_path=db_path,
    )

    snapshot = multi_timeframe_snapshot(
        str(series["series_id"]),
        as_of=as_of,
        db_path=db_path,
    )
    frames = snapshot.get("frames") or {}
    missing = [
        label
        for key, label in (("1d", "1D_TREND"), ("4h", "4H_STRUCTURE"), ("1h", "1H_SETUP"), ("15m", "15M_ENTRY_REFINEMENT"))
        if (frames.get(key) or {}).get("status") != "OK"
    ]
    structural_break = bool(snapshot.get("price_comparability_block"))
    complete = not missing and not structural_break

    return {
        "context_version": CONTEXT_VERSION,
        "status": "READY" if complete else ("PRICE_COMPARABILITY_BLOCK" if structural_break else "INCOMPLETE_TIMEFRAME_EVIDENCE"),
        "ticker": "BSE",
        "exchange": "NSE",
        "as_of": as_of.isoformat(),
        "series_id": series.get("series_id"),
        "source_key": series.get("source_key"),
        "series_selection": selection,
        "required_hierarchy": snapshot.get("hierarchy"),
        "frames": frames,
        "alignment": snapshot.get("alignment"),
        "opening_gap": snapshot.get("opening_gap"),
        "corporate_action_context": snapshot.get("corporate_action_context"),
        "official_split_price_eras": official_eras,
        "missing_frames": missing,
        "candidate_evidence_complete": complete,
        "price_comparability_block": structural_break,
        "four_hour_exchange_native": False,
        "four_hour_construction": snapshot.get("4h_construction"),
        "research_only_features": True,
        "automatic_policy_change": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def decision_context_for_prompt(context: dict[str, Any]) -> str:
    """Compact deterministic text for model prompts without dropping provenance/status."""
    status = str(context.get("status") or "UNKNOWN")
    lines = [
        f"Audited multi-timeframe context status: {status}",
        f"As-of: {context.get('as_of')}",
        f"Source: {context.get('source_key') or 'NONE'} ({context.get('series_selection')})",
        f"Candidate evidence complete: {bool(context.get('candidate_evidence_complete'))}",
    ]
    if status == "MISSING_AUDITED_SERIES":
        lines.append(str(context.get("reason") or "No audited timeframe evidence is available."))
        lines.append("Do not invent 1D/4H/1H/15m values; use WAIT / NO TRADE when these are required.")
        return "\n".join(lines)

    frames = context.get("frames") or {}
    for key, label in (("1d", "1D"), ("4h", "4H derived"), ("1h", "1H"), ("15m", "15m")):
        frame = frames.get(key) or {}
        lines.append(
            f"{label}: status={frame.get('status')} trend={frame.get('trend')} close={frame.get('last_close')} "
            f"EMA20={frame.get('ema20')} EMA50={frame.get('ema50')} RSI14={frame.get('rsi14')} "
            f"ATR14={frame.get('atr14')} last_close_time={frame.get('last_bar_close')}"
        )
    h4 = frames.get("4h") or {}
    lines.append(f"4H levels: {h4.get('levels')}")
    lines.append(f"Alignment: {context.get('alignment')}")
    lines.append(f"Opening gap: {context.get('opening_gap')}")
    lines.append(f"Corporate action context: {context.get('corporate_action_context')}")
    lines.append(f"Official split price eras: {context.get('official_split_price_eras')}")
    if context.get("missing_frames"):
        lines.append(f"Missing/incomplete frames: {context.get('missing_frames')}")
    if context.get("price_comparability_block"):
        lines.append("Raw-price comparability is BLOCKED by corporate-action context; do not interpret raw gap/position geometry as normal.")
    return "\n".join(lines)
