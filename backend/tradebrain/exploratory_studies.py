"""Exploratory studies for Trade Brain evidence generation.

These studies intentionally do not enter Phase-5 promotion directly. They are allowed to
look across historical evidence to generate hypotheses, but any hypothesis discovered
here must be frozen and validated on future/out-of-sample data before it can influence a
runtime soft parameter.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.tradebrain.market_data_store import get_series, query_bars

GAP_STUDY_VERSION = "BSE_OPENING_GAP_EXPLORATION_V1"
DEFAULT_GAP_THRESHOLDS = (0.5, 1.0, 1.5)


def _parse_dt(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _same_price_era(prev: dict[str, Any], current: dict[str, Any]) -> bool:
    left = prev.get("era_id")
    right = current.get("era_id")
    if left is None and right is None:
        return True
    return bool(left and right and left == right)


def _pct(num: float) -> float:
    return round(num * 100.0, 6)


def _rate(num: int, den: int) -> float | None:
    return round(num / den * 100.0, 3) if den else None


def _empty_bucket() -> dict[str, Any]:
    return {
        "n": 0,
        "filled_anytime": 0,
        "closed_reversed_vs_gap": 0,
        "closed_continued_with_gap": 0,
        "closed_through_previous_close": 0,
    }


def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
    n = int(bucket["n"])
    return {
        **bucket,
        "fill_rate_pct": _rate(int(bucket["filled_anytime"]), n),
        "close_reversal_rate_pct": _rate(int(bucket["closed_reversed_vs_gap"]), n),
        "close_continuation_rate_pct": _rate(int(bucket["closed_continued_with_gap"]), n),
        "close_through_previous_close_rate_pct": _rate(int(bucket["closed_through_previous_close"]), n),
    }


def opening_gap_exploration(
    series_id: str,
    *,
    thresholds_pct: Iterable[float] = DEFAULT_GAP_THRESHOLDS,
    as_of: str | datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Measure daily opening-gap behavior without pretending it is a strategy test.

    Definitions use only daily OHLC facts:
    - GAP_UP fill: session low <= previous close
    - GAP_DOWN fill: session high >= previous close
    - reversal at close: close moved opposite the opening gap relative to session open
    - continuation at close: close moved with the opening gap relative to session open
    - through previous close: close crossed all the way through previous close

    No intraday ordering is inferred. A day can both fill and later continue/reverse.
    """
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    cutoff = _parse_dt(as_of).isoformat()
    bars = query_bars(series_id, "1d", as_of=cutoff, limit=500000, db_path=db_path)
    thresholds = sorted({round(float(x), 6) for x in thresholds_pct if float(x) > 0})
    if not thresholds:
        raise ValueError("At least one positive gap threshold is required")

    buckets: dict[float, dict[str, dict[str, Any]]] = {
        threshold: {"GAP_UP": _empty_bucket(), "GAP_DOWN": _empty_bucket()} for threshold in thresholds
    }
    by_year: dict[float, dict[str, dict[str, dict[str, Any]]]] = {
        threshold: defaultdict(lambda: {"GAP_UP": _empty_bucket(), "GAP_DOWN": _empty_bucket()})
        for threshold in thresholds
    }
    excluded_cross_era = 0
    observations = 0

    for idx in range(1, len(bars)):
        prev = bars[idx - 1]
        bar = bars[idx]
        if not _same_price_era(prev, bar):
            excluded_cross_era += 1
            continue
        prev_close = float(prev["close"])
        o = float(bar["open"])
        h = float(bar["high"])
        l = float(bar["low"])
        c = float(bar["close"])
        if prev_close <= 0 or o <= 0:
            continue
        gap_pct = _pct(o / prev_close - 1.0)
        abs_gap = abs(gap_pct)
        if gap_pct == 0:
            continue
        direction = "GAP_UP" if gap_pct > 0 else "GAP_DOWN"
        year = datetime.fromisoformat(bar["ts_open"]).year
        observations += 1

        if direction == "GAP_UP":
            facts = {
                "filled_anytime": l <= prev_close,
                "closed_reversed_vs_gap": c < o,
                "closed_continued_with_gap": c > o,
                "closed_through_previous_close": c <= prev_close,
            }
        else:
            facts = {
                "filled_anytime": h >= prev_close,
                "closed_reversed_vs_gap": c > o,
                "closed_continued_with_gap": c < o,
                "closed_through_previous_close": c >= prev_close,
            }

        for threshold in thresholds:
            if abs_gap < threshold:
                continue
            for target in (buckets[threshold][direction], by_year[threshold][str(year)][direction]):
                target["n"] += 1
                for key, value in facts.items():
                    if value:
                        target[key] += 1

    finalized = {
        str(threshold): {direction: _finalize(bucket) for direction, bucket in directional.items()}
        for threshold, directional in buckets.items()
    }
    finalized_years: dict[str, Any] = {}
    for threshold, years in by_year.items():
        finalized_years[str(threshold)] = {
            year: {direction: _finalize(bucket) for direction, bucket in directional.items()}
            for year, directional in sorted(years.items())
        }

    return {
        "method_version": GAP_STUDY_VERSION,
        "as_of": cutoff,
        "series": {
            "series_id": series_id,
            "exchange": series.get("exchange"),
            "symbol": series.get("symbol"),
            "source_key": series.get("source_key"),
            "source_official": bool((series.get("source_metadata") or {}).get("official")),
            "price_mode": series.get("price_mode"),
        },
        "daily_bars": len(bars),
        "eligible_directional_gap_observations": observations,
        "cross_price_era_transitions_excluded": excluded_cross_era,
        "thresholds_pct": thresholds,
        "cohorts": finalized,
        "yearly_cohorts": finalized_years,
        "interpretation_contract": {
            "intraday_order_inferred": False,
            "exploratory_only": True,
            "historical_full_sample_was_available_during_hypothesis_generation": True,
            "eligible_for_direct_phase5_promotion": False,
            "required_next_step": "Freeze a specific rule/threshold and validate prospectively or on genuinely untouched evidence.",
            "trade_authorization": False,
            "order_execution_allowed": False,
        },
    }
