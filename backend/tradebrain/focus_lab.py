"""Trade Brain Phase 4: strict replay outcomes and Focus Instrument Lab.

This module turns Phase-3 audited candles into falsifiable research outcomes. It is
conservative by design: coarse-bar intrabar ordering is never guessed, hypothetical
replay is kept separate from real/manual outcomes, and all calibration outputs remain
research evidence rather than automatic policy changes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timezone
import math
from statistics import median, pstdev
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.focus_lab_store import (
    event_category_effect_rows,
    get_plan,
    list_plans,
    list_replay_outcomes,
    persist_level_study,
    upsert_replay_outcome,
)
from backend.tradebrain.market_data_store import find_series, get_series, query_bars

IST = ZoneInfo("Asia/Kolkata")
OUTCOME_METHOD_VERSION = "STRICT_BAR_REPLAY_V1"
LEVEL_METHOD_VERSION = "LEVEL_REACTION_REPLAY_V1"
REGIME_METHOD_VERSION = "AUDITED_INSTRUMENT_REGIME_V1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | datetime) -> datetime:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _utc_iso(value: str | datetime) -> str:
    return _parse_dt(value).astimezone(timezone.utc).isoformat()


def _session_date(ts: str) -> str:
    return _parse_dt(ts).astimezone(IST).date().isoformat()


def _bar_hits(bar: dict[str, Any], price: float) -> bool:
    return float(bar["low"]) <= price <= float(bar["high"])


def _exit_hits(plan: dict[str, Any], bar: dict[str, Any]) -> tuple[bool, bool]:
    if plan["direction"] == "LONG":
        tp = float(bar["high"]) >= float(plan["take_profit"])
        sl = float(bar["low"]) <= float(plan["stop_loss"])
    else:
        tp = float(bar["low"]) <= float(plan["take_profit"])
        sl = float(bar["high"]) >= float(plan["stop_loss"])
    return tp, sl


def _risk(plan: dict[str, Any]) -> float:
    if plan["direction"] == "LONG":
        return float(plan["entry"]) - float(plan["stop_loss"])
    return float(plan["stop_loss"]) - float(plan["entry"])


def _reward(plan: dict[str, Any]) -> float:
    if plan["direction"] == "LONG":
        return float(plan["take_profit"]) - float(plan["entry"])
    return float(plan["entry"]) - float(plan["take_profit"])


def _excursions(plan: dict[str, Any], bars: list[dict[str, Any]]) -> tuple[float, float]:
    """Return positive MAE/MFE percentages for bars known to occur after entry."""
    if not bars:
        return 0.0, 0.0
    entry = float(plan["entry"])
    if plan["direction"] == "LONG":
        adverse = max(0.0, (entry - min(float(b["low"]) for b in bars)) / entry * 100)
        favorable = max(0.0, (max(float(b["high"]) for b in bars) - entry) / entry * 100)
    else:
        adverse = max(0.0, (max(float(b["high"]) for b in bars) - entry) / entry * 100)
        favorable = max(0.0, (entry - min(float(b["low"]) for b in bars)) / entry * 100)
    return adverse, favorable


def classify_instrument_regime(
    series_id: str,
    *,
    as_of: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Classify only from audited daily bars completed by `as_of`.

    This is an instrument-regime research heuristic, not an exchange fact and not the
    repo's live Nifty regime classifier.
    """
    if get_series(series_id, db_path=db_path) is None:
        raise ValueError(f"Unknown market series: {series_id}")
    bars = query_bars(series_id, "1d", as_of=_utc_iso(as_of), limit=260, db_path=db_path)
    if len(bars) < 50:
        return {
            "regime": "UNKNOWN",
            "basis": REGIME_METHOD_VERSION,
            "bars": len(bars),
            "reason": "At least 50 completed daily bars are required",
        }

    closes = [float(b["close"]) for b in bars]
    close = closes[-1]
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50

    def ann_vol(values: list[float]) -> float:
        if len(values) < 21:
            return 0.0
        rets = [(values[i] / values[i - 1]) - 1 for i in range(len(values) - 20, len(values))]
        return pstdev(rets) * math.sqrt(252) * 100 if len(rets) > 1 else 0.0

    current_vol = ann_vol(closes)
    baselines: list[float] = []
    start = max(50, len(closes) - 140)
    for end in range(start, len(closes) - 20, 5):
        sample = closes[: end + 1]
        value = ann_vol(sample)
        if value > 0:
            baselines.append(value)
    baseline = median(baselines) if baselines else current_vol

    if baseline > 0 and current_vol > baseline * 1.5:
        regime = "HIGH_VOL"
        reason = f"20-session realized vol {current_vol:.2f}% > 1.5x baseline {baseline:.2f}%"
    elif close > sma20 > sma50:
        regime = "TREND_UP"
        reason = "close > SMA20 > SMA50"
    elif close < sma20 < sma50:
        regime = "TREND_DOWN"
        reason = "close < SMA20 < SMA50"
    else:
        regime = "RANGE"
        reason = "close/SMA20/SMA50 are not directionally aligned"

    return {
        "regime": regime,
        "basis": REGIME_METHOD_VERSION,
        "bars": len(bars),
        "close": round(close, 4),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "annualized_vol_pct": round(current_vol, 4),
        "vol_baseline_pct": round(baseline, 4),
        "reason": reason,
        "as_of": _utc_iso(as_of),
    }


