"""MTF-aware Phase-6 paper accounting for active BSE SWING research.

This is separate from the historical full-notional cash paper ledger. It models the
human cash contribution and Zerodha-funded portion explicitly, uses the versioned MTF
cost engine, and never creates broker execution permission.
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
from backend.tradebrain.bse_scope import require_bse_trade_target
from backend.tradebrain.paper_ledger import ensure_paper_ledger_schema, get_paper_account
from backend.tradebrain.swing_mtf import calculate_swing_mtf_trade_costs

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
METHOD_VERSION = "BSE_PHASE6_MTF_PAPER_LEDGER_V1"


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


def _dt(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("MTF paper-ledger timestamps must be timezone-aware")
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_session_fill(timestamp: datetime) -> None:
    local = timestamp.astimezone(IST)
    clock = local.time().replace(tzinfo=None)
    if clock < MARKET_OPEN or clock >= MARKET_CLOSE:
        raise ValueError("MTF paper fill must represent an Indian cash-market session fill (09:15-15:30 IST)")


def ensure_mtf_paper_schema(db_path: str | None = None) -> None:
    ensure_paper_ledger_schema(db_path)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_phase6_mtf_paper_positions (
                position_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                exchange TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'SWING',
                direction TEXT NOT NULL DEFAULT 'LONG',
                quantity INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                entry_timestamp TEXT NOT NULL,
                position_value REAL NOT NULL,
                funded_amount REAL NOT NULL,
                own_cash_contribution REAL NOT NULL,
                reserved_cash REAL NOT NULL,
                mtf_eligible_verified INTEGER NOT NULL DEFAULT 1,
                purchase_date_count INTEGER NOT NULL DEFAULT 1,
                slippage_bps REAL NOT NULL DEFAULT 0,
                transaction_charge_pct_override REAL,
                dp_base_rupees REAL,
                data_source TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_price REAL,
                exit_timestamp TEXT,
                interest_days INTEGER,
                gross_pnl REAL,
                total_charges REAL,
                mtf_interest REAL,
                net_pnl REAL,
                net_return_on_own_cash_pct REAL,
                economics_json TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES tb_phase6_paper_accounts(account_id)
            );
            CREATE INDEX IF NOT EXISTS idx_tb_phase6_mtf_account_status
                ON tb_phase6_mtf_paper_positions(account_id, status, entry_timestamp);
            """
        )


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["mtf_eligible_verified"] = bool(result.get("mtf_eligible_verified"))
    raw = result.pop("economics_json", None)
    result["economics"] = json.loads(raw) if raw else None
    result["swing_funding"] = "MTF"
    result["method_version"] = METHOD_VERSION
    result["trade_authorization"] = False
    result["order_execution_allowed"] = False
    return result


