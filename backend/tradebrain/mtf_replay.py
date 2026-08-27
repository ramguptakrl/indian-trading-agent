"""MTF-aware strict replay economics for active BSE SWING plans.

The Phase-4 strict replay engine remains the authority for entry/TP/SL ordering. This
module adds active-product constraints, split-era comparability checks, and versioned
Zerodha MTF economics without guessing funding or interest-day inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from backend.db import DB_PATH
from backend.tradebrain.corporate_action_eras import sync_official_bse_split_price_eras
from backend.tradebrain.focus_lab import evaluate_plan_replay_outcome
from backend.tradebrain.focus_lab_store import get_plan
from backend.tradebrain.market_data_store import get_series
from backend.tradebrain.swing_mtf import calculate_swing_mtf_trade_costs
from backend.tradebrain.trade_modes import to_active_mode

METHOD_VERSION = "BSE_SWING_MTF_STRICT_REPLAY_V1"


@contextmanager
def _connect(db_path: str | None = None):
    path = db_path or DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_mtf_replay_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tb_swing_mtf_replay_economics (
                replay_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                series_id TEXT NOT NULL,
                interval TEXT NOT NULL,
                as_of TEXT,
                strict_outcome TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                funded_amount REAL NOT NULL,
                interest_days INTEGER NOT NULL,
                mtf_eligible_verified INTEGER NOT NULL,
                gross_pnl REAL,
                total_charges REAL,
                mtf_interest REAL,
                net_pnl REAL,
                net_return_on_user_cash_pct REAL,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL,
                method_version TEXT NOT NULL,
                computed_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_tb_mtf_replay_plan
               ON tb_swing_mtf_replay_economics(plan_id, computed_at DESC)"""
        )


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _crosses_price_era(
    *,
    series_id: str,
    interval: str,
    start: str | None,
    end: str | None,
    db_path: str | None,
) -> tuple[bool, list[str]]:
    """Check bar-open era IDs, including the exit/boundary bar itself.

    The strict replay may timestamp a threshold exit at the bar open. Using the generic
    completed-bar `as_of` query here would exclude that very bar. Direct `ts_open`
    bounds ensure a split ex-date bar cannot sneak through as a real stop/target event.
    """
    if not start or not end:
        return False, []
    start_utc = _parse(start).isoformat()
    end_utc = _parse(end).isoformat()
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT era_id
            FROM tb_ohlcv_bars
            WHERE series_id=? AND interval=?
              AND ts_open>=? AND ts_open<=?
              AND era_id IS NOT NULL AND era_id!=''
            ORDER BY era_id
            """,
            (series_id, interval, start_utc, end_utc),
        ).fetchall()
    eras = [str(row["era_id"]) for row in rows]
    return len(eras) > 1, eras


def _persist(result: dict[str, Any], *, db_path: str | None) -> None:
    ensure_mtf_replay_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_swing_mtf_replay_economics(
                replay_id, plan_id, series_id, interval, as_of, strict_outcome,
                quantity, funded_amount, interest_days, mtf_eligible_verified,
                gross_pnl, total_charges, mtf_interest, net_pnl,
                net_return_on_user_cash_pct, status, result_json, method_version, computed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(replay_id) DO UPDATE SET
                strict_outcome=excluded.strict_outcome,
                gross_pnl=excluded.gross_pnl,
                total_charges=excluded.total_charges,
                mtf_interest=excluded.mtf_interest,
                net_pnl=excluded.net_pnl,
                net_return_on_user_cash_pct=excluded.net_return_on_user_cash_pct,
                status=excluded.status,
                result_json=excluded.result_json,
                computed_at=excluded.computed_at
            """,
            (
                result["replay_id"], result["plan_id"], result["series_id"], result["interval"],
                result.get("as_of"), result["strict_outcome"], result["quantity"],
                result["funded_amount"], result["interest_days"], 1,
                result.get("gross_pnl"), result.get("total_charges"), result.get("mtf_interest"),
                result.get("net_pnl"), result.get("net_return_on_user_cash_pct"),
                result["status"], json.dumps(result, sort_keys=True, default=str),
                METHOD_VERSION, result["computed_at"],
            ),
        )


