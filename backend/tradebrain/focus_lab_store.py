"""Persistence for Trade Brain Phase 4 outcome learning and Focus Instrument Lab.

Replay outcomes are deliberately stored separately from `tb_trade_plan_outcomes`.
The latter can represent manually supplied/real outcomes; this module stores only
counterfactual/hypothetical outcomes reconstructed from audited Phase-3 candles.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Any

from backend.db import DB_PATH
from backend.tradebrain.market_data_store import ensure_market_data_schema


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


def ensure_focus_lab_schema(db_path: str | None = None) -> None:
    ensure_market_data_schema(db_path)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_replay_plan_outcomes (
                plan_id TEXT NOT NULL,
                series_id TEXT NOT NULL,
                interval TEXT NOT NULL,
                observation_kind TEXT NOT NULL DEFAULT 'HYPOTHETICAL_REPLAY',
                outcome TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                observation_end TEXT,
                entry_bar_open TEXT,
                entry_fill_price REAL,
                exit_bar_open TEXT,
                exit_timestamp TEXT,
                exit_price REAL,
                mae_pct REAL,
                mfe_pct REAL,
                r_multiple REAL,
                time_to_event_minutes REAL,
                bars_observed INTEGER NOT NULL DEFAULT 0,
                sessions_observed INTEGER NOT NULL DEFAULT 0,
                ambiguity_reason TEXT,
                regime TEXT,
                regime_basis TEXT,
                method_version TEXT NOT NULL,
                metadata_json TEXT,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (plan_id, series_id, interval),
                FOREIGN KEY (plan_id) REFERENCES tb_trade_plan_evaluations(plan_id),
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_replay_outcomes_series
                ON tb_replay_plan_outcomes(series_id, interval, outcome);
            CREATE INDEX IF NOT EXISTS idx_tb_replay_outcomes_regime
                ON tb_replay_plan_outcomes(series_id, interval, regime, outcome);

            CREATE TABLE IF NOT EXISTS tb_level_reliability_runs (
                study_id TEXT PRIMARY KEY,
                series_id TEXT NOT NULL,
                interval TEXT NOT NULL,
                level_type TEXT NOT NULL,
                level_price REAL NOT NULL,
                tolerance_pct REAL NOT NULL,
                reaction_pct REAL NOT NULL,
                break_pct REAL NOT NULL,
                horizon_bars INTEGER NOT NULL,
                as_of TEXT,
                method_version TEXT NOT NULL,
                result_json TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_level_runs_series
                ON tb_level_reliability_runs(series_id, interval, computed_at DESC);
            """
        )


