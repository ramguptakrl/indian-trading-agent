"""Phase 6 Trade Brain paper ledger for resident INTRADAY + SWING equity.

This ledger is intentionally separate from the repo's generic recommendation simulator.
It tracks explicit quantity, virtual cash, full-notional conservative buying power,
resident equity transaction costs, rule violations, and net-after-cost realized P&L.
It never sends a broker order.
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
from backend.tradebrain.equity_costs import COST_PROFILE_KEY, calculate_equity_trade_costs
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


def ensure_paper_ledger_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_phase6_paper_accounts (
                account_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                trader_profile TEXT NOT NULL DEFAULT 'RESIDENT_INDIAN',
                currency TEXT NOT NULL DEFAULT 'INR',
                starting_cash REAL NOT NULL,
                cash_balance REAL NOT NULL,
                realized_net_pnl REAL NOT NULL DEFAULT 0,
                buying_power_mode TEXT NOT NULL DEFAULT 'CASH_NOTIONAL_CONSERVATIVE',
                mtf_enabled INTEGER NOT NULL DEFAULT 0,
                order_execution_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tb_phase6_paper_positions (
                position_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                exchange TEXT NOT NULL,
                mode TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_timestamp TEXT NOT NULL,
                reserved_cash REAL NOT NULL,
                slippage_bps REAL NOT NULL DEFAULT 0,
                transaction_charge_pct_override REAL,
                dp_base_rupees REAL,
                cost_profile_key TEXT NOT NULL,
                data_source TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_price REAL,
                exit_timestamp TEXT,
                gross_pnl REAL,
                total_charges REAL,
                net_pnl REAL,
                net_return_pct REAL,
                mode_violation INTEGER NOT NULL DEFAULT 0,
                violation_reason TEXT,
                economics_json TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES tb_phase6_paper_accounts(account_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_phase6_positions_account_status
                ON tb_phase6_paper_positions(account_id, status, entry_timestamp);
            CREATE INDEX IF NOT EXISTS idx_tb_phase6_positions_ticker
                ON tb_phase6_paper_positions(ticker, exchange, mode, status);
            """
        )