def _limit_sessions(bars: list[dict[str, Any]], max_sessions: int) -> list[dict[str, Any]]:
    if max_sessions <= 0:
        return []
    allowed: list[str] = []
    output: list[dict[str, Any]] = []
    for bar in bars:
        day = _session_date(bar["ts_open"])
        if day not in allowed:
            if len(allowed) >= max_sessions:
                break
            allowed.append(day)
        output.append(bar)
    return output


def evaluate_plan_replay_outcome(
    plan_id: str,
    *,
    series_id: str | None = None,
    interval: str = "5m",
    max_sessions: int = 10,
    as_of: str | None = None,
    persist: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Resolve one hypothetical plan without guessing intrabar order.

    Entry rule: first *future* bar (bar open >= evaluation timestamp) whose range
    touches the plan entry. If that same entry bar also touches TP or SL, the result is
    AMBIGUOUS because threshold ordering inside the bar is unknowable. After entry,
    any bar that touches both TP and SL is also AMBIGUOUS.
    """
    plan = get_plan(plan_id, db_path=db_path)
    if plan is None:
        raise ValueError(f"Unknown plan_id: {plan_id}")

    if series_id:
        series = get_series(series_id, db_path=db_path)
        if series is None:
            raise ValueError(f"Unknown market series: {series_id}")
        if series["exchange"] != plan["exchange"] or series["symbol"] != plan["ticker"].upper():
            raise ValueError("Plan identity does not match requested market series")
    else:
        series = find_series(plan["exchange"], plan["ticker"].upper(), db_path=db_path)
        if series is None:
            raise ValueError(
                f"No audited market series for {plan['exchange']}:{plan['ticker']}; sync Phase 3 data first"
            )
    series_id = series["series_id"]

    evaluated = _parse_dt(plan["evaluated_at_ist"])
    evaluated_utc = evaluated.astimezone(timezone.utc)
    replay_as_of = _parse_dt(as_of).astimezone(timezone.utc) if as_of else _now()

    if plan["mode"] == "DAY":
        local_day = evaluated.astimezone(IST).date()
        hard_exit = datetime.combine(local_day, time(15, 15), tzinfo=IST).astimezone(timezone.utc)
        replay_as_of = min(replay_as_of, hard_exit)

    bars = query_bars(
        series_id,
        interval,
        start=evaluated_utc.isoformat(),
        as_of=replay_as_of.isoformat(),
        limit=500000,
        db_path=db_path,
    )
    # A candle already in progress when the plan was evaluated contains pre-plan range
    # information, so it is not allowed to trigger entry.
    bars = [b for b in bars if _parse_dt(b["ts_open"]) >= evaluated_utc]
    if plan["mode"] == "DAY":
        eval_day = evaluated.astimezone(IST).date().isoformat()
        bars = [b for b in bars if _session_date(b["ts_open"]) == eval_day]
    else:
        bars = _limit_sessions(bars, max_sessions)

    computed_at = _now().isoformat()
    regime = classify_instrument_regime(series_id, as_of=evaluated_utc.isoformat(), db_path=db_path)
    base = {
        "plan_id": plan_id,
        "series_id": series_id,
        "interval": interval,
        "observation_kind": "HYPOTHETICAL_REPLAY",
        "evaluated_at": evaluated_utc.isoformat(),
        "observation_end": bars[-1]["ts_close"] if bars else replay_as_of.isoformat(),
        "entry_bar_open": None,
        "entry_fill_price": None,
        "exit_bar_open": None,
        "exit_timestamp": None,
        "exit_price": None,
        "mae_pct": None,
        "mfe_pct": None,
        "r_multiple": None,
        "time_to_event_minutes": None,
        "bars_observed": 0,
        "sessions_observed": len({_session_date(b["ts_open"]) for b in bars}),
        "ambiguity_reason": None,
        "regime": regime["regime"],
        "regime_basis": regime["basis"],
        "method_version": OUTCOME_METHOD_VERSION,
        "computed_at": computed_at,
        "metadata": {
            "entry_rule": "first bar with ts_open >= evaluation and low <= entry <= high",
            "intrabar_rule": "never guess threshold ordering within one candle",
            "mae_mfe_rule": "entry bar excluded; exit bar does not contribute unknown post-exit extremes",
            "time_rule": "event time uses bar-open approximation because intrabar hit time is unknown",
            "max_sessions": max_sessions if plan["mode"] != "DAY" else 1,
            "as_of": replay_as_of.isoformat(),
            "source_price_mode": series.get("price_mode"),
            "source_key": series.get("source_key"),
        },
    }

    if not bars:
        result = {**base, "outcome": "INSUFFICIENT_DATA"}
        if persist:
            upsert_replay_outcome(result, db_path=db_path)
        return result

    entry_index = next((i for i, bar in enumerate(bars) if _bar_hits(bar, float(plan["entry"]))), None)
    if entry_index is None:
        result = {
            **base,
            "outcome": "NOT_ENTERED",
            "bars_observed": len(bars),
        }
        if persist:
            upsert_replay_outcome(result, db_path=db_path)
        return result

    entry_bar = bars[entry_index]
    base["entry_bar_open"] = entry_bar["ts_open"]
    base["entry_fill_price"] = float(plan["entry"])
    future = bars[entry_index + 1 :]
    base["bars_observed"] = 1 + len(future)
    base["sessions_observed"] = len({_session_date(b["ts_open"]) for b in bars[entry_index:]})

    entry_tp, entry_sl = _exit_hits(plan, entry_bar)
    if entry_tp or entry_sl:
        reason = "ENTRY_BAR_BOTH_TP_SL" if entry_tp and entry_sl else "ENTRY_BAR_EXIT_THRESHOLD_TOUCH"
        result = {
            **base,
            "outcome": "AMBIGUOUS",
            "ambiguity_reason": reason,
            "exit_bar_open": entry_bar["ts_open"],
            "exit_timestamp": entry_bar["ts_open"],
            "time_to_event_minutes": 0.0,
        }
        if persist:
            upsert_replay_outcome(result, db_path=db_path)
        return result

    pre_exit: list[dict[str, Any]] = []
    exit_kind = None
    exit_bar = None
    ambiguity = None
    for bar in future:
        hit_tp, hit_sl = _exit_hits(plan, bar)
        if hit_tp and hit_sl:
            exit_kind = "AMBIGUOUS"
            exit_bar = bar
            ambiguity = "TP_AND_SL_SAME_BAR_ORDER_UNKNOWN"
            break
        if hit_tp:
            exit_kind = "TP_FIRST"
            exit_bar = bar
            break
        if hit_sl:
            exit_kind = "SL_FIRST"
            exit_bar = bar
            break
        pre_exit.append(bar)

    risk = _risk(plan)
    reward = _reward(plan)
    mae, mfe = _excursions(plan, pre_exit)

    if exit_kind == "AMBIGUOUS":
        result = {
            **base,
            "outcome": "AMBIGUOUS",
            "ambiguity_reason": ambiguity,
            "exit_bar_open": exit_bar["ts_open"],
            "exit_timestamp": exit_bar["ts_open"],
            "mae_pct": round(mae, 6),
            "mfe_pct": round(mfe, 6),
            "time_to_event_minutes": round(
                (_parse_dt(exit_bar["ts_open"]) - _parse_dt(entry_bar["ts_open"])).total_seconds() / 60,
                3,
            ),
        }
    elif exit_kind == "TP_FIRST":
        target_excursion = reward / float(plan["entry"]) * 100
        result = {
            **base,
            "outcome": "TP_FIRST",
            "exit_bar_open": exit_bar["ts_open"],
            "exit_timestamp": exit_bar["ts_open"],
            "exit_price": float(plan["take_profit"]),
            "mae_pct": round(mae, 6),
            "mfe_pct": round(max(mfe, target_excursion), 6),
            "r_multiple": round(reward / risk, 6) if risk > 0 else None,
            "time_to_event_minutes": round(
                (_parse_dt(exit_bar["ts_open"]) - _parse_dt(entry_bar["ts_open"])).total_seconds() / 60,
                3,
            ),
        }
    elif exit_kind == "SL_FIRST":
        stop_excursion = risk / float(plan["entry"]) * 100
        result = {
            **base,
            "outcome": "SL_FIRST",
            "exit_bar_open": exit_bar["ts_open"],
            "exit_timestamp": exit_bar["ts_open"],
            "exit_price": float(plan["stop_loss"]),
            "mae_pct": round(max(mae, stop_excursion), 6),
            "mfe_pct": round(mfe, 6),
            "r_multiple": -1.0,
            "time_to_event_minutes": round(
                (_parse_dt(exit_bar["ts_open"]) - _parse_dt(entry_bar["ts_open"])).total_seconds() / 60,
                3,
            ),
        }
    else:
        mae, mfe = _excursions(plan, future)
        last = future[-1] if future else entry_bar
        last_price = float(last["close"])
        if plan["direction"] == "LONG":
            pnl = last_price - float(plan["entry"])
        else:
            pnl = float(plan["entry"]) - last_price
        result = {
            **base,
            "outcome": "NEITHER",
            "exit_price": last_price,
            "exit_timestamp": last["ts_close"],
            "mae_pct": round(mae, 6),
            "mfe_pct": round(mfe, 6),
            "r_multiple": round(pnl / risk, 6) if risk > 0 else None,
        }

    if persist:
        upsert_replay_outcome(result, db_path=db_path)
    return result


def backfill_replay_outcomes(
    *,
    exchange: str | None = None,
    ticker: str | None = None,
    interval: str = "5m",
    max_sessions: int = 10,
    as_of: str | None = None,
    limit: int = 10000,
    db_path: str | None = None,
) -> dict[str, Any]:
    plans = list_plans(exchange=exchange, ticker=ticker, limit=limit, db_path=db_path)
    outcomes: dict[str, int] = defaultdict(int)
    errors: list[dict[str, str]] = []
    processed = 0
    for plan in plans:
        try:
            result = evaluate_plan_replay_outcome(
                plan["plan_id"], interval=interval, max_sessions=max_sessions,
                as_of=as_of, persist=True, db_path=db_path,
            )
            outcomes[result["outcome"]] += 1
            processed += 1
        except Exception as exc:
            errors.append({"plan_id": plan["plan_id"], "error": f"{type(exc).__name__}: {exc}"})
    return {
        "plans_selected": len(plans),
        "processed": processed,
        "outcomes": dict(sorted(outcomes.items())),
        "errors": errors[:100],
        "error_count": len(errors),
        "observation_kind": "HYPOTHETICAL_REPLAY",
        "method_version": OUTCOME_METHOD_VERSION,
        "real_outcomes_overwritten": False,
    }


def _rr_band(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value < 1:
        return "LT_1"
    if value < 2:
        return "1_TO_2"
    if value < 3:
        return "2_TO_3"
    return "GE_3"


def _time_bucket(value: str) -> str:
    local = _parse_dt(value).astimezone(IST).time()
    if local < time(9, 15):
        return "PRE_MARKET"
    if local < time(10, 0):
        return "OPEN_0915_1000"
    if local < time(12, 0):
        return "MORNING_1000_1200"
    if local < time(14, 0):
        return "MIDDAY_1200_1400"
    if local < time(15, 10):
        return "LATE_1400_1510"
    if local < time(15, 15):
        return "EXIT_WINDOW_1510_1515"
    return "POST_HARD_EXIT"


def _cohort_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["outcome"]] += 1
    entered = [r for r in rows if r["outcome"] not in {"NOT_ENTERED", "INSUFFICIENT_DATA"}]
    resolved = [r for r in entered if r["outcome"] in {"TP_FIRST", "SL_FIRST"}]
    numeric_r = [float(r["r_multiple"]) for r in rows if r.get("r_multiple") is not None]
    maes = [float(r["mae_pct"]) for r in rows if r.get("mae_pct") is not None]
    mfes = [float(r["mfe_pct"]) for r in rows if r.get("mfe_pct") is not None]
    return {
        "n": len(rows),
        "entered_n": len(entered),
        "resolved_tp_sl_n": len(resolved),
        "outcomes": dict(sorted(counts.items())),
        "tp_rate_resolved_pct": round(sum(r["outcome"] == "TP_FIRST" for r in resolved) / len(resolved) * 100, 3) if resolved else None,
        "ambiguity_rate_entered_pct": round(sum(r["outcome"] == "AMBIGUOUS" for r in entered) / len(entered) * 100, 3) if entered else None,
        "median_r_multiple": round(median(numeric_r), 6) if numeric_r else None,
        "median_mae_pct": round(median(maes), 6) if maes else None,
        "median_mfe_pct": round(median(mfes), 6) if mfes else None,
    }


def focus_cohort_report(
    *,
    series_id: str,
    interval: str,
    limit: int = 100000,
    db_path: str | None = None,
) -> dict[str, Any]:
    rows = list_replay_outcomes(series_id=series_id, interval=interval, limit=limit, db_path=db_path)
    dimensions = {
        "mode": lambda r: r.get("mode") or "UNKNOWN",
        "crash_guard": lambda r: r.get("crash_guard") or "UNKNOWN",
        "regime": lambda r: r.get("regime") or "UNKNOWN",
        "gate_action": lambda r: r.get("gate_action") or "UNKNOWN",
        "reward_risk_band": lambda r: _rr_band(r.get("reward_risk")),
        "evaluation_time": lambda r: _time_bucket(r.get("evaluated_at_ist") or r["evaluated_at"]),
    }
    grouped: dict[str, dict[str, Any]] = {}
    for dimension, key_fn in dimensions.items():
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            buckets[str(key_fn(row))].append(row)
        grouped[dimension] = {key: _cohort_summary(value) for key, value in sorted(buckets.items())}
    return {
        "profile": "FOCUS_INSTRUMENT_LAB",
        "series_id": series_id,
        "interval": interval,
        "overall": _cohort_summary(rows),
        "cohorts": grouped,
        "promotion_rule": "Research only. No cohort changes hard policy without separate walk-forward/challenger validation.",
        "observation_kind": "HYPOTHETICAL_REPLAY",
    }


def crash_guard_calibration(
    *,
    series_id: str,
    interval: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    rows = list_replay_outcomes(series_id=series_id, interval=interval, limit=100000, db_path=db_path)
    long_rows = [r for r in rows if r.get("direction") == "LONG"]
    states: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in long_rows:
        states[row.get("crash_guard") or "UNKNOWN"].append(row)
    severe = states.get("SEVERE", [])
    severe_resolved = [r for r in severe if r["outcome"] in {"TP_FIRST", "SL_FIRST"}]
    return {
        "series_id": series_id,
        "interval": interval,
        "long_plan_states": {state: _cohort_summary(items) for state, items in sorted(states.items())},
        "severe_counterfactual": {
            "resolved_n": len(severe_resolved),
            "would_have_hit_tp_pct": round(sum(r["outcome"] == "TP_FIRST" for r in severe_resolved) / len(severe_resolved) * 100, 3) if severe_resolved else None,
            "would_have_hit_sl_pct": round(sum(r["outcome"] == "SL_FIRST" for r in severe_resolved) / len(severe_resolved) * 100, 3) if severe_resolved else None,
        },
        "interpretation_boundary": "This audits the existing Crash Guard label counterfactually; it does not auto-relax or tighten the hard gate.",
    }


def study_level_reliability(
    *,
    series_id: str,
    interval: str,
    level_type: str,
    level_price: float,
    tolerance_pct: float = 0.20,
    reaction_pct: float = 0.50,
    break_pct: float = 0.30,
    horizon_bars: int = 6,
    as_of: str | None = None,
    persist: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    level_type = level_type.upper()
    if level_type not in {"SUPPORT", "RESISTANCE"}:
        raise ValueError("level_type must be SUPPORT or RESISTANCE")
    if min(level_price, tolerance_pct, reaction_pct, break_pct) <= 0 or horizon_bars <= 0:
        raise ValueError("level/tolerance/reaction/break/horizon must be positive")
    if get_series(series_id, db_path=db_path) is None:
        raise ValueError(f"Unknown market series: {series_id}")

    bars = query_bars(series_id, interval, as_of=_utc_iso(as_of) if as_of else None, limit=500000, db_path=db_path)
    tol = level_price * tolerance_pct / 100
    reaction = level_price * reaction_pct / 100
    break_distance = level_price * break_pct / 100
    episodes: list[dict[str, Any]] = []

    i = 0
    while i < len(bars):
        bar = bars[i]
        touched = float(bar["low"]) <= level_price + tol and float(bar["high"]) >= level_price - tol
        if not touched:
            i += 1
            continue
        future = bars[i + 1 : i + 1 + horizon_bars]
        outcome = "UNRESOLVED"
        resolved_at = None
        for candidate in future:
            if level_type == "SUPPORT":
                reacted = float(candidate["high"]) >= level_price + reaction
                broke = float(candidate["low"]) <= level_price - break_distance
            else:
                reacted = float(candidate["low"]) <= level_price - reaction
                broke = float(candidate["high"]) >= level_price + break_distance
            if reacted and broke:
                outcome = "AMBIGUOUS"
                resolved_at = candidate["ts_open"]
                break
            if reacted:
                outcome = "REACTION_FIRST"
                resolved_at = candidate["ts_open"]
                break
            if broke:
                outcome = "BREAK_FIRST"
                resolved_at = candidate["ts_open"]
                break
        regime = classify_instrument_regime(series_id, as_of=bar["ts_open"], db_path=db_path)
        episodes.append({
            "touch_bar_open": bar["ts_open"],
            "outcome": outcome,
            "resolved_at": resolved_at,
            "regime": regime["regime"],
        })
        # Non-overlapping windows prevent one prolonged interaction from becoming many samples.
        i += 1 + horizon_bars

    counts: dict[str, int] = defaultdict(int)
    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        counts[episode["outcome"]] += 1
        by_regime[episode["regime"]].append(episode)
    resolved = [e for e in episodes if e["outcome"] in {"REACTION_FIRST", "BREAK_FIRST"}]
    result = {
        "series_id": series_id,
        "interval": interval,
        "level_type": level_type,
        "level_price": level_price,
        "tolerance_pct": tolerance_pct,
        "reaction_pct": reaction_pct,
        "break_pct": break_pct,
        "horizon_bars": horizon_bars,
        "touch_episodes": len(episodes),
        "outcomes": dict(sorted(counts.items())),
        "reaction_first_rate_resolved_pct": round(sum(e["outcome"] == "REACTION_FIRST" for e in resolved) / len(resolved) * 100, 3) if resolved else None,
        "by_regime": {key: _cohort_summary([{"outcome": "TP_FIRST" if e["outcome"] == "REACTION_FIRST" else "SL_FIRST" if e["outcome"] == "BREAK_FIRST" else e["outcome"], "r_multiple": None, "mae_pct": None, "mfe_pct": None} for e in value]) for key, value in sorted(by_regime.items())},
        "episodes": episodes,
        "method_version": LEVEL_METHOD_VERSION,
        "regime_basis": REGIME_METHOD_VERSION,
        "sampling_rule": "Non-overlapping touch windows; touch bar itself is not used to resolve reaction-vs-break order.",
        "status": "RESEARCH_HEURISTIC_NOT_POLICY",
    }
    if persist:
        study_id = persist_level_study(
            series_id=series_id, interval=interval, level_type=level_type,
            level_price=level_price, tolerance_pct=tolerance_pct, reaction_pct=reaction_pct,
            break_pct=break_pct, horizon_bars=horizon_bars, as_of=_utc_iso(as_of) if as_of else None,
            method_version=LEVEL_METHOD_VERSION, result=result, computed_at=_now().isoformat(), db_path=db_path,
        )
        result["study_id"] = study_id
    return result


def event_category_relevance(
    *,
    series_id: str,
    horizon_sessions: int = 5,
    db_path: str | None = None,
) -> dict[str, Any]:
    rows = event_category_effect_rows(series_id, horizon_sessions, db_path=db_path)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row.get("category") or "GENERAL"].append(row)

    categories: dict[str, Any] = {}
    for category, items in sorted(groups.items()):
        comparable = [r for r in items if r.get("return_pct") is not None]
        returns = [float(r["return_pct"]) for r in comparable]
        maes = [float(r["mae_pct"]) for r in comparable if r.get("mae_pct") is not None]
        mfes = [float(r["mfe_pct"]) for r in comparable if r.get("mfe_pct") is not None]
        categories[category] = {
            "events_total": len(items),
            "events_comparable": len(comparable),
            "positive_return_rate_pct": round(sum(v > 0 for v in returns) / len(returns) * 100, 3) if returns else None,
            "median_return_pct": round(median(returns), 6) if returns else None,
            "median_abs_return_pct": round(median([abs(v) for v in returns]), 6) if returns else None,
            "median_mae_pct": round(median(maes), 6) if maes else None,
            "median_mfe_pct": round(median(mfes), 6) if mfes else None,
        }

    return {
        "series_id": series_id,
        "horizon_sessions": horizon_sessions,
        "categories": categories,
        "events_total": len(rows),
        "causation_warning": "Observed post-announcement price movement is association, not proof the filing caused the move.",
        "policy_status": "SOFT_EVIDENCE_ONLY",
    }
