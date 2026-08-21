"""Prospective collector for BSE Hypothesis 001.

The hypothesis was frozen after the 2026-08-21 evidence baseline. This module refuses
to count any session on or before that date as validation evidence. It evaluates a
fixed blind gap-direction benchmark against a first-45-minute confirmation challenger
using audited 5-minute bars, verified exchange calendar state, strict threshold
ordering, the protected 15:15 INTRADAY exit, and resident transaction costs.

Nothing here authorizes a trade or promotes a runtime rule.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import Counter
from datetime import date, datetime, time, timezone
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from backend.db import DB_PATH
from backend.tradebrain.equity_costs import calculate_equity_trade_costs
from backend.tradebrain.exchange_calendar import session_for_date
from backend.tradebrain.market_data_store import get_series, query_bars

IST = ZoneInfo("Asia/Kolkata")
HYPOTHESIS_ID = "BSE_PROSPECTIVE_HYPOTHESIS_001"
METHOD_VERSION = "BSE_GAP_FIRST_HOUR_PROSPECTIVE_V1"
FREEZE_DATE = date(2026, 8, 21)
MIN_ABS_GAP_PCT = 1.0
DECISION_TIME = time(10, 0)
HARD_EXIT_TIME = time(15, 15)
FIXED_NOTIONAL_RUPEES = 100_000.0
MIN_ELIGIBLE_FOR_REVIEW = 30
MIN_CHALLENGER_ENTRIES_FOR_REVIEW = 20
MAX_AMBIGUITY_RATE_PCT = 10.0


def _db_path(db_path: str | None) -> str:
    return db_path or DB_PATH


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = _db_path(db_path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_prospective_gap_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tb_prospective_gap_observations (
                hypothesis_id TEXT NOT NULL,
                series_id TEXT NOT NULL,
                session_date TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                gap_pct REAL NOT NULL,
                gap_direction TEXT NOT NULL,
                previous_close REAL NOT NULL,
                session_open REAL NOT NULL,
                confirmation_passed INTEGER NOT NULL,
                confirmation_reason TEXT NOT NULL,
                benchmark_json TEXT NOT NULL,
                challenger_json TEXT NOT NULL,
                method_version TEXT NOT NULL,
                PRIMARY KEY(hypothesis_id, series_id, session_date),
                FOREIGN KEY(series_id) REFERENCES tb_market_series(series_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tb_prospective_gap_date ON tb_prospective_gap_observations(hypothesis_id, session_date)"
        )


def _local_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def _bar_day(bar: dict[str, Any]) -> date:
    return _local_dt(bar["ts_open"]).date()


def _same_verified_era(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    left = previous.get("era_id")
    right = current.get("era_id")
    return bool(left and right and left == right)


def _expected_first_window_opens() -> list[time]:
    return [time(9, 15 + 5 * i) if 15 + 5 * i < 60 else time(10, (15 + 5 * i) - 60) for i in range(9)]


def _first_window(session_bars: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    xs = []
    for bar in session_bars:
        opened = _local_dt(bar["ts_open"])
        closed = _local_dt(bar["ts_close"])
        if opened.time() >= time(9, 15) and closed.time() <= DECISION_TIME:
            xs.append(bar)
    xs.sort(key=lambda b: b["ts_open"])
    expected = [time(9, 15), time(9, 20), time(9, 25), time(9, 30), time(9, 35), time(9, 40), time(9, 45), time(9, 50), time(9, 55)]
    opens = [_local_dt(bar["ts_open"]).time().replace(tzinfo=None) for bar in xs]
    if opens != expected:
        return xs, "INCOMPLETE_0915_TO_1000_WINDOW"
    if _local_dt(xs[-1]["ts_close"]).time().replace(tzinfo=None) != DECISION_TIME:
        return xs, "FIRST_WINDOW_DOES_NOT_CLOSE_AT_1000"
    return xs, None


def _entry_and_following_bars(session_bars: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    eligible = []
    for bar in sorted(session_bars, key=lambda b: b["ts_open"]):
        opened = _local_dt(bar["ts_open"]).time().replace(tzinfo=None)
        closed = _local_dt(bar["ts_close"]).time().replace(tzinfo=None)
        if opened >= DECISION_TIME and closed <= HARD_EXIT_TIME:
            eligible.append(bar)
    if not eligible:
        return None, [], "NO_BAR_AVAILABLE_AT_OR_AFTER_1000_BEFORE_HARD_EXIT"
    first_open = _local_dt(eligible[0]["ts_open"]).time().replace(tzinfo=None)
    if first_open != DECISION_TIME:
        return None, eligible, "ENTRY_BAR_AT_1000_MISSING"
    last_close = _local_dt(eligible[-1]["ts_close"]).time().replace(tzinfo=None)
    if last_close < HARD_EXIT_TIME:
        return eligible[0], eligible, "DATA_ENDS_BEFORE_1515_HARD_EXIT"
    return eligible[0], eligible, None


def _resolve_arm(
    *,
    direction: str,
    entry_price: float,
    stop_price: float,
    bars: list[dict[str, Any]],
    notional_rupees: float,
    exchange: str,
) -> dict[str, Any]:
    direction = direction.upper()
    if direction == "LONG":
        risk = entry_price - stop_price
        if risk <= 0:
            return {"entered": False, "outcome": "INVALID_GEOMETRY", "reason": "LONG stop must be below entry"}
        target = entry_price + risk
    else:
        risk = stop_price - entry_price
        if risk <= 0:
            return {"entered": False, "outcome": "INVALID_GEOMETRY", "reason": "SHORT stop must be above entry"}
        target = entry_price - risk
        if target <= 0:
            return {"entered": False, "outcome": "INVALID_GEOMETRY", "reason": "SHORT 1R target is nonpositive"}

    quantity = int(math.floor(float(notional_rupees) / float(entry_price)))
    if quantity <= 0:
        return {"entered": False, "outcome": "INSUFFICIENT_NOTIONAL", "reason": "Fixed notional buys fewer than one share"}

    observed: list[dict[str, Any]] = []
    outcome = "NEITHER"
    exit_price = None
    exit_ts = None
    ambiguity_reason = None

    for bar in bars:
        observed.append(bar)
        high = float(bar["high"])
        low = float(bar["low"])
        if direction == "LONG":
            tp_hit = high >= target
            sl_hit = low <= stop_price
        else:
            tp_hit = low <= target
            sl_hit = high >= stop_price
        if tp_hit and sl_hit:
            outcome = "AMBIGUOUS"
            ambiguity_reason = "TP_AND_SL_TOUCHED_WITHIN_SAME_5M_BAR"
            exit_ts = bar["ts_close"]
            break
        if tp_hit:
            outcome = "TP_FIRST"
            exit_price = target
            exit_ts = bar["ts_close"]
            break
        if sl_hit:
            outcome = "SL_FIRST"
            exit_price = stop_price
            exit_ts = bar["ts_close"]
            break

    if outcome == "NEITHER":
        final_bar = observed[-1] if observed else None
        if final_bar is None:
            return {"entered": False, "outcome": "INSUFFICIENT_DATA", "reason": "No bars after entry"}
        exit_price = float(final_bar["close"])
        exit_ts = final_bar["ts_close"]

    highs = [float(bar["high"]) for bar in observed]
    lows = [float(bar["low"]) for bar in observed]
    if direction == "LONG":
        mfe_r = max(0.0, (max(highs) - entry_price) / risk) if highs else 0.0
        mae_r = max(0.0, (entry_price - min(lows)) / risk) if lows else 0.0
    else:
        mfe_r = max(0.0, (entry_price - min(lows)) / risk) if lows else 0.0
        mae_r = max(0.0, (max(highs) - entry_price) / risk) if highs else 0.0

    result: dict[str, Any] = {
        "entered": True,
        "direction": direction,
        "entry_price": round(entry_price, 6),
        "stop_price": round(stop_price, 6),
        "target_price": round(target, 6),
        "risk_per_share": round(risk, 6),
        "quantity": quantity,
        "fixed_notional_rupees": float(notional_rupees),
        "outcome": outcome,
        "exit_price": round(exit_price, 6) if exit_price is not None else None,
        "exit_ts": exit_ts,
        "ambiguity_reason": ambiguity_reason,
        "bars_observed": len(observed),
        "mfe_r": round(mfe_r, 6),
        "mae_r": round(mae_r, 6),
    }
    if exit_price is not None:
        gross_r = ((exit_price - entry_price) / risk) if direction == "LONG" else ((entry_price - exit_price) / risk)
        result["gross_r"] = round(gross_r, 6)
        result["costs"] = calculate_equity_trade_costs(
            mode="INTRADAY",
            exchange=exchange,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            slippage_bps=0.0,
        )
        result["net_pnl"] = result["costs"]["net_pnl"]
    else:
        result["gross_r"] = None
        result["costs"] = None
        result["net_pnl"] = None
    return result


def _no_trade(reason: str) -> dict[str, Any]:
    return {
        "entered": False,
        "outcome": "NO_TRADE",
        "reason": reason,
        "net_pnl": 0.0,
        "gross_r": 0.0,
    }


def _persist_observation(item: dict[str, Any], *, db_path: str | None = None) -> None:
    ensure_prospective_gap_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_prospective_gap_observations(
                hypothesis_id, series_id, session_date, observed_at,
                gap_pct, gap_direction, previous_close, session_open,
                confirmation_passed, confirmation_reason,
                benchmark_json, challenger_json, method_version
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(hypothesis_id, series_id, session_date) DO UPDATE SET
                observed_at=excluded.observed_at,
                gap_pct=excluded.gap_pct,
                gap_direction=excluded.gap_direction,
                previous_close=excluded.previous_close,
                session_open=excluded.session_open,
                confirmation_passed=excluded.confirmation_passed,
                confirmation_reason=excluded.confirmation_reason,
                benchmark_json=excluded.benchmark_json,
                challenger_json=excluded.challenger_json,
                method_version=excluded.method_version
            """,
            (
                HYPOTHESIS_ID,
                item["series_id"],
                item["session_date"],
                datetime.now(timezone.utc).isoformat(),
                item["gap_pct"],
                item["gap_direction"],
                item["previous_close"],
                item["session_open"],
                1 if item["confirmation_passed"] else 0,
                item["confirmation_reason"],
                json.dumps(item["benchmark"], sort_keys=True),
                json.dumps(item["challenger"], sort_keys=True),
                METHOD_VERSION,
            ),
        )


