"""Research-only candlestick and fair-value-gap studies for BSE Ltd.

These features are intentionally exploratory. They may generate hypotheses but cannot
modify live policy, authorize a trade, or place broker orders.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.market_data_store import get_series, query_bars

IST = ZoneInfo("Asia/Kolkata")
METHOD_VERSION = "BSE_PATTERN_LAB_V1"


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _session_date(bar: dict[str, Any]):
    return _dt(str(bar["ts_open"])).astimezone(IST).date()


def _body(bar: dict[str, Any]) -> float:
    return abs(float(bar["close"]) - float(bar["open"]))


def _range(bar: dict[str, Any]) -> float:
    return max(0.0, float(bar["high"]) - float(bar["low"]))


def _patterns(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    out: list[str] = []
    o = float(current["open"])
    h = float(current["high"])
    l = float(current["low"])
    c = float(current["close"])
    body = abs(c - o)
    span = max(h - l, 1e-12)
    upper = h - max(o, c)
    lower = min(o, c) - l

    if body / span <= 0.10:
        out.append("DOJI_SHAPE")
    if lower >= max(2.0 * body, span * 0.45) and upper <= max(body, span * 0.20):
        out.append("HAMMER_SHAPE")
    if upper >= max(2.0 * body, span * 0.45) and lower <= max(body, span * 0.20):
        out.append("SHOOTING_STAR_SHAPE")

    if previous is not None:
        po = float(previous["open"])
        ph = float(previous["high"])
        pl = float(previous["low"])
        pc = float(previous["close"])
        if h < ph and l > pl:
            out.append("INSIDE_BAR")
        previous_bear = pc < po
        previous_bull = pc > po
        current_bull = c > o
        current_bear = c < o
        if previous_bear and current_bull and o <= pc and c >= po:
            out.append("BULLISH_ENGULFING_BODY")
        if previous_bull and current_bear and o >= pc and c <= po:
            out.append("BEARISH_ENGULFING_BODY")
    return out


def _forward_return(bars: list[dict[str, Any]], idx: int, horizon: int) -> float | None:
    end = idx + horizon
    if end >= len(bars):
        return None
    if _session_date(bars[idx]) != _session_date(bars[end]):
        return None
    start_close = float(bars[idx]["close"])
    if start_close <= 0:
        return None
    return (float(bars[end]["close"]) / start_close - 1.0) * 100.0


def _summarize_returns(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean_return_pct": None, "positive_rate_pct": None}
    return {
        "n": len(values),
        "mean_return_pct": round(mean(values), 5),
        "positive_rate_pct": round(sum(x > 0 for x in values) / len(values) * 100.0, 3),
    }


def _fvg_study(bars: list[dict[str, Any]], *, max_fill_bars: int = 16) -> dict[str, Any]:
    results = {
        "BULLISH_FVG": {"n": 0, "filled_within_window": 0, "sizes_pct": []},
        "BEARISH_FVG": {"n": 0, "filled_within_window": 0, "sizes_pct": []},
    }
    for idx in range(2, len(bars)):
        first = bars[idx - 2]
        third = bars[idx]
        if _session_date(first) != _session_date(third):
            continue
        first_high = float(first["high"])
        first_low = float(first["low"])
        third_high = float(third["high"])
        third_low = float(third["low"])
        close = float(third["close"])
        if close <= 0:
            continue

        kind = None
        boundary = None
        size = None
        if third_low > first_high:
            kind = "BULLISH_FVG"
            boundary = first_high
            size = (third_low - first_high) / close * 100.0
        elif third_high < first_low:
            kind = "BEARISH_FVG"
            boundary = first_low
            size = (first_low - third_high) / close * 100.0
        if kind is None:
            continue

        bucket = results[kind]
        bucket["n"] += 1
        bucket["sizes_pct"].append(size)
        session = _session_date(third)
        filled = False
        for future in bars[idx + 1 : idx + 1 + max_fill_bars]:
            if _session_date(future) != session:
                break
            if kind == "BULLISH_FVG" and float(future["low"]) <= float(boundary):
                filled = True
                break
            if kind == "BEARISH_FVG" and float(future["high"]) >= float(boundary):
                filled = True
                break
        if filled:
            bucket["filled_within_window"] += 1

    output: dict[str, Any] = {}
    for kind, bucket in results.items():
        n = int(bucket["n"])
        sizes = list(bucket["sizes_pct"])
        output[kind] = {
            "n": n,
            "fill_rate_within_16_bars_pct": round(bucket["filled_within_window"] / n * 100.0, 3) if n else None,
            "mean_gap_size_pct": round(mean(sizes), 5) if sizes else None,
        }
    return output


def pattern_lab_study(
    series_id: str,
    *,
    as_of: str | datetime | None = None,
    db_path: str | None = None,
    interval: str = "15m",
) -> dict[str, Any]:
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    if interval not in {"15m", "60m", "1d"}:
        raise ValueError("Pattern Lab interval must be 15m, 60m or 1d")
    if as_of is None:
        cutoff = datetime.now(timezone.utc).isoformat()
    elif isinstance(as_of, datetime):
        value = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        cutoff = value.astimezone(timezone.utc).isoformat()
    else:
        cutoff = as_of

    bars = query_bars(series_id, interval, as_of=cutoff, limit=500000, db_path=db_path)
    returns_4: dict[str, list[float]] = defaultdict(list)
    returns_16: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)

    for idx, bar in enumerate(bars):
        previous = bars[idx - 1] if idx > 0 and _session_date(bars[idx - 1]) == _session_date(bar) else None
        for pattern in _patterns(previous, bar):
            counts[pattern] += 1
            r4 = _forward_return(bars, idx, 4)
            r16 = _forward_return(bars, idx, 16)
            if r4 is not None:
                returns_4[pattern].append(r4)
            if r16 is not None:
                returns_16[pattern].append(r16)

    candle_summary = {
        pattern: {
            "occurrences": counts[pattern],
            "forward_4_bar_raw_return": _summarize_returns(returns_4[pattern]),
            "forward_16_bar_raw_return": _summarize_returns(returns_16[pattern]),
        }
        for pattern in sorted(counts)
    }

    return {
        "method_version": METHOD_VERSION,
        "series_id": series_id,
        "exchange": series.get("exchange"),
        "symbol": series.get("symbol"),
        "interval": interval,
        "as_of": cutoff,
        "bars": len(bars),
        "candlestick_shapes": candle_summary,
        "fair_value_gaps": _fvg_study(bars) if interval == "15m" else {},
        "definitions": {
            "candlestick_context_claimed": False,
            "fvg_definition": "3-candle imbalance: candle3 low > candle1 high (bullish) or candle3 high < candle1 low (bearish)",
            "forward_returns_are_raw_descriptive_not_strategy_pnl": True,
            "same_session_forward_windows_for_intraday": True,
        },
        "exploratory_only": True,
        "eligible_for_direct_live_promotion": False,
        "required_next_step": "Freeze any promising BSE-specific rule and validate on untouched chronological evidence.",
        "automatic_policy_change": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