def get_plan(plan_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_focus_lab_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_trade_plan_evaluations WHERE plan_id=?", (plan_id,)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    for key in ("hard_rule_failures", "warnings", "evidence"):
        try:
            result[key] = json.loads(result.get(key) or "[]")
        except json.JSONDecodeError:
            result[key] = []
    return result


def list_plans(
    *,
    exchange: str | None = None,
    ticker: str | None = None,
    limit: int = 1000,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    ensure_focus_lab_schema(db_path)
    clauses: list[str] = []
    args: list[Any] = []
    if exchange:
        clauses.append("exchange=?")
        args.append(exchange.upper())
    if ticker:
        clauses.append("ticker=?")
        args.append(ticker.upper())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    args.append(max(1, min(limit, 100000)))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM tb_trade_plan_evaluations{where} ORDER BY evaluated_at_ist LIMIT ?",
            args,
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        for key in ("hard_rule_failures", "warnings", "evidence"):
            try:
                item[key] = json.loads(item.get(key) or "[]")
            except json.JSONDecodeError:
                item[key] = []
        results.append(item)
    return results


def upsert_replay_outcome(result: dict[str, Any], db_path: str | None = None) -> None:
    ensure_focus_lab_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_replay_plan_outcomes(
                plan_id, series_id, interval, observation_kind, outcome, evaluated_at,
                observation_end, entry_bar_open, entry_fill_price, exit_bar_open,
                exit_timestamp, exit_price, mae_pct, mfe_pct, r_multiple,
                time_to_event_minutes, bars_observed, sessions_observed,
                ambiguity_reason, regime, regime_basis, method_version, metadata_json,
                computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_id, series_id, interval) DO UPDATE SET
                observation_kind=excluded.observation_kind,
                outcome=excluded.outcome,
                evaluated_at=excluded.evaluated_at,
                observation_end=excluded.observation_end,
                entry_bar_open=excluded.entry_bar_open,
                entry_fill_price=excluded.entry_fill_price,
                exit_bar_open=excluded.exit_bar_open,
                exit_timestamp=excluded.exit_timestamp,
                exit_price=excluded.exit_price,
                mae_pct=excluded.mae_pct,
                mfe_pct=excluded.mfe_pct,
                r_multiple=excluded.r_multiple,
                time_to_event_minutes=excluded.time_to_event_minutes,
                bars_observed=excluded.bars_observed,
                sessions_observed=excluded.sessions_observed,
                ambiguity_reason=excluded.ambiguity_reason,
                regime=excluded.regime,
                regime_basis=excluded.regime_basis,
                method_version=excluded.method_version,
                metadata_json=excluded.metadata_json,
                computed_at=excluded.computed_at
            """,
            (
                result["plan_id"], result["series_id"], result["interval"],
                result.get("observation_kind", "HYPOTHETICAL_REPLAY"), result["outcome"],
                result["evaluated_at"], result.get("observation_end"),
                result.get("entry_bar_open"), result.get("entry_fill_price"),
                result.get("exit_bar_open"), result.get("exit_timestamp"),
                result.get("exit_price"), result.get("mae_pct"), result.get("mfe_pct"),
                result.get("r_multiple"), result.get("time_to_event_minutes"),
                int(result.get("bars_observed") or 0), int(result.get("sessions_observed") or 0),
                result.get("ambiguity_reason"), result.get("regime"),
                result.get("regime_basis"), result["method_version"],
                json.dumps(result.get("metadata") or {}, sort_keys=True, ensure_ascii=False, default=str),
                result["computed_at"],
            ),
        )


def get_replay_outcome(
    plan_id: str, series_id: str, interval: str, db_path: str | None = None
) -> dict[str, Any] | None:
    ensure_focus_lab_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT r.*, p.ticker, p.exchange, p.mode, p.direction, p.entry, p.stop_loss,
                   p.take_profit, p.crash_guard, p.reward_risk, p.gate_action,
                   p.allowed_for_advisory
            FROM tb_replay_plan_outcomes r
            JOIN tb_trade_plan_evaluations p ON p.plan_id=r.plan_id
            WHERE r.plan_id=? AND r.series_id=? AND r.interval=?
            """,
            (plan_id, series_id, interval),
        ).fetchone()
    return _decode_outcome(row) if row else None


def list_replay_outcomes(
    *,
    series_id: str,
    interval: str,
    limit: int = 10000,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    ensure_focus_lab_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT r.*, p.ticker, p.exchange, p.mode, p.direction, p.entry, p.stop_loss,
                   p.take_profit, p.crash_guard, p.reward_risk, p.gate_action,
                   p.allowed_for_advisory, p.evaluated_at_ist
            FROM tb_replay_plan_outcomes r
            JOIN tb_trade_plan_evaluations p ON p.plan_id=r.plan_id
            WHERE r.series_id=? AND r.interval=?
            ORDER BY p.evaluated_at_ist
            LIMIT ?
            """,
            (series_id, interval, max(1, min(limit, 100000))),
        ).fetchall()
    return [_decode_outcome(row) for row in rows]


def _decode_outcome(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    try:
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    except json.JSONDecodeError:
        result["metadata"] = {}
        result.pop("metadata_json", None)
    return result


def persist_level_study(
    *,
    series_id: str,
    interval: str,
    level_type: str,
    level_price: float,
    tolerance_pct: float,
    reaction_pct: float,
    break_pct: float,
    horizon_bars: int,
    as_of: str | None,
    method_version: str,
    result: dict[str, Any],
    computed_at: str,
    db_path: str | None = None,
) -> str:
    ensure_focus_lab_schema(db_path)
    study_id = str(uuid.uuid4())
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_level_reliability_runs(
                study_id, series_id, interval, level_type, level_price, tolerance_pct,
                reaction_pct, break_pct, horizon_bars, as_of, method_version,
                result_json, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                study_id, series_id, interval, level_type, float(level_price),
                float(tolerance_pct), float(reaction_pct), float(break_pct),
                int(horizon_bars), as_of, method_version,
                json.dumps(result, sort_keys=True, ensure_ascii=False, default=str), computed_at,
            ),
        )
    return study_id


def event_category_effect_rows(
    series_id: str, horizon_sessions: int, db_path: str | None = None
) -> list[dict[str, Any]]:
    ensure_focus_lab_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT e.category, e.importance, e.source_critical, e.event_id,
                   x.return_pct, x.mae_pct, x.mfe_pct, x.bars_observed, x.method
            FROM tb_event_price_effects x
            JOIN tb_corporate_events e ON e.event_id=x.event_id
            WHERE x.series_id=? AND x.horizon_sessions=?
            ORDER BY e.category, e.announced_at
            """,
            (series_id, int(horizon_sessions)),
        ).fetchall()
    return [dict(row) for row in rows]


def focus_lab_stats(db_path: str | None = None) -> dict[str, int]:
    ensure_focus_lab_schema(db_path)
    with _connect(db_path) as conn:
        return {
            "replay_plan_outcomes": conn.execute("SELECT COUNT(*) FROM tb_replay_plan_outcomes").fetchone()[0],
            "ambiguous_replay_outcomes": conn.execute("SELECT COUNT(*) FROM tb_replay_plan_outcomes WHERE outcome='AMBIGUOUS'").fetchone()[0],
            "level_reliability_runs": conn.execute("SELECT COUNT(*) FROM tb_level_reliability_runs").fetchone()[0],
        }