def collect_prospective_gap_observations(
    series_id: str,
    *,
    as_of: str | datetime | None = None,
    notional_rupees: float = FIXED_NOTIONAL_RUPEES,
    require_verified_calendar: bool = True,
    persist: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    if str(series.get("exchange") or "").upper() != "NSE" or str(series.get("symbol") or "").upper() != "BSE":
        raise ValueError("Hypothesis 001 is frozen for exact instrument NSE:BSE only")
    if notional_rupees <= 0:
        raise ValueError("notional_rupees must be positive")

    cutoff = datetime.now(timezone.utc) if as_of is None else (datetime.fromisoformat(as_of) if isinstance(as_of, str) else as_of)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    cutoff_iso = cutoff.astimezone(timezone.utc).isoformat()

    daily = query_bars(series_id, "1d", as_of=cutoff_iso, limit=500000, db_path=db_path)
    intraday = query_bars(series_id, "5m", as_of=cutoff_iso, limit=500000, db_path=db_path)
    intraday_by_day: dict[date, list[dict[str, Any]]] = {}
    for bar in intraday:
        intraday_by_day.setdefault(_bar_day(bar), []).append(bar)

    observations: list[dict[str, Any]] = []
    skipped = Counter()
    for idx in range(1, len(daily)):
        previous = daily[idx - 1]
        current = daily[idx]
        session_day = _bar_day(current)
        if session_day <= FREEZE_DATE:
            continue
        if not _same_verified_era(previous, current):
            skipped["PRICE_ERA_NOT_COMPARABLE"] += 1
            continue
        if require_verified_calendar:
            calendar = session_for_date(session_day, exchange="NSE", segment="CM", db_path=db_path)
            if not calendar.get("calendar_verified") or not calendar.get("is_trading_session") or not calendar.get("timing_verified"):
                skipped["CALENDAR_NOT_VERIFIED_REGULAR_OPEN"] += 1
                continue
            if calendar.get("session_type") != "REGULAR":
                skipped["NON_REGULAR_SESSION"] += 1
                continue

        previous_close = float(previous["close"])
        session_open = float(current["open"])
        if previous_close <= 0 or session_open <= 0:
            skipped["INVALID_DAILY_PRICE"] += 1
            continue
        gap_pct = (session_open / previous_close - 1.0) * 100.0
        if abs(gap_pct) < MIN_ABS_GAP_PCT:
            continue
        direction = "LONG" if gap_pct > 0 else "SHORT"
        gap_direction = "GAP_UP" if gap_pct > 0 else "GAP_DOWN"

        session_bars = intraday_by_day.get(session_day, [])
        window, error = _first_window(session_bars)
        if error:
            skipped[error] += 1
            continue
        entry_bar, follow_bars, error = _entry_and_following_bars(session_bars)
        if error:
            skipped[error] += 1
            continue
        assert entry_bar is not None

        if direction == "LONG":
            stop = min(float(bar["low"]) for bar in window)
            final_window_close = float(window[-1]["close"])
            previous_close_untouched = min(float(bar["low"]) for bar in window) > previous_close
            confirmation_passed = final_window_close > session_open and previous_close_untouched
            confirmation_reason = (
                "GAP_UP_FIRST_45M_CONFIRMED_AND_PREVIOUS_CLOSE_UNTOUCHED"
                if confirmation_passed
                else "GAP_UP_FIRST_45M_NOT_CONFIRMED_OR_GAP_TOUCHED"
            )
        else:
            stop = max(float(bar["high"]) for bar in window)
            final_window_close = float(window[-1]["close"])
            previous_close_untouched = max(float(bar["high"]) for bar in window) < previous_close
            confirmation_passed = final_window_close < session_open and previous_close_untouched
            confirmation_reason = (
                "GAP_DOWN_FIRST_45M_CONFIRMED_AND_PREVIOUS_CLOSE_UNTOUCHED"
                if confirmation_passed
                else "GAP_DOWN_FIRST_45M_NOT_CONFIRMED_OR_GAP_TOUCHED"
            )

        entry_price = float(entry_bar["open"])
        benchmark = _resolve_arm(
            direction=direction,
            entry_price=entry_price,
            stop_price=stop,
            bars=follow_bars,
            notional_rupees=notional_rupees,
            exchange="NSE",
        )
        challenger = (
            _resolve_arm(
                direction=direction,
                entry_price=entry_price,
                stop_price=stop,
                bars=follow_bars,
                notional_rupees=notional_rupees,
                exchange="NSE",
            )
            if confirmation_passed
            else _no_trade(confirmation_reason)
        )

        item = {
            "hypothesis_id": HYPOTHESIS_ID,
            "method_version": METHOD_VERSION,
            "series_id": series_id,
            "session_date": session_day.isoformat(),
            "gap_pct": round(gap_pct, 6),
            "gap_direction": gap_direction,
            "previous_close": round(previous_close, 6),
            "session_open": round(session_open, 6),
            "decision_time_ist": "10:00",
            "confirmation_passed": confirmation_passed,
            "confirmation_reason": confirmation_reason,
            "benchmark": benchmark,
            "challenger": challenger,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
        observations.append(item)
        if persist:
            _persist_observation(item, db_path=db_path)

    summary = summarize_prospective_gap_observations(observations)
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "method_version": METHOD_VERSION,
        "freeze_date": FREEZE_DATE.isoformat(),
        "validation_rule": "Only session dates strictly after freeze_date count",
        "as_of": cutoff_iso,
        "series_id": series_id,
        "eligible_observations": len(observations),
        "observations": observations,
        "skipped": dict(sorted(skipped.items())),
        "summary": summary,
        "review_thresholds": {
            "min_eligible_sessions": MIN_ELIGIBLE_FOR_REVIEW,
            "min_challenger_entries": MIN_CHALLENGER_ENTRIES_FOR_REVIEW,
            "max_ambiguity_rate_pct": MAX_AMBIGUITY_RATE_PCT,
        },
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def _arm_summary(observations: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    rows = [item[arm] for item in observations]
    entered = [row for row in rows if row.get("entered")]
    outcomes = Counter(str(row.get("outcome")) for row in entered)
    clean = [row for row in entered if row.get("outcome") in {"TP_FIRST", "SL_FIRST", "NEITHER"}]
    net_values = [float(row.get("net_pnl") or 0.0) for row in rows]
    clean_r = [float(row["gross_r"]) for row in clean if row.get("gross_r") is not None]
    mae = [float(row["mae_r"]) for row in clean if row.get("mae_r") is not None]
    ambiguous = outcomes.get("AMBIGUOUS", 0)
    return {
        "eligible_sessions": len(rows),
        "entries": len(entered),
        "outcomes": dict(sorted(outcomes.items())),
        "mean_net_pnl_per_eligible_session": round(mean(net_values), 2) if net_values else None,
        "median_net_pnl_per_eligible_session": round(median(net_values), 2) if net_values else None,
        "median_clean_gross_r": round(median(clean_r), 6) if clean_r else None,
        "median_clean_mae_r": round(median(mae), 6) if mae else None,
        "ambiguity_rate_pct_of_entries": round(ambiguous / len(entered) * 100.0, 3) if entered else None,
    }


def summarize_prospective_gap_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    benchmark = _arm_summary(observations, "benchmark")
    challenger = _arm_summary(observations, "challenger")
    enough_sample = (
        len(observations) >= MIN_ELIGIBLE_FOR_REVIEW
        and challenger["entries"] >= MIN_CHALLENGER_ENTRIES_FOR_REVIEW
        and (challenger["ambiguity_rate_pct_of_entries"] or 0.0) <= MAX_AMBIGUITY_RATE_PCT
    )
    return {
        "benchmark": benchmark,
        "challenger": challenger,
        "review_sample_gate_passed": enough_sample,
        "decision": "READY_FOR_FORMAL_REVIEW" if enough_sample else "NEEDS_MORE_DATA",
        "automatic_promotion": False,
        "human_approval_required": True,
    }


def stored_prospective_gap_observations(series_id: str, *, db_path: str | None = None) -> list[dict[str, Any]]:
    ensure_prospective_gap_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM tb_prospective_gap_observations
               WHERE hypothesis_id=? AND series_id=? ORDER BY session_date ASC""",
            (HYPOTHESIS_ID, series_id),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["confirmation_passed"] = bool(item["confirmation_passed"])
        item["benchmark"] = json.loads(item.pop("benchmark_json"))
        item["challenger"] = json.loads(item.pop("challenger_json"))
        result.append(item)
    return result