def evaluate_swing_mtf_replay(
    plan_id: str,
    *,
    series_id: str,
    quantity: int,
    funded_amount: float,
    interest_days: int,
    mtf_eligible_verified: bool,
    interval: str = "5m",
    max_sessions: int = 10,
    as_of: str | None = None,
    slippage_bps: float = 0.0,
    transaction_charge_pct_override: float | None = None,
    dp_base_rupees: float | None = None,
    purchase_date_count: int = 1,
    rms_squareoff_orders: int = 0,
    persist: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Evaluate one active SWING plan with explicit MTF funding assumptions.

    `interest_days` is intentionally caller-supplied and must be >=1. The current MTF
    profile does not allow this replay layer to silently guess financing days from bar
    timestamps or exchange trading sessions.
    """
    plan = get_plan(plan_id, db_path=db_path)
    if plan is None:
        raise ValueError(f"Unknown plan_id: {plan_id}")
    if to_active_mode(str(plan.get("mode") or "")) != "SWING":
        raise ValueError("MTF replay is valid only for SWING plans")
    if str(plan.get("direction") or "").upper() != "LONG":
        raise ValueError("Active SWING MTF replay is LONG-only")
    if not mtf_eligible_verified:
        raise ValueError("Current/frozen scenario MTF eligibility must be explicitly verified")
    if quantity <= 0 or funded_amount <= 0:
        raise ValueError("quantity and funded_amount must be positive")
    if interest_days < 1:
        raise ValueError("A positive explicit interest_days scenario is required; replay will not guess it")

    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    if str(series.get("exchange") or "").upper() != "NSE" or str(series.get("symbol") or "").upper() != "BSE":
        raise ValueError("Active SWING MTF replay supports only canonical NSE:BSE")

    era_sync = sync_official_bse_split_price_eras(
        series_id,
        known_by=as_of or datetime.now(timezone.utc),
        db_path=db_path,
    )

    strict = evaluate_plan_replay_outcome(
        plan_id,
        series_id=series_id,
        interval=interval,
        max_sessions=max_sessions,
        as_of=as_of,
        persist=False,
        db_path=db_path,
    )
    strict_outcome = str(strict.get("outcome") or "UNKNOWN")
    computed_at = datetime.now(timezone.utc).isoformat()
    replay_seed = "|".join(
        [
            plan_id, series_id, interval, str(as_of or "LATEST"), str(quantity),
            f"{float(funded_amount):.8f}", str(interest_days), str(max_sessions),
        ]
    )
    replay_id = "mtfreplay:" + hashlib.sha256(replay_seed.encode("utf-8")).hexdigest()

    base = {
        "replay_id": replay_id,
        "plan_id": plan_id,
        "series_id": series_id,
        "interval": interval,
        "as_of": as_of,
        "strict_outcome": strict_outcome,
        "strict_replay": strict,
        "quantity": int(quantity),
        "funded_amount": round(float(funded_amount), 2),
        "interest_days": int(interest_days),
        "interest_days_source": "EXPLICIT_CALLER_SCENARIO_NOT_GUESSED",
        "mtf_eligible_verified": True,
        "swing_funding": "MTF",
        "official_split_price_eras": era_sync,
        "method_version": METHOD_VERSION,
        "computed_at": computed_at,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }

    if strict_outcome in {"NOT_ENTERED", "INSUFFICIENT_DATA", "AMBIGUOUS"}:
        result = {
            **base,
            "status": "NO_MTF_ECONOMICS_UNRESOLVED_STRICT_OUTCOME",
            "economics": None,
            "reason": "MTF costs are not scored when strict replay cannot establish an unambiguous entered price path.",
        }
        if persist:
            _persist(result, db_path=db_path)
        return result

    entry_time = strict.get("entry_bar_open")
    end_time = strict.get("exit_timestamp") or strict.get("observation_end")
    crosses_era, era_ids = _crosses_price_era(
        series_id=series_id,
        interval=interval,
        start=entry_time,
        end=end_time,
        db_path=db_path,
    )
    if crosses_era:
        result = {
            **base,
            "status": "RAW_PRICE_CROSSES_COMPARABILITY_ERA",
            "strict_outcome": "RAW_PRICE_CROSSES_COMPARABILITY_ERA",
            "price_era_ids": era_ids,
            "economics": None,
            "reason": "Raw pre/post-split price scales cannot be used for TP/SL or MTF P&L without basis adjustment.",
        }
        if persist:
            _persist(result, db_path=db_path)
        return result

    entry_price = float(strict.get("entry_fill_price") or plan["entry"])
    exit_price = strict.get("exit_price")
    if exit_price is None or float(exit_price) <= 0:
        result = {
            **base,
            "status": "NO_MTF_ECONOMICS_MISSING_EXIT_PRICE",
            "economics": None,
        }
        if persist:
            _persist(result, db_path=db_path)
        return result

    position_value = entry_price * int(quantity)
    if float(funded_amount) >= position_value:
        raise ValueError("funded_amount must be below replay position value")

    economics = calculate_swing_mtf_trade_costs(
        exchange="NSE",
        entry_price=entry_price,
        exit_price=float(exit_price),
        quantity=int(quantity),
        funded_amount=float(funded_amount),
        interest_days=int(interest_days),
        slippage_bps=slippage_bps,
        transaction_charge_pct_override=transaction_charge_pct_override,
        dp_base_rupees=dp_base_rupees,
        purchase_date_count=purchase_date_count,
        rms_squareoff_orders=rms_squareoff_orders,
    )
    user_cash = float(economics.get("user_cash_contribution") or 0.0)
    net_pnl = float(economics["net_pnl"])
    result = {
        **base,
        "status": "MTF_ECONOMICS_COMPLETE",
        "exit_price_basis": "STRICT_REPLAY_THRESHOLD_OR_OBSERVATION_CLOSE",
        "gross_pnl": float(economics["gross_pnl"]),
        "total_charges": float(economics.get("charges", {}).get("total", 0.0)),
        "mtf_interest": float(economics.get("funding_interest") or 0.0),
        "net_pnl": net_pnl,
        "user_cash_contribution": user_cash,
        "net_return_on_user_cash_pct": round(net_pnl / user_cash * 100.0, 6) if user_cash > 0 else None,
        "economics": economics,
    }
    if persist:
        _persist(result, db_path=db_path)
    return result


def list_mtf_replays(*, plan_id: str | None = None, limit: int = 100, db_path: str | None = None) -> list[dict[str, Any]]:
    ensure_mtf_replay_schema(db_path)
    clauses: list[str] = []
    args: list[Any] = []
    if plan_id:
        clauses.append("plan_id=?")
        args.append(plan_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    args.append(max(1, min(int(limit), 1000)))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT result_json FROM tb_swing_mtf_replay_economics{where} ORDER BY computed_at DESC LIMIT ?",
            args,
        ).fetchall()
    output = []
    for row in rows:
        try:
            output.append(json.loads(row["result_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
    return output
