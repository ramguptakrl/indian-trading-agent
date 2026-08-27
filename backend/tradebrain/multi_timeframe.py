"""Audited BSE multi-timeframe feature snapshot.

Canonical hierarchy:
- 1D: dominant trend/regime
- 4H: key structure/levels (derived transparently from completed 60m bars)
- 1H: setup qualification
- 15m: entry refinement

This module produces research features only. It does not authorize trades, mutate hard
rules, or call a broker order endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.corporate_actions import corporate_action_context_from_store
from backend.tradebrain.market_data_store import get_series, query_bars

IST = ZoneInfo("Asia/Kolkata")
METHOD_VERSION = "BSE_MULTI_TIMEFRAME_SNAPSHOT_V1"


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _same_ist_date(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _dt(str(left["ts_open"])).astimezone(IST).date() == _dt(str(right["ts_open"])).astimezone(IST).date()


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = item * alpha + value * (1.0 - alpha)
    return value


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    seed = changes[:period]
    avg_gain = sum(max(x, 0.0) for x in seed) / period
    avg_loss = sum(max(-x, 0.0) for x in seed) / period
    for change in changes[period:]:
        avg_gain = ((period - 1) * avg_gain + max(change, 0.0)) / period
        avg_loss = ((period - 1) * avg_loss + max(-change, 0.0)) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) <= period:
        return None
    trs: list[float] = []
    for idx in range(1, len(bars)):
        high = float(bars[idx]["high"])
        low = float(bars[idx]["low"])
        prev_close = float(bars[idx - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(trs) < period:
        return None
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = ((period - 1) * value + tr) / period
    return value


def _frame_summary(bars: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    if not bars:
        return {"timeframe": label, "status": "NO_DATA"}
    closes = [float(x["close"]) for x in bars]
    last = bars[-1]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    rsi14 = _rsi(closes, 14)
    atr14 = _atr(bars, 14)
    close = closes[-1]
    if ema20 is None:
        trend = "INSUFFICIENT_DATA"
    elif ema50 is not None and close > ema20 > ema50:
        trend = "UP"
    elif ema50 is not None and close < ema20 < ema50:
        trend = "DOWN"
    elif close > ema20:
        trend = "ABOVE_EMA20"
    elif close < ema20:
        trend = "BELOW_EMA20"
    else:
        trend = "NEUTRAL"
    recent_volumes = [float(x.get("volume") or 0.0) for x in bars[-20:]]
    volume_median = median(recent_volumes) if recent_volumes else 0.0
    volume_ratio = (float(last.get("volume") or 0.0) / volume_median) if volume_median > 0 else None
    return {
        "timeframe": label,
        "status": "OK",
        "bars": len(bars),
        "last_open": round(float(last["open"]), 4),
        "last_high": round(float(last["high"]), 4),
        "last_low": round(float(last["low"]), 4),
        "last_close": round(close, 4),
        "last_bar_open": last["ts_open"],
        "last_bar_close": last["ts_close"],
        "ema20": round(ema20, 4) if ema20 is not None else None,
        "ema50": round(ema50, 4) if ema50 is not None else None,
        "rsi14": round(rsi14, 3) if rsi14 is not None else None,
        "atr14": round(atr14, 4) if atr14 is not None else None,
        "volume_vs_20bar_median": round(volume_ratio, 3) if volume_ratio is not None else None,
        "trend": trend,
    }


def rolling_4h_from_60m(hourly: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build rolling four-completed-hour structures without crossing an IST session date.

    Kite does not expose a native 4H candle. These are transparently labelled derived
    rolling 4x60m structures; they are useful for key-level research but must not be
    represented as an exchange-native candle series.
    """
    output: list[dict[str, Any]] = []
    if len(hourly) < 4:
        return output
    for end_idx in range(3, len(hourly)):
        window = hourly[end_idx - 3 : end_idx + 1]
        if any(not _same_ist_date(window[0], item) for item in window[1:]):
            continue
        output.append(
            {
                "ts_open": window[0]["ts_open"],
                "ts_close": window[-1]["ts_close"],
                "open": float(window[0]["open"]),
                "high": max(float(x["high"]) for x in window),
                "low": min(float(x["low"]) for x in window),
                "close": float(window[-1]["close"]),
                "volume": sum(float(x.get("volume") or 0.0) for x in window),
                "is_final": True,
                "is_derived": True,
                "derived_from_interval": "60m",
                "quality_flags": ["ROLLING_4X60M", "NOT_EXCHANGE_NATIVE_4H"],
            }
        )
    return output


def _key_levels(bars_4h: list[dict[str, Any]]) -> dict[str, float | None]:
    if not bars_4h:
        return {
            "recent_swing_high": None,
            "recent_swing_low": None,
            "range_high_20": None,
            "range_low_20": None,
        }
    recent = bars_4h[-5:]
    window = bars_4h[-20:]
    return {
        "recent_swing_high": round(max(float(x["high"]) for x in recent), 4),
        "recent_swing_low": round(min(float(x["low"]) for x in recent), 4),
        "range_high_20": round(max(float(x["high"]) for x in window), 4),
        "range_low_20": round(min(float(x["low"]) for x in window), 4),
    }