def open_mtf_paper_position(
    *,
    account_id: str,
    ticker: str,
    exchange: str,
    quantity: int,
    entry_price: float,
    funded_amount: float,
    mtf_eligible_verified: bool,
    entry_timestamp: str | datetime | None = None,
    slippage_bps: float = 0.0,
    transaction_charge_pct_override: float | None = None,
    dp_base_rupees: float | None = None,
    purchase_date_count: int = 1,
    data_source: str = "MANUAL_OR_AUDITED_DATA",
    notes: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    symbol = require_bse_trade_target(ticker)
    ex = exchange.strip().upper()
    if ex != "NSE":
        raise ValueError("Active BSE Ltd SWING paper modeling uses canonical NSE:BSE")
    if not mtf_eligible_verified:
        raise ValueError("Current Zerodha MTF eligibility must be explicitly verified")
    if quantity <= 0 or entry_price <= 0 or funded_amount <= 0:
        raise ValueError("quantity, entry_price and funded_amount must be positive")
    if purchase_date_count <= 0:
        raise ValueError("purchase_date_count must be positive")
    ts = _dt(entry_timestamp)
    _validate_session_fill(ts)

    position_value = float(entry_price) * int(quantity)
    if funded_amount >= position_value:
        raise ValueError("funded_amount must be below total position value")
    own_cash = position_value - float(funded_amount)

    # Reserve the user's contribution plus a conservative one-day flat-price cost
    # cushion. The cushion is released at close while realized net P&L applies the
    # actual supplied interest-days scenario.
    flat = calculate_swing_mtf_trade_costs(
        exchange=ex,
        entry_price=entry_price,
        exit_price=entry_price,
        quantity=quantity,
        funded_amount=funded_amount,
        interest_days=1,
        slippage_bps=slippage_bps,
        transaction_charge_pct_override=transaction_charge_pct_override,
        dp_base_rupees=dp_base_rupees,
        purchase_date_count=purchase_date_count,
        rms_squareoff_orders=0,
    )
    cushion = max(0.0, float(flat.get("charges", {}).get("total", 0.0)))
    reservation = own_cash + cushion

    ensure_mtf_paper_schema(db_path)
    account = get_paper_account(account_id, db_path=db_path)
    if float(account["cash_balance"]) + 1e-9 < reservation:
        raise ValueError(
            f"Insufficient MTF paper cash contribution: need {reservation:.2f}, have {float(account['cash_balance']):.2f}"
        )

    position_id = str(uuid.uuid4())
    now = _now_iso()
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE tb_phase6_paper_accounts SET cash_balance=cash_balance-?, mtf_enabled=1, updated_at=? WHERE account_id=?",
            (reservation, now, account_id),
        )
        conn.execute(
            """
            INSERT INTO tb_phase6_mtf_paper_positions(
                position_id, account_id, ticker, exchange, quantity, entry_price,
                entry_timestamp, position_value, funded_amount, own_cash_contribution,
                reserved_cash, mtf_eligible_verified, purchase_date_count, slippage_bps,
                transaction_charge_pct_override, dp_base_rupees, data_source, notes,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                position_id, account_id, symbol, ex, quantity, entry_price,
                ts.astimezone(timezone.utc).isoformat(), position_value, funded_amount,
                own_cash, reservation, 1, purchase_date_count, slippage_bps,
                transaction_charge_pct_override, dp_base_rupees, data_source, notes,
                now, now,
            ),
        )
    return get_mtf_paper_position(position_id, db_path=db_path)


def get_mtf_paper_position(position_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    ensure_mtf_paper_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_phase6_mtf_paper_positions WHERE position_id=?", (position_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Unknown MTF paper position: {position_id}")
    return _decode(row)


def close_mtf_paper_position(
    position_id: str,
    *,
    exit_price: float,
    interest_days: int,
    exit_timestamp: str | datetime | None = None,
    rms_squareoff_orders: int = 0,
    db_path: str | None = None,
) -> dict[str, Any]:
    if exit_price <= 0:
        raise ValueError("exit_price must be positive")
    if interest_days < 1:
        raise ValueError("A positive MTF interest-days scenario is required at close")
    if rms_squareoff_orders < 0:
        raise ValueError("rms_squareoff_orders cannot be negative")
    exit_ts = _dt(exit_timestamp)
    _validate_session_fill(exit_ts)
    ensure_mtf_paper_schema(db_path)

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_phase6_mtf_paper_positions WHERE position_id=?", (position_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown MTF paper position: {position_id}")
        if row["status"] != "OPEN":
            raise ValueError("MTF paper position is already closed")

        economics = calculate_swing_mtf_trade_costs(
            exchange=row["exchange"],
            entry_price=float(row["entry_price"]),
            exit_price=float(exit_price),
            quantity=int(row["quantity"]),
            funded_amount=float(row["funded_amount"]),
            interest_days=int(interest_days),
            slippage_bps=float(row["slippage_bps"]),
            transaction_charge_pct_override=row["transaction_charge_pct_override"],
            dp_base_rupees=row["dp_base_rupees"],
            purchase_date_count=int(row["purchase_date_count"]),
            rms_squareoff_orders=int(rms_squareoff_orders),
        )
        net_pnl = float(economics["net_pnl"])
        gross_pnl = float(economics["gross_pnl"])
        total_charges = float(economics.get("charges", {}).get("total", 0.0))
        mtf_interest = float(economics.get("mtf", {}).get("interest", economics.get("funding_interest", 0.0)) or 0.0)
        own_cash = float(row["own_cash_contribution"])
        net_return = net_pnl / own_cash * 100.0 if own_cash > 0 else None
        now = _now_iso()
        conn.execute(
            """
            UPDATE tb_phase6_mtf_paper_positions SET
                status='CLOSED', exit_price=?, exit_timestamp=?, interest_days=?,
                gross_pnl=?, total_charges=?, mtf_interest=?, net_pnl=?,
                net_return_on_own_cash_pct=?, economics_json=?, updated_at=?
            WHERE position_id=?
            """,
            (
                exit_price, exit_ts.astimezone(timezone.utc).isoformat(), interest_days,
                gross_pnl, total_charges, mtf_interest, net_pnl, net_return,
                json.dumps(economics, sort_keys=True, default=str), now, position_id,
            ),
        )
        conn.execute(
            """
            UPDATE tb_phase6_paper_accounts
            SET cash_balance=cash_balance+?, realized_net_pnl=realized_net_pnl+?, updated_at=?
            WHERE account_id=?
            """,
            (float(row["reserved_cash"]) + net_pnl, net_pnl, now, row["account_id"]),
        )
    return get_mtf_paper_position(position_id, db_path=db_path)


def list_mtf_paper_positions(
    *, account_id: str, status: str | None = None, db_path: str | None = None
) -> list[dict[str, Any]]:
    ensure_mtf_paper_schema(db_path)
    clauses = ["account_id=?"]
    args: list[Any] = [account_id]
    if status:
        value = status.upper()
        if value not in {"OPEN", "CLOSED"}:
            raise ValueError("status must be OPEN or CLOSED")
        clauses.append("status=?")
        args.append(value)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM tb_phase6_mtf_paper_positions WHERE {' AND '.join(clauses)} ORDER BY entry_timestamp DESC",
            args,
        ).fetchall()
    return [_decode(row) for row in rows]


def mtf_paper_stats(*, db_path: str | None = None) -> dict[str, Any]:
    ensure_mtf_paper_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) AS open_n,
                   SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) AS closed_n,
                   COALESCE(SUM(CASE WHEN status='CLOSED' THEN net_pnl ELSE 0 END), 0) AS realized_net_pnl
            FROM tb_phase6_mtf_paper_positions
            """
        ).fetchone()
    return {
        "method_version": METHOD_VERSION,
        "positions": int(row["total"] or 0),
        "open_positions": int(row["open_n"] or 0),
        "closed_positions": int(row["closed_n"] or 0),
        "realized_net_pnl": round(float(row["realized_net_pnl"] or 0.0), 2),
        "swing_funding": "MTF_ONLY",
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