def _dt(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("Paper-ledger timestamps must be timezone-aware")
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_paper_account(
    *, name: str, starting_cash: float, db_path: str | None = None
) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("name is required")
    if starting_cash <= 0:
        raise ValueError("starting_cash must be positive")
    ensure_paper_ledger_schema(db_path)
    account_id = str(uuid.uuid4())
    now = _now_iso()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_phase6_paper_accounts(
                account_id, name, starting_cash, cash_balance, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (account_id, name.strip(), float(starting_cash), float(starting_cash), now, now),
        )
    return get_paper_account(account_id, db_path=db_path)


def get_paper_account(account_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    ensure_paper_ledger_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_phase6_paper_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown paper account: {account_id}")
        counts = conn.execute(
            """SELECT
                SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) AS open_n,
                SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) AS closed_n,
                SUM(CASE WHEN mode_violation=1 THEN 1 ELSE 0 END) AS violation_n
               FROM tb_phase6_paper_positions WHERE account_id=?""",
            (account_id,),
        ).fetchone()
    result = dict(row)
    result["open_positions"] = int(counts["open_n"] or 0)
    result["closed_positions"] = int(counts["closed_n"] or 0)
    result["mode_violations"] = int(counts["violation_n"] or 0)
    result["mtf_enabled"] = bool(result["mtf_enabled"])
    result["order_execution_enabled"] = bool(result["order_execution_enabled"])
    return result


def _validate_open_time(mode: str, timestamp: datetime) -> None:
    local = timestamp.astimezone(IST)
    clock = local.time().replace(tzinfo=None)
    if clock < MARKET_OPEN or clock >= MARKET_CLOSE:
        raise ValueError("Paper fill must represent an Indian cash-market session fill (09:15-15:30 IST)")
    if mode == "INTRADAY" and clock >= INTRADAY_NO_FRESH_ENTRY:
        raise ValueError("No fresh INTRADAY paper entry from 15:10 IST")


def open_paper_position(
    *,
    account_id: str,
    ticker: str,
    exchange: str,
    mode: str,
    direction: str,
    quantity: int,
    entry_price: float,
    entry_timestamp: str | datetime | None = None,
    slippage_bps: float = 0.0,
    transaction_charge_pct_override: float | None = None,
    dp_base_rupees: float | None = None,
    data_source: str = "MANUAL_OR_AUDITED_DATA",
    notes: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    active_mode = to_active_mode(mode)
    ex = exchange.upper()
    side = direction.upper()
    if ex not in {"NSE", "BSE"}:
        raise ValueError("exchange must be NSE or BSE")
    if side not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if active_mode == "SWING" and side != "LONG":
        raise ValueError("SWING is LONG cash/delivery equity only")
    if quantity <= 0 or entry_price <= 0:
        raise ValueError("quantity and entry_price must be positive")
    ts = _dt(entry_timestamp)
    _validate_open_time(active_mode, ts)

    # Conservative paper buying power: reserve full entry notional plus a same-price
    # round-trip charge cushion. No leverage, no MTF and no hidden funding assumption.
    flat = calculate_equity_trade_costs(
        mode=active_mode, exchange=ex, direction=side, entry_price=entry_price,
        exit_price=entry_price, quantity=quantity, slippage_bps=slippage_bps,
        transaction_charge_pct_override=transaction_charge_pct_override,
        dp_base_rupees=dp_base_rupees,
    )
    reservation = float(entry_price) * int(quantity) + float(flat["charges"]["total"])
    ensure_paper_ledger_schema(db_path)
    position_id = str(uuid.uuid4())
    now = _now_iso()
    with _connect(db_path) as conn:
        account = conn.execute(
            "SELECT * FROM tb_phase6_paper_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if not account:
            raise ValueError(f"Unknown paper account: {account_id}")
        if float(account["cash_balance"]) + 1e-9 < reservation:
            raise ValueError(
                f"Insufficient conservative paper buying power: need {reservation:.2f}, have {float(account['cash_balance']):.2f}"
            )
        conn.execute(
            "UPDATE tb_phase6_paper_accounts SET cash_balance=cash_balance-?, updated_at=? WHERE account_id=?",
            (reservation, now, account_id),
        )
        conn.execute(
            """
            INSERT INTO tb_phase6_paper_positions(
                position_id, account_id, ticker, exchange, mode, direction, quantity,
                entry_price, entry_timestamp, reserved_cash, slippage_bps,
                transaction_charge_pct_override, dp_base_rupees, cost_profile_key,
                data_source, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position_id, account_id, ticker.upper(), ex, active_mode, side, int(quantity),
                float(entry_price), ts.astimezone(timezone.utc).isoformat(), reservation,
                float(slippage_bps), transaction_charge_pct_override, dp_base_rupees,
                COST_PROFILE_KEY, data_source, notes, now, now,
            ),
        )
    return get_paper_position(position_id, db_path=db_path)


def get_paper_position(position_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    ensure_paper_ledger_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_phase6_paper_positions WHERE position_id=?", (position_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Unknown paper position: {position_id}")
    result = dict(row)
    result["mode_violation"] = bool(result["mode_violation"])
    raw = result.pop("economics_json", None)
    result["economics"] = json.loads(raw) if raw else None
    return result


def list_paper_positions(
    *, account_id: str, status: str | None = None, db_path: str | None = None
) -> list[dict[str, Any]]:
    ensure_paper_ledger_schema(db_path)
    args: list[Any] = [account_id]
    where = "account_id=?"
    if status:
        status = status.upper()
        if status not in {"OPEN", "CLOSED"}:
            raise ValueError("status must be OPEN or CLOSED")
        where += " AND status=?"
        args.append(status)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT position_id FROM tb_phase6_paper_positions WHERE {where} ORDER BY entry_timestamp",
            args,
        ).fetchall()
    return [get_paper_position(row["position_id"], db_path=db_path) for row in rows]


def close_paper_position(
    *,
    position_id: str,
    exit_price: float,
    exit_timestamp: str | datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    if exit_price <= 0:
        raise ValueError("exit_price must be positive")
    position = get_paper_position(position_id, db_path=db_path)
    if position["status"] != "OPEN":
        raise ValueError("Paper position is already closed")
    exit_ts = _dt(exit_timestamp)
    entry_ts = _dt(position["entry_timestamp"])
    if exit_ts <= entry_ts:
        raise ValueError("exit_timestamp must be after entry_timestamp")

    violation = False
    reason = None
    if position["mode"] == "INTRADAY":
        entry_local = entry_ts.astimezone(IST)
        exit_local = exit_ts.astimezone(IST)
        if exit_local.date() != entry_local.date():
            violation = True
            reason = "INTRADAY carried beyond entry session"
        elif exit_local.time().replace(tzinfo=None) > INTRADAY_HARD_EXIT:
            violation = True
            reason = "INTRADAY closed after 15:15 IST hard-exit boundary"

    economics = calculate_equity_trade_costs(
        mode=position["mode"], exchange=position["exchange"], direction=position["direction"],
        entry_price=float(position["entry_price"]), exit_price=float(exit_price),
        quantity=int(position["quantity"]), slippage_bps=float(position["slippage_bps"]),
        transaction_charge_pct_override=position.get("transaction_charge_pct_override"),
        dp_base_rupees=position.get("dp_base_rupees"),
    )
    now = _now_iso()
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE tb_phase6_paper_positions SET
                status='CLOSED', exit_price=?, exit_timestamp=?, gross_pnl=?,
                total_charges=?, net_pnl=?, net_return_pct=?, mode_violation=?,
                violation_reason=?, economics_json=?, updated_at=?
            WHERE position_id=?
            """,
            (
                float(exit_price), exit_ts.astimezone(timezone.utc).isoformat(),
                economics["gross_pnl"], economics["charges"]["total"], economics["net_pnl"],
                economics["net_return_on_entry_notional_pct"], int(violation), reason,
                json.dumps(economics, sort_keys=True, ensure_ascii=False), now, position_id,
            ),
        )
        # Reservation is released; realized net P&L is then applied once.
        conn.execute(
            """
            UPDATE tb_phase6_paper_accounts SET
                cash_balance=cash_balance+?+?,
                realized_net_pnl=realized_net_pnl+?,
                updated_at=?
            WHERE account_id=?
            """,
            (
                float(position["reserved_cash"]), economics["net_pnl"], economics["net_pnl"],
                now, position["account_id"],
            ),
        )
    return get_paper_position(position_id, db_path=db_path)


def paper_ledger_stats(db_path: str | None = None) -> dict[str, Any]:
    ensure_paper_ledger_schema(db_path)
    with _connect(db_path) as conn:
        accounts = conn.execute("SELECT COUNT(*) FROM tb_phase6_paper_accounts").fetchone()[0]
        positions = conn.execute("SELECT COUNT(*) FROM tb_phase6_paper_positions").fetchone()[0]
        open_n = conn.execute("SELECT COUNT(*) FROM tb_phase6_paper_positions WHERE status='OPEN'").fetchone()[0]
        violations = conn.execute("SELECT COUNT(*) FROM tb_phase6_paper_positions WHERE mode_violation=1").fetchone()[0]
        net = conn.execute("SELECT COALESCE(SUM(net_pnl),0) FROM tb_phase6_paper_positions WHERE status='CLOSED'").fetchone()[0]
    return {
        "paper_accounts": accounts,
        "paper_positions": positions,
        "open_positions": open_n,
        "mode_violations": violations,
        "realized_net_pnl": round(float(net or 0), 2),
        "active_modes": ["INTRADAY", "SWING"],
        "mtf_enabled": False,
        "order_execution_enabled": False,
    }
