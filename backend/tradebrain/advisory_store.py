"""Persistent Phase-10 final-advisory records keyed to upstream analysis task ids."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from backend.db import DB_PATH


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


def ensure_advisory_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_final_advisories (
                task_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                exchange TEXT NOT NULL,
                research_label TEXT NOT NULL,
                final_status TEXT NOT NULL,
                advisory_json TEXT NOT NULL,
                trade_authorization INTEGER NOT NULL DEFAULT 0,
                order_execution_allowed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tb_final_advisories_status
                ON tb_final_advisories(final_status, updated_at DESC);
            """
        )


def save_final_advisory(
    task_id: str,
    advisory: dict[str, Any],
    *,
    research_label: str,
    db_path: str | None = None,
) -> None:
    ensure_advisory_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_final_advisories(
                task_id, ticker, exchange, research_label, final_status, advisory_json,
                trade_authorization, order_execution_allowed, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                ticker=excluded.ticker,
                exchange=excluded.exchange,
                research_label=excluded.research_label,
                final_status=excluded.final_status,
                advisory_json=excluded.advisory_json,
                trade_authorization=0,
                order_execution_allowed=0,
                updated_at=excluded.updated_at
            """,
            (
                task_id,
                str(advisory.get("ticker") or "UNKNOWN"),
                str(advisory.get("exchange") or "NSE"),
                research_label,
                str(advisory.get("final_status") or "NO_TRADE"),
                json.dumps(advisory, sort_keys=True, ensure_ascii=False, default=str),
                now,
                now,
            ),
        )


def get_final_advisory(task_id: str, *, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_advisory_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_final_advisories WHERE task_id=?", (task_id,)
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["advisory"] = json.loads(item.pop("advisory_json"))
    except json.JSONDecodeError:
        item["advisory"] = {"final_status": "BLOCK_MALFORMED_PERSISTED_ADVISORY"}
        item.pop("advisory_json", None)
    item["trade_authorization"] = False
    item["order_execution_allowed"] = False
    return item
