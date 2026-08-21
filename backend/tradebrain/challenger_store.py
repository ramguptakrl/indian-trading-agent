"""Persistence for Trade Brain Phase 5 challenger / walk-forward validation.

The store is intentionally append-audit oriented. Experiment definitions and windows
are frozen before evaluation, result rows are tied to that frozen definition, and
promotion/rejection decisions are retained as an immutable history.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from backend.db import DB_PATH
from backend.tradebrain.focus_lab_store import ensure_focus_lab_schema


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


def ensure_challenger_schema(db_path: str | None = None) -> None:
    ensure_focus_lab_schema(db_path)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_challenger_experiments (
                experiment_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                series_id TEXT NOT NULL,
                interval TEXT NOT NULL,
                parameter_key TEXT NOT NULL,
                parameter_scope TEXT NOT NULL,
                parameter_class TEXT NOT NULL,
                incumbent_value_json TEXT NOT NULL,
                challenger_value_json TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                thresholds_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                method_version TEXT NOT NULL,
                definition_sha256 TEXT,
                created_by TEXT NOT NULL DEFAULT 'HUMAN_REQUEST',
                created_at TEXT NOT NULL,
                frozen_at TEXT,
                evaluated_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (series_id) REFERENCES tb_market_series(series_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_challenger_experiments_series
                ON tb_challenger_experiments(series_id, interval, status);
            CREATE INDEX IF NOT EXISTS idx_tb_challenger_experiments_parameter
                ON tb_challenger_experiments(parameter_key, status);

            CREATE TABLE IF NOT EXISTS tb_challenger_windows (
                window_id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                role TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                frozen_at TEXT NOT NULL,
                UNIQUE(experiment_id, role, ordinal),
                FOREIGN KEY (experiment_id) REFERENCES tb_challenger_experiments(experiment_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_challenger_windows_experiment
                ON tb_challenger_windows(experiment_id, starts_at, ends_at);

            CREATE TABLE IF NOT EXISTS tb_challenger_window_results (
                experiment_id TEXT NOT NULL,
                window_id TEXT NOT NULL,
                arm TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                quality_pass INTEGER NOT NULL,
                quality_reasons_json TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                PRIMARY KEY (experiment_id, window_id, arm),
                FOREIGN KEY (experiment_id) REFERENCES tb_challenger_experiments(experiment_id),
                FOREIGN KEY (window_id) REFERENCES tb_challenger_windows(window_id)
            );

            CREATE TABLE IF NOT EXISTS tb_challenger_decisions (
                decision_id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                actor TEXT NOT NULL,
                rationale_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES tb_challenger_experiments(experiment_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_challenger_decisions_experiment
                ON tb_challenger_decisions(experiment_id, created_at);

            CREATE TABLE IF NOT EXISTS tb_soft_parameter_versions (
                parameter_key TEXT NOT NULL,
                parameter_scope TEXT NOT NULL,
                version INTEGER NOT NULL,
                value_json TEXT NOT NULL,
                status TEXT NOT NULL,
                source_experiment_id TEXT,
                approved_by TEXT NOT NULL,
                approval_note TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                retired_at TEXT,
                PRIMARY KEY (parameter_key, parameter_scope, version),
                FOREIGN KEY (source_experiment_id) REFERENCES tb_challenger_experiments(experiment_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_soft_parameter_active
                ON tb_soft_parameter_versions(parameter_key, parameter_scope, status);
            """
        )


