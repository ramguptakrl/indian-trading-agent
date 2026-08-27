"""Actual manual-trade journal linked to Trade Brain advisories.

This is deliberately separate from hypothetical replay and paper-trading records.
It records what the human actually did at the broker after seeing an advisory.
Active SWING rows are Zerodha-MTF funded and retain explicit funding metadata so the
journal never silently prices a funded position as ordinary own-cash delivery.
It never places, modifies, or cancels broker orders.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.db import DB_PATH
from backend.tradebrain.advisory_store import get_final_advisory
from backend.tradebrain.equity_costs import COST_PROFILE_KEY, calculate_equity_trade_costs
from backend.tradebrain.mtf_economics import PROFILE_KEY as MTF_PROFILE_KEY
from backend.tradebrain.swing_mtf import calculate_swing_mtf_trade_costs
from backend.tradebrain.trade_modes import to_active_mode

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
INTRADAY_NO_FRESH_ENTRY = time(15, 10)
INTRADAY_HARD_EXIT = time(15, 15)
MARKET_CLOSE = time(15, 30)


@contextmanager
def _connect(db_path: str | None = None):
    path = db_path or DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def ensure_actual_trade_schema(db_path: str | None = None) -> None:
    """Create/migrate the journal additively; historical rows remain readable."""
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_actual_trades (
                trade_id TEXT PRIMARY KEY,
                advisory_task_id TEXT,
                advisory_snapshot_json TEXT,
                ticker TEXT NOT NULL,
                exchange TEXT NOT NULL,
                mode TEXT NOT NULL,
                direction TEXT NOT NULL,
                original_quantity INTEGER NOT NULL,
                open_quantity INTEGER NOT NULL,
                avg_entry_price REAL NOT NULL,
                entry_timestamp TEXT NOT NULL,
                stop_loss REAL,
                take_profit REAL,
                broker_order_ref TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                advisory_alignment TEXT NOT NULL DEFAULT 'UNLINKED_MANUAL',
                entry_policy_violation INTEGER NOT NULL DEFAULT 0,
                violation_reasons_json TEXT,
                realized_gross_pnl REAL NOT NULL DEFAULT 0,
                estimated_or_actual_charges REAL NOT NULL DEFAULT 0,
                realized_net_pnl REAL NOT NULL DEFAULT 0,
                notes TEXT,
                manual_tracking_only INTEGER NOT NULL DEFAULT 1,
                order_execution_enabled INTEGER NOT NULL DEFAULT 0,
                swing_funding TEXT,
                mtf_eligible_verified INTEGER,
                funded_amount REAL,
                mtf_profile_key TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tb_actual_trade_exits (
                exit_id TEXT PRIMARY KEY,
                trade_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                exit_price REAL NOT NULL,
                exit_timestamp TEXT NOT NULL,
                gross_pnl REAL NOT NULL,
                estimated_charges REAL NOT NULL,
                actual_charges_override REAL,
                charges_used REAL NOT NULL,
                net_pnl REAL NOT NULL,
                mtf_interest_days INTEGER,
                mtf_funded_amount_allocated REAL,
                cost_allocation_method TEXT,
                economics_json TEXT,
                broker_order_ref TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (trade_id) REFERENCES tb_actual_trades(trade_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_actual_trades_status
                ON tb_actual_trades(status, entry_timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_tb_actual_trades_advisory
                ON tb_actual_trades(advisory_task_id, entry_timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_tb_actual_trade_exits_trade
                ON tb_actual_trade_exits(trade_id, exit_timestamp);
            """
        )
        for name, ddl in (
            ("swing_funding", "TEXT"),
            ("mtf_eligible_verified", "INTEGER"),
            ("funded_amount", "REAL"),
            ("mtf_profile_key", "TEXT"),
        ):
            _ensure_column(conn, "tb_actual_trades", name, ddl)
        for name, ddl in (
            ("mtf_interest_days", "INTEGER"),
            ("mtf_funded_amount_allocated", "REAL"),
            ("cost_allocation_method", "TEXT"),
            ("economics_json", "TEXT"),
        ):
            _ensure_column(conn, "tb_actual_trade_exits", name, ddl)