def _gap_snapshot(
    daily: list[dict[str, Any]],
    *,
    corporate_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(daily) < 2:
        return {"status": "INSUFFICIENT_DATA"}
    previous = daily[-2]
    current = daily[-1]
    prev_close = float(previous["close"])
    current_open = float(current["open"])
    if prev_close <= 0:
        return {"status": "INVALID_PREVIOUS_CLOSE"}
    gap_pct = (current_open / prev_close - 1.0) * 100.0
    if abs(gap_pct) < 1e-12:
        raw_direction = "FLAT_OPEN"
    else:
        raw_direction = "GAP_UP" if gap_pct > 0 else "GAP_DOWN"
    session_date = _dt(str(current["ts_open"])).astimezone(IST).date().isoformat()
    action = corporate_action or {}
    affected = bool(action.get("mechanical_gap_risk"))
    return {
        "status": "CORPORATE_ACTION_AFFECTED" if affected else "OK",
        "direction": "CORPORATE_ACTION_AFFECTED_OPEN" if affected else raw_direction,
        "gap_pct": round(gap_pct, 4),
        "raw_direction": raw_direction,
        "raw_gap_pct": round(gap_pct, 4),
        "previous_close": round(prev_close, 4),
        "session_open": round(current_open, 4),
        "gap_fill_reference": round(prev_close, 4),
        "session_date_ist": session_date,
        "eligible_as_normal_gap_signal": not affected,
        "mechanical_gap_risk": affected,
        "corporate_action_types": sorted({str(x.get("action_type")) for x in action.get("ex_date_actions", [])}),
        "stock_split_ex_date": bool(action.get("stock_split_ex_date")),
        "dividend_ex_date": bool(action.get("dividend_ex_date")),
        "interpretation": (
            "Raw open-vs-previous-close move is preserved for audit but excluded from normal gap interpretation on a known ex-date."
            if affected
            else "Raw open-vs-previous-close gap is comparable under currently known corporate-action context."
        ),
    }


def multi_timeframe_snapshot(
    series_id: str,
    *,
    as_of: str | datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    if as_of is None:
        cutoff = datetime.now(timezone.utc).isoformat()
    elif isinstance(as_of, datetime):
        value = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        cutoff = value.astimezone(timezone.utc).isoformat()
    else:
        cutoff = as_of

    daily = query_bars(series_id, "1d", as_of=cutoff, limit=500000, db_path=db_path)[-300:]
    hourly = query_bars(series_id, "60m", as_of=cutoff, limit=500000, db_path=db_path)[-2000:]
    fifteen = query_bars(series_id, "15m", as_of=cutoff, limit=500000, db_path=db_path)[-4000:]
    derived_4h = rolling_4h_from_60m(hourly)

    daily_summary = _frame_summary(daily, label="1D_TREND")
    h4_summary = _frame_summary(derived_4h, label="4H_STRUCTURE_DERIVED")
    h1_summary = _frame_summary(hourly, label="1H_SETUP")
    m15_summary = _frame_summary(fifteen, label="15M_ENTRY_REFINEMENT")

    action_context: dict[str, Any] = {
        "status": "NOT_APPLICABLE_NO_DAILY_BAR",
        "mechanical_gap_risk": False,
        "raw_price_series_structural_break": False,
    }
    if daily and str(series.get("symbol") or "").upper() == "BSE":
        session_date = _dt(str(daily[-1]["ts_open"])).astimezone(IST).date().isoformat()
        action_context = corporate_action_context_from_store(
            session_date=session_date,
            known_by=cutoff,
            db_path=db_path,
        )

    alignment = "UNKNOWN"
    trends = [daily_summary.get("trend"), h4_summary.get("trend"), h1_summary.get("trend")]
    bullish = sum(t in {"UP", "ABOVE_EMA20"} for t in trends)
    bearish = sum(t in {"DOWN", "BELOW_EMA20"} for t in trends)
    if action_context.get("raw_price_series_structural_break"):
        alignment = "PRICE_SERIES_STRUCTURAL_BREAK"
    elif bullish >= 3:
        alignment = "BULLISH_ALIGNED"
    elif bearish >= 3:
        alignment = "BEARISH_ALIGNED"
    elif bullish >= 2:
        alignment = "BULLISH_LEAN"
    elif bearish >= 2:
        alignment = "BEARISH_LEAN"
    elif daily:
        alignment = "MIXED"

    return {
        "method_version": METHOD_VERSION,
        "series_id": series_id,
        "exchange": series.get("exchange"),
        "symbol": series.get("symbol"),
        "as_of": cutoff,
        "hierarchy": ["1D_TREND", "4H_STRUCTURE", "1H_SETUP", "15M_ENTRY_REFINEMENT"],
        "frames": {
            "1d": daily_summary,
            "4h": {**h4_summary, "levels": _key_levels(derived_4h)},
            "1h": h1_summary,
            "15m": m15_summary,
        },
        "opening_gap": _gap_snapshot(daily, corporate_action=action_context),
        "corporate_action_context": action_context,
        "alignment": alignment,
        "price_comparability_block": bool(action_context.get("raw_price_series_structural_break")),
        "requires_price_era_rebuild": bool(action_context.get("raw_price_series_structural_break")),
        "4h_construction": "ROLLING_4X_COMPLETED_60M_SAME_IST_SESSION_DATE",
        "4h_exchange_native": False,
        "research_only": True,
        "automatic_policy_change": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