def _decode_experiment(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for src, dst, default in (
        ("incumbent_value_json", "incumbent_value", None),
        ("challenger_value_json", "challenger_value", None),
        ("thresholds_json", "thresholds", {}),
    ):
        raw = item.pop(src, None)
        try:
            item[dst] = json.loads(raw) if raw is not None else default
        except json.JSONDecodeError:
            item[dst] = default
    return item


def create_experiment_record(
    *,
    name: str,
    series_id: str,
    interval: str,
    parameter_key: str,
    parameter_scope: str,
    parameter_class: str,
    incumbent_value: Any,
    challenger_value: Any,
    hypothesis: str,
    thresholds: dict[str, Any],
    method_version: str,
    created_by: str = "HUMAN_REQUEST",
    db_path: str | None = None,
) -> dict[str, Any]:
    ensure_challenger_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    experiment_id = str(uuid.uuid4())
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_challenger_experiments(
                experiment_id, name, series_id, interval, parameter_key,
                parameter_scope, parameter_class, incumbent_value_json,
                challenger_value_json, hypothesis, thresholds_json, status,
                method_version, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
            """,
            (
                experiment_id, name, series_id, interval, parameter_key,
                parameter_scope, parameter_class,
                json.dumps(incumbent_value, sort_keys=True, default=str),
                json.dumps(challenger_value, sort_keys=True, default=str),
                hypothesis,
                json.dumps(thresholds, sort_keys=True, default=str),
                method_version, created_by, now, now,
            ),
        )
    return get_experiment(experiment_id, db_path=db_path) or {"experiment_id": experiment_id}


def get_experiment(experiment_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_challenger_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_challenger_experiments WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()
    return _decode_experiment(row)


def set_frozen_definition(
    experiment_id: str,
    *,
    windows: list[dict[str, Any]],
    definition_sha256: str,
    frozen_at: str,
    db_path: str | None = None,
) -> None:
    ensure_challenger_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM tb_challenger_experiments WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown experiment_id: {experiment_id}")
        if row["status"] != "DRAFT":
            raise ValueError("Only a DRAFT experiment can be frozen")
        for window in windows:
            conn.execute(
                """
                INSERT INTO tb_challenger_windows(
                    window_id, experiment_id, role, ordinal, starts_at, ends_at, frozen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    window["window_id"], experiment_id, window["role"], int(window["ordinal"]),
                    window["starts_at"], window["ends_at"], frozen_at,
                ),
            )
        conn.execute(
            """
            UPDATE tb_challenger_experiments
            SET status='FROZEN', definition_sha256=?, frozen_at=?, updated_at=?
            WHERE experiment_id=?
            """,
            (definition_sha256, frozen_at, frozen_at, experiment_id),
        )


def list_windows(experiment_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    ensure_challenger_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM tb_challenger_windows
            WHERE experiment_id=?
            ORDER BY starts_at, ends_at, role, ordinal
            """,
            (experiment_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_window_result(
    *,
    experiment_id: str,
    window_id: str,
    arm: str,
    metrics: dict[str, Any],
    quality_pass: bool,
    quality_reasons: list[str],
    computed_at: str,
    db_path: str | None = None,
) -> None:
    ensure_challenger_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_challenger_window_results(
                experiment_id, window_id, arm, metrics_json, quality_pass,
                quality_reasons_json, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(experiment_id, window_id, arm) DO UPDATE SET
                metrics_json=excluded.metrics_json,
                quality_pass=excluded.quality_pass,
                quality_reasons_json=excluded.quality_reasons_json,
                computed_at=excluded.computed_at
            """,
            (
                experiment_id, window_id, arm,
                json.dumps(metrics, sort_keys=True, ensure_ascii=False, default=str),
                int(quality_pass),
                json.dumps(quality_reasons, ensure_ascii=False),
                computed_at,
            ),
        )


def list_window_results(experiment_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    ensure_challenger_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT r.*, w.role, w.ordinal, w.starts_at, w.ends_at
            FROM tb_challenger_window_results r
            JOIN tb_challenger_windows w ON w.window_id=r.window_id
            WHERE r.experiment_id=?
            ORDER BY w.starts_at, w.role, w.ordinal, r.arm
            """,
            (experiment_id,),
        ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["metrics"] = json.loads(item.pop("metrics_json") or "{}")
        except json.JSONDecodeError:
            item["metrics"] = {}
            item.pop("metrics_json", None)
        try:
            item["quality_reasons"] = json.loads(item.pop("quality_reasons_json") or "[]")
        except json.JSONDecodeError:
            item["quality_reasons"] = ["MALFORMED_QUALITY_REASONS"]
            item.pop("quality_reasons_json", None)
        item["quality_pass"] = bool(item["quality_pass"])
        output.append(item)
    return output


def set_experiment_status(
    experiment_id: str,
    status: str,
    *,
    evaluated_at: str | None = None,
    db_path: str | None = None,
) -> None:
    ensure_challenger_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        if evaluated_at:
            conn.execute(
                """
                UPDATE tb_challenger_experiments
                SET status=?, evaluated_at=?, updated_at=? WHERE experiment_id=?
                """,
                (status, evaluated_at, now, experiment_id),
            )
        else:
            conn.execute(
                "UPDATE tb_challenger_experiments SET status=?, updated_at=? WHERE experiment_id=?",
                (status, now, experiment_id),
            )


def append_decision(
    experiment_id: str,
    *,
    decision: str,
    actor: str,
    rationale: dict[str, Any],
    db_path: str | None = None,
) -> str:
    ensure_challenger_schema(db_path)
    decision_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_challenger_decisions(
                decision_id, experiment_id, decision, actor, rationale_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id, experiment_id, decision, actor,
                json.dumps(rationale, sort_keys=True, ensure_ascii=False, default=str), now,
            ),
        )
    return decision_id


def list_decisions(experiment_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    ensure_challenger_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM tb_challenger_decisions
            WHERE experiment_id=? ORDER BY created_at, decision_id
            """,
            (experiment_id,),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["rationale"] = json.loads(item.pop("rationale_json") or "{}")
        except json.JSONDecodeError:
            item["rationale"] = {}
            item.pop("rationale_json", None)
        output.append(item)
    return output


def activate_soft_parameter(
    *,
    parameter_key: str,
    parameter_scope: str,
    value: Any,
    source_experiment_id: str,
    approved_by: str,
    approval_note: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    ensure_challenger_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        current = conn.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS max_version
            FROM tb_soft_parameter_versions
            WHERE parameter_key=? AND parameter_scope=?
            """,
            (parameter_key, parameter_scope),
        ).fetchone()
        version = int(current["max_version"] or 0) + 1
        conn.execute(
            """
            UPDATE tb_soft_parameter_versions
            SET status='RETIRED', retired_at=?
            WHERE parameter_key=? AND parameter_scope=? AND status='ACTIVE'
            """,
            (now, parameter_key, parameter_scope),
        )
        conn.execute(
            """
            INSERT INTO tb_soft_parameter_versions(
                parameter_key, parameter_scope, version, value_json, status,
                source_experiment_id, approved_by, approval_note, activated_at
            ) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
            """,
            (
                parameter_key, parameter_scope, version,
                json.dumps(value, sort_keys=True, default=str), source_experiment_id,
                approved_by, approval_note, now,
            ),
        )
    return {
        "parameter_key": parameter_key,
        "parameter_scope": parameter_scope,
        "version": version,
        "value": value,
        "status": "ACTIVE",
        "source_experiment_id": source_experiment_id,
        "approved_by": approved_by,
        "approval_note": approval_note,
        "activated_at": now,
    }


def list_soft_parameter_versions(
    *,
    parameter_key: str | None = None,
    active_only: bool = False,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    ensure_challenger_schema(db_path)
    clauses: list[str] = []
    args: list[Any] = []
    if parameter_key:
        clauses.append("parameter_key=?")
        args.append(parameter_key)
    if active_only:
        clauses.append("status='ACTIVE'")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM tb_soft_parameter_versions{where} ORDER BY parameter_key, parameter_scope, version",
            args,
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["value"] = json.loads(item.pop("value_json"))
        except (json.JSONDecodeError, TypeError):
            item["value"] = None
            item.pop("value_json", None)
        output.append(item)
    return output


def challenger_stats(db_path: str | None = None) -> dict[str, int]:
    ensure_challenger_schema(db_path)
    with _connect(db_path) as conn:
        return {
            "experiments": conn.execute("SELECT COUNT(*) FROM tb_challenger_experiments").fetchone()[0],
            "frozen_experiments": conn.execute("SELECT COUNT(*) FROM tb_challenger_experiments WHERE frozen_at IS NOT NULL").fetchone()[0],
            "ready_for_review": conn.execute("SELECT COUNT(*) FROM tb_challenger_experiments WHERE status='READY_FOR_REVIEW'").fetchone()[0],
            "promoted": conn.execute("SELECT COUNT(*) FROM tb_challenger_experiments WHERE status='PROMOTED'").fetchone()[0],
            "rejected": conn.execute("SELECT COUNT(*) FROM tb_challenger_experiments WHERE status='REJECTED'").fetchone()[0],
            "decision_records": conn.execute("SELECT COUNT(*) FROM tb_challenger_decisions").fetchone()[0],
            "active_soft_parameters": conn.execute("SELECT COUNT(*) FROM tb_soft_parameter_versions WHERE status='ACTIVE'").fetchone()[0],
        }