def _dt(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("Actual-trade timestamps must be timezone-aware")
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entry_policy_notes(mode: str, ts: datetime) -> list[str]:
    local = ts.astimezone(IST)
    clock = local.time().replace(tzinfo=None)
    notes: list[str] = []
    if clock < MARKET_OPEN or clock >= MARKET_CLOSE:
        notes.append("Entry timestamp is outside the regular 09:15-15:30 IST cash-market session")
    if mode == "INTRADAY" and clock >= INTRADAY_NO_FRESH_ENTRY:
        notes.append("INTRADAY entry is at/after the 15:10 IST no-fresh-entry boundary")
    return notes


def _advisory_link(
    advisory_task_id: str | None,
    *,
    ticker: str,
    exchange: str,
    direction: str,
    db_path: str | None,
) -> tuple[dict[str, Any] | None, str]:
    if not advisory_task_id:
        return None, "UNLINKED_MANUAL"
    record = get_final_advisory(advisory_task_id, db_path=db_path)
    if not record:
        raise ValueError(f"Unknown Trade Brain advisory task: {advisory_task_id}")
    if str(record.get("ticker", "")).upper() != ticker.upper():
        raise ValueError("Linked advisory ticker does not match the actual trade ticker")
    if str(record.get("exchange", "")).upper() != exchange.upper():
        raise ValueError("Linked advisory exchange does not match the actual trade exchange")

    label = str(record.get("research_label") or "").upper()
    expected = "LONG" if label == "LONG_CANDIDATE" else "SHORT" if label == "SHORT_CANDIDATE" else None
    if expected is None:
        alignment = "LINKED_NON_ENTRY_ADVISORY"
    elif expected != direction.upper():
        alignment = "DIRECTION_MISMATCH"
    else:
        alignment = "MATCHED"
    return record, alignment


def _validate_funding(
    *,
    mode: str,
    quantity: int,
    entry_price: float,
    swing_funding: str | None,
    mtf_eligible_verified: bool | None,
    funded_amount: float | None,
) -> tuple[str | None, bool | None, float | None, str | None]:
    if mode != "SWING":
        if swing_funding is not None or mtf_eligible_verified is not None or funded_amount is not None:
            raise ValueError("MTF funding fields apply only to SWING actual trades")
        return None, None, None, None

    funding = str(swing_funding or "").strip().upper()
    if funding != "MTF":
        raise ValueError("Active SWING actual trades require swing_funding=MTF")
    if mtf_eligible_verified is not True:
        raise ValueError("Active SWING actual trades require current MTF eligibility to be verified")
    if funded_amount is None or funded_amount <= 0:
        raise ValueError("Active SWING actual trades require a positive funded_amount")
    entry_notional = float(entry_price) * int(quantity)
    if float(funded_amount) >= entry_notional:
        raise ValueError("funded_amount must be below the actual SWING entry notional")
    return "MTF", True, round(float(funded_amount), 2), MTF_PROFILE_KEY


def record_actual_trade(
    *,
    ticker: str,
    exchange: str,
    mode: str,
    direction: str,
    quantity: int,
    entry_price: float,
    entry_timestamp: str | datetime | None = None,
    advisory_task_id: str | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    broker_order_ref: str | None = None,
    notes: str | None = None,
    swing_funding: str | None = None,
    mtf_eligible_verified: bool | None = None,
    funded_amount: float | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    active_mode = to_active_mode(mode)
    ex = exchange.upper()
    side = direction.upper()
    symbol = ticker.upper().strip()
    if not symbol:
        raise ValueError("ticker is required")
    if ex not in {"NSE", "BSE"}:
        raise ValueError("exchange must be NSE or BSE")
    if side not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if active_mode == "SWING" and side != "LONG":
        raise ValueError("SWING is LONG-only in the active architecture")
    if quantity <= 0 or entry_price <= 0:
        raise ValueError("quantity and entry_price must be positive")
    if stop_loss is not None and stop_loss <= 0:
        raise ValueError("stop_loss must be positive when supplied")
    if take_profit is not None and take_profit <= 0:
        raise ValueError("take_profit must be positive when supplied")

    funding, eligible, funded, mtf_profile = _validate_funding(
        mode=active_mode,
        quantity=quantity,
        entry_price=entry_price,
        swing_funding=swing_funding,
        mtf_eligible_verified=mtf_eligible_verified,
        funded_amount=funded_amount,
    )
    ts = _dt(entry_timestamp)
    violations = _entry_policy_notes(active_mode, ts)
    advisory, alignment = _advisory_link(
        advisory_task_id,
        ticker=symbol,
        exchange=ex,
        direction=side,
        db_path=db_path,
    )
    ensure_actual_trade_schema(db_path)
    trade_id = str(uuid.uuid4())
    now = _now_iso()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_actual_trades(
                trade_id, advisory_task_id, advisory_snapshot_json, ticker, exchange,
                mode, direction, original_quantity, open_quantity, avg_entry_price,
                entry_timestamp, stop_loss, take_profit, broker_order_ref, status,
                advisory_alignment, entry_policy_violation, violation_reasons_json,
                notes, swing_funding, mtf_eligible_verified, funded_amount, mtf_profile_key,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                advisory_task_id,
                json.dumps(advisory, sort_keys=True, ensure_ascii=False, default=str) if advisory else None,
                symbol,
                ex,
                active_mode,
                side,
                int(quantity),
                int(quantity),
                float(entry_price),
                ts.astimezone(timezone.utc).isoformat(),
                stop_loss,
                take_profit,
                broker_order_ref,
                alignment,
                int(bool(violations)),
                json.dumps(violations, ensure_ascii=False),
                notes,
                funding,
                int(eligible) if eligible is not None else None,
                funded,
                mtf_profile,
                now,
                now,
            ),
        )
    return get_actual_trade(trade_id, db_path=db_path)


def _row_to_trade(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["manual_tracking_only"] = True
    item["order_execution_enabled"] = False
    item["entry_policy_violation"] = bool(item["entry_policy_violation"])
    if item.get("mtf_eligible_verified") is not None:
        item["mtf_eligible_verified"] = bool(item["mtf_eligible_verified"])
    try:
        item["violation_reasons"] = json.loads(item.pop("violation_reasons_json") or "[]")
    except json.JSONDecodeError:
        item["violation_reasons"] = ["Malformed stored violation metadata"]
        item.pop("violation_reasons_json", None)
    raw_advisory = item.pop("advisory_snapshot_json", None)
    if raw_advisory:
        try:
            item["advisory_snapshot"] = json.loads(raw_advisory)
        except json.JSONDecodeError:
            item["advisory_snapshot"] = None
    else:
        item["advisory_snapshot"] = None
    item["observation_kind"] = "ACTUAL_MANUAL_TRADE"
    item["costs_are_estimated_unless_overridden"] = True
    if item.get("mode") == "SWING":
        complete = (
            item.get("swing_funding") == "MTF"
            and item.get("mtf_eligible_verified") is True
            and float(item.get("funded_amount") or 0) > 0
        )
        item["mtf_metadata_status"] = "COMPLETE" if complete else "LEGACY_MTF_METADATA_MISSING"
    else:
        item["mtf_metadata_status"] = "NOT_APPLICABLE"
    return item


def _row_to_exit(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    raw = item.pop("economics_json", None)
    if raw:
        try:
            item["economics"] = json.loads(raw)
        except json.JSONDecodeError:
            item["economics"] = None
    else:
        item["economics"] = None
    return item


def get_actual_trade(trade_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    ensure_actual_trade_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM tb_actual_trades WHERE trade_id=?", (trade_id,)).fetchone()
        if not row:
            raise ValueError(f"Unknown actual trade: {trade_id}")
        exits = conn.execute(
            "SELECT * FROM tb_actual_trade_exits WHERE trade_id=? ORDER BY exit_timestamp, created_at",
            (trade_id,),
        ).fetchall()
    result = _row_to_trade(row)
    result["exits"] = [_row_to_exit(x) for x in exits]
    return result


def list_actual_trades(
    *,
    status: str | None = None,
    advisory_task_id: str | None = None,
    limit: int = 200,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    ensure_actual_trade_schema(db_path)
    clauses: list[str] = []
    args: list[Any] = []
    if status:
        normalized = status.upper()
        if normalized not in {"OPEN", "PARTIALLY_CLOSED", "CLOSED"}:
            raise ValueError("status must be OPEN, PARTIALLY_CLOSED, or CLOSED")
        clauses.append("status=?")
        args.append(normalized)
    if advisory_task_id:
        clauses.append("advisory_task_id=?")
        args.append(advisory_task_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    n = max(1, min(int(limit), 1000))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM tb_actual_trades {where} ORDER BY entry_timestamp DESC LIMIT ?",
            (*args, n),
        ).fetchall()
    return [_row_to_trade(row) for row in rows]


def _gross_pnl(direction: str, entry: float, exit_price: float, quantity: int) -> float:
    if direction == "LONG":
        return round((exit_price - entry) * quantity, 2)
    return round((entry - exit_price) * quantity, 2)


def _estimated_slice_economics(
    trade: dict[str, Any],
    *,
    exit_price: float,
    quantity: int,
    mtf_interest_days: int | None,
) -> dict[str, Any]:
    gross = _gross_pnl(trade["direction"], float(trade["avg_entry_price"]), float(exit_price), quantity)
    if trade["mode"] != "SWING":
        economics = calculate_equity_trade_costs(
            mode=trade["mode"],
            exchange=trade["exchange"],
            direction=trade["direction"],
            entry_price=float(trade["avg_entry_price"]),
            exit_price=float(exit_price),
            quantity=quantity,
        )
        charges = float(economics["charges"]["total"])
        return {
            "gross_pnl": gross,
            "estimated_charges": charges,
            "estimated_net_pnl": round(gross - charges, 2),
            "cost_allocation_method": "DIRECT_SLICE_EQUITY_COSTS",
            "mtf_funded_amount_allocated": None,
            "economics": economics,
        }

    if trade.get("mtf_metadata_status") != "COMPLETE":
        raise ValueError(
            "Historical SWING trade lacks MTF funding metadata; supply/reconcile MTF metadata before estimating funded economics"
        )
    if mtf_interest_days is None or int(mtf_interest_days) < 0:
        raise ValueError("SWING close/mark requires explicit mtf_interest_days >= 0")

    original_qty = int(trade["original_quantity"])
    fraction = float(quantity) / float(original_qty)
    full = calculate_swing_mtf_trade_costs(
        exchange=trade["exchange"],
        entry_price=float(trade["avg_entry_price"]),
        exit_price=float(exit_price),
        quantity=original_qty,
        funded_amount=float(trade["funded_amount"]),
        interest_days=int(mtf_interest_days),
    )
    allocated_charges = round(float(full["charges"]["total"]) * fraction, 2)
    funded_allocated = round(float(trade["funded_amount"]) * fraction, 2)
    economics = {
        "full_original_position_scenario": full,
        "allocation_fraction": round(fraction, 8),
        "allocated_quantity": int(quantity),
        "allocated_funded_amount": funded_allocated,
        "allocated_estimated_charges": allocated_charges,
        "allocation_method": "PRO_RATA_ORIGINAL_POSITION_ESTIMATE",
        "note": (
            "Fixed/capped MTF and delivery charges are estimated once on the original position and allocated pro-rata "
            "to avoid double-counting across partial exits. Broker-statement actual charges should override this estimate."
        ),
    }
    return {
        "gross_pnl": gross,
        "estimated_charges": allocated_charges,
        "estimated_net_pnl": round(gross - allocated_charges, 2),
        "cost_allocation_method": "PRO_RATA_ORIGINAL_POSITION_ESTIMATE",
        "mtf_funded_amount_allocated": funded_allocated,
        "economics": economics,
    }


def close_actual_trade(
    *,
    trade_id: str,
    exit_price: float,
    quantity: int | None = None,
    exit_timestamp: str | datetime | None = None,
    actual_charges_override: float | None = None,
    broker_order_ref: str | None = None,
    notes: str | None = None,
    mtf_interest_days: int | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    if exit_price <= 0:
        raise ValueError("exit_price must be positive")
    trade = get_actual_trade(trade_id, db_path=db_path)
    if trade["status"] == "CLOSED" or int(trade["open_quantity"]) <= 0:
        raise ValueError("Actual trade is already closed")
    close_qty = int(quantity if quantity is not None else trade["open_quantity"])
    if close_qty <= 0 or close_qty > int(trade["open_quantity"]):
        raise ValueError("close quantity must be positive and cannot exceed open quantity")
    if actual_charges_override is not None and actual_charges_override < 0:
        raise ValueError("actual_charges_override must be >= 0")

    exit_ts = _dt(exit_timestamp)
    entry_ts = _dt(trade["entry_timestamp"])
    if exit_ts <= entry_ts:
        raise ValueError("exit_timestamp must be after entry_timestamp")

    violations = list(trade.get("violation_reasons") or [])
    if trade["mode"] == "INTRADAY":
        entry_local = entry_ts.astimezone(IST)
        exit_local = exit_ts.astimezone(IST)
        if exit_local.date() != entry_local.date():
            violations.append("INTRADAY actual trade carried beyond the entry session")
        elif exit_local.time().replace(tzinfo=None) > INTRADAY_HARD_EXIT:
            violations.append("INTRADAY actual trade closed after the 15:15 IST hard-exit boundary")

    estimated = _estimated_slice_economics(
        trade,
        exit_price=float(exit_price),
        quantity=close_qty,
        mtf_interest_days=mtf_interest_days,
    )
    gross = float(estimated["gross_pnl"])
    estimated_charges = float(estimated["estimated_charges"])
    charges_used = float(actual_charges_override) if actual_charges_override is not None else estimated_charges
    net = round(gross - charges_used, 2)
    new_open = int(trade["open_quantity"]) - close_qty
    new_status = "CLOSED" if new_open == 0 else "PARTIALLY_CLOSED"
    now = _now_iso()
    exit_id = str(uuid.uuid4())

    stored_economics = dict(estimated["economics"])
    stored_economics["actual_charges_override"] = actual_charges_override
    stored_economics["charges_used"] = charges_used
    stored_economics["net_pnl_after_charges_used"] = net

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_actual_trade_exits(
                exit_id, trade_id, quantity, exit_price, exit_timestamp, gross_pnl,
                estimated_charges, actual_charges_override, charges_used, net_pnl,
                mtf_interest_days, mtf_funded_amount_allocated, cost_allocation_method,
                economics_json, broker_order_ref, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exit_id,
                trade_id,
                close_qty,
                float(exit_price),
                exit_ts.astimezone(timezone.utc).isoformat(),
                gross,
                estimated_charges,
                actual_charges_override,
                charges_used,
                net,
                int(mtf_interest_days) if trade["mode"] == "SWING" and mtf_interest_days is not None else None,
                estimated["mtf_funded_amount_allocated"],
                estimated["cost_allocation_method"],
                json.dumps(stored_economics, sort_keys=True, ensure_ascii=False, default=str),
                broker_order_ref,
                notes,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE tb_actual_trades SET
                open_quantity=?, status=?,
                realized_gross_pnl=realized_gross_pnl+?,
                estimated_or_actual_charges=estimated_or_actual_charges+?,
                realized_net_pnl=realized_net_pnl+?,
                entry_policy_violation=?, violation_reasons_json=?,
                updated_at=?, closed_at=?
            WHERE trade_id=?
            """,
            (
                new_open,
                new_status,
                gross,
                charges_used,
                net,
                int(bool(violations)),
                json.dumps(sorted(set(violations)), ensure_ascii=False),
                now,
                exit_ts.astimezone(timezone.utc).isoformat() if new_status == "CLOSED" else None,
                trade_id,
            ),
        )
    return get_actual_trade(trade_id, db_path=db_path)


def mark_actual_trade(
    *,
    trade_id: str,
    current_price: float,
    source: str = "MANUAL_OR_MARKET_DATA",
    mtf_interest_days: int | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    trade = get_actual_trade(trade_id, db_path=db_path)
    open_qty = int(trade["open_quantity"])
    if open_qty <= 0:
        return {
            "trade_id": trade_id,
            "status": trade["status"],
            "current_price": float(current_price),
            "source": source,
            "open_quantity": 0,
            "unrealized_gross_pnl": 0.0,
            "estimated_open_net_pnl_if_closed_now": 0.0,
            "realized_net_pnl": float(trade["realized_net_pnl"]),
            "combined_realized_plus_estimated_open_net_pnl": float(trade["realized_net_pnl"]),
            "order_execution_allowed": False,
        }

    unrealized_gross = _gross_pnl(
        trade["direction"], float(trade["avg_entry_price"]), float(current_price), open_qty
    )
    if trade["mode"] == "SWING" and mtf_interest_days is None:
        return {
            "trade_id": trade_id,
            "status": trade["status"],
            "ticker": trade["ticker"],
            "mode": trade["mode"],
            "direction": trade["direction"],
            "current_price": float(current_price),
            "source": source,
            "open_quantity": open_qty,
            "unrealized_gross_pnl": unrealized_gross,
            "estimated_open_charges_if_closed_now": None,
            "estimated_open_net_pnl_if_closed_now": None,
            "realized_net_pnl": float(trade["realized_net_pnl"]),
            "combined_realized_plus_estimated_open_net_pnl": None,
            "estimate_status": "MTF_INTEREST_DAYS_REQUIRED",
            "mtf_metadata_status": trade.get("mtf_metadata_status"),
            "charges_estimated": False,
            "manual_tracking_only": True,
            "order_execution_allowed": False,
        }

    estimated = _estimated_slice_economics(
        trade,
        exit_price=float(current_price),
        quantity=open_qty,
        mtf_interest_days=mtf_interest_days,
    )
    estimated_open_net = float(estimated["estimated_net_pnl"])
    combined = round(float(trade["realized_net_pnl"]) + estimated_open_net, 2)
    return {
        "trade_id": trade_id,
        "status": trade["status"],
        "ticker": trade["ticker"],
        "mode": trade["mode"],
        "direction": trade["direction"],
        "current_price": float(current_price),
        "source": source,
        "open_quantity": open_qty,
        "unrealized_gross_pnl": unrealized_gross,
        "estimated_open_charges_if_closed_now": float(estimated["estimated_charges"]),
        "estimated_open_net_pnl_if_closed_now": estimated_open_net,
        "realized_net_pnl": float(trade["realized_net_pnl"]),
        "combined_realized_plus_estimated_open_net_pnl": combined,
        "cost_profile_key": COST_PROFILE_KEY,
        "mtf_profile_key": trade.get("mtf_profile_key"),
        "mtf_interest_days": int(mtf_interest_days) if trade["mode"] == "SWING" and mtf_interest_days is not None else None,
        "mtf_funded_amount_allocated": estimated["mtf_funded_amount_allocated"],
        "cost_allocation_method": estimated["cost_allocation_method"],
        "estimate_status": "COMPUTED",
        "charges_estimated": True,
        "manual_tracking_only": True,
        "order_execution_allowed": False,
    }


def actual_trade_stats(db_path: str | None = None) -> dict[str, Any]:
    ensure_actual_trade_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) AS open_n,
                SUM(CASE WHEN status='PARTIALLY_CLOSED' THEN 1 ELSE 0 END) AS partial_n,
                SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) AS closed_n,
                COALESCE(SUM(realized_gross_pnl),0) AS gross,
                COALESCE(SUM(estimated_or_actual_charges),0) AS charges,
                COALESCE(SUM(realized_net_pnl),0) AS net,
                SUM(CASE WHEN advisory_task_id IS NOT NULL THEN 1 ELSE 0 END) AS linked_n,
                SUM(CASE WHEN mode='SWING' AND swing_funding='MTF' AND mtf_eligible_verified=1 AND funded_amount>0 THEN 1 ELSE 0 END) AS mtf_swing_n,
                SUM(CASE WHEN mode='SWING' AND (swing_funding IS NULL OR funded_amount IS NULL OR funded_amount<=0) THEN 1 ELSE 0 END) AS legacy_swing_missing_mtf_n
            FROM tb_actual_trades
            """
        ).fetchone()
    return {
        "actual_trades": int(row["n"] or 0),
        "open": int(row["open_n"] or 0),
        "partially_closed": int(row["partial_n"] or 0),
        "closed": int(row["closed_n"] or 0),
        "linked_to_advisory": int(row["linked_n"] or 0),
        "swing_mtf": int(row["mtf_swing_n"] or 0),
        "legacy_swing_missing_mtf_metadata": int(row["legacy_swing_missing_mtf_n"] or 0),
        "realized_gross_pnl": round(float(row["gross"] or 0), 2),
        "charges_used": round(float(row["charges"] or 0), 2),
        "realized_net_pnl": round(float(row["net"] or 0), 2),
        "observation_kind": "ACTUAL_MANUAL_TRADE",
        "swing_funding": "MTF_ONLY_FOR_NEW_ACTIVE_SWING_ROWS",
        "manual_tracking_only": True,
        "order_execution_enabled": False,
    }
