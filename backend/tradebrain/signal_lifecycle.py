"""Persistent publication governor for Trade Brain advisory candidates.

Trade Brain may re-evaluate frequently, including on each completed 5-minute bar, but a
new user-visible trade plan is event-driven rather than bar-driven. This module is the
boundary between repeated analysis and publication:

* no fixed number of trades per day;
* an existing plan remains sticky while repeated same-direction candidates arrive;
* WAIT / blocked evaluations never silently erase an active plan;
* an opposite INTRADAY candidate must be confirmed on a subsequent publishable
  evaluation before it can replace the active plan;
* INTRADAY plans expire across the session/date boundary;
* SWING plans remain sticky across dates until explicitly terminated or replaced by a
  future lifecycle rule.

This is advisory state only. It never authorizes or places broker orders.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.db import DB_PATH
from backend.tradebrain.advisory_pipeline import parse_agent_candidate

IST = ZoneInfo("Asia/Kolkata")
METHOD_VERSION = "BSE_SIGNAL_LIFECYCLE_V1"
PUBLISHABLE_STATUS = "ADVISORY_CANDIDATE_PASS"
ACTIVE_STATE = "ACTIVE"
TERMINAL_STATE = "TERMINAL"
REVERSAL_CONFIRMATIONS_REQUIRED = 2


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


def ensure_signal_lifecycle_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_signal_lifecycle_current (
                ticker TEXT NOT NULL,
                horizon TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                direction TEXT NOT NULL,
                state TEXT NOT NULL,
                plan_fingerprint TEXT NOT NULL,
                advisory_json TEXT NOT NULL,
                pending_direction TEXT,
                pending_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(ticker, horizon)
            );

            CREATE TABLE IF NOT EXISTS tb_signal_lifecycle_events (
                event_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                horizon TEXT,
                trade_date TEXT,
                plan_id TEXT,
                action TEXT NOT NULL,
                direction TEXT,
                candidate_fingerprint TEXT,
                published_new_trade INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                trade_authorization INTEGER NOT NULL DEFAULT 0,
                order_execution_allowed INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_tb_signal_lifecycle_events_lookup
                ON tb_signal_lifecycle_events(ticker, horizon, evaluated_at DESC);
            """
        )


def _aware(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(IST)
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("signal lifecycle evaluated_at must be timezone-aware")
    return parsed.astimezone(IST)


def _fingerprint(candidate: dict[str, Any]) -> str:
    material = {
        "mode": candidate.get("mode"),
        "direction": candidate.get("direction"),
        "entry": candidate.get("entry"),
        "stop_loss": candidate.get("stop_loss"),
        "take_profit": candidate.get("take_profit"),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_to_current(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    try:
        item["advisory"] = json.loads(item.pop("advisory_json"))
    except json.JSONDecodeError:
        item["advisory"] = None
        item.pop("advisory_json", None)
    return item


def get_current_signal(
    horizon: str,
    *,
    ticker: str = "BSE",
    db_path: str | None = None,
) -> dict[str, Any] | None:
    ensure_signal_lifecycle_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_signal_lifecycle_current WHERE ticker=? AND horizon=?",
            (ticker.strip().upper(), horizon.strip().upper()),
        ).fetchone()
    return _row_to_current(row)


def _event(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    horizon: str | None,
    trade_date: str | None,
    plan_id: str | None,
    action: str,
    direction: str | None,
    candidate_fingerprint: str | None,
    published_new_trade: bool,
    reason: str,
    evaluated_at: datetime,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO tb_signal_lifecycle_events(
            event_id, ticker, horizon, trade_date, plan_id, action, direction,
            candidate_fingerprint, published_new_trade, reason, evaluated_at,
            payload_json, trade_authorization, order_execution_allowed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """,
        (
            str(uuid.uuid4()),
            ticker,
            horizon,
            trade_date,
            plan_id,
            action,
            direction,
            candidate_fingerprint,
            int(bool(published_new_trade)),
            reason,
            evaluated_at.isoformat(),
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str),
        ),
    )


def _public(
    *,
    action: str,
    published_new_trade: bool,
    active: dict[str, Any] | None,
    reason: str,
    candidate_direction: str | None,
    pending_direction: str | None = None,
    pending_count: int = 0,
) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "action": action,
        "published_new_trade": bool(published_new_trade),
        "fixed_trade_count_limit": False,
        "analysis_can_refresh_frequently": True,
        "publication_is_event_driven": True,
        "candidate_direction": candidate_direction,
        "active_plan_id": active.get("plan_id") if active else None,
        "active_direction": active.get("direction") if active else None,
        "active_trade_date": active.get("trade_date") if active else None,
        "pending_reversal_direction": pending_direction,
        "pending_reversal_confirmations": int(pending_count),
        "reversal_confirmations_required": REVERSAL_CONFIRMATIONS_REQUIRED,
        "reason": reason,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def apply_signal_lifecycle(
    advisory: dict[str, Any],
    *,
    final_trade_decision: str,
    evaluated_at: datetime | str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Attach sticky publication state to one final live-advisory evaluation."""
    ensure_signal_lifecycle_schema(db_path)
    now = _aware(evaluated_at or advisory.get("evaluated_at_ist"))
    ticker = str(advisory.get("ticker") or "BSE").strip().upper()
    candidate = parse_agent_candidate(final_trade_decision)
    horizon = str(candidate.get("mode") or "").upper() or None
    direction = str(candidate.get("direction") or "").upper() or None
    trade_date = now.date().isoformat()
    publishable = (
        advisory.get("final_status") == PUBLISHABLE_STATUS
        and candidate.get("parse_status") == "STRUCTURED_CANDIDATE"
        and horizon in {"INTRADAY", "SWING"}
        and direction in {"LONG", "SHORT"}
    )
    fingerprint = _fingerprint(candidate) if publishable else None

    with _connect(db_path) as conn:
        row = None
        if horizon:
            row = conn.execute(
                "SELECT * FROM tb_signal_lifecycle_current WHERE ticker=? AND horizon=?",
                (ticker, horizon),
            ).fetchone()
        active = _row_to_current(row)

        # An INTRADAY plan cannot leak into another session/day. This expiration happens
        # even if today's fresh evaluation is WAIT or blocked.
        if active and horizon == "INTRADAY" and active.get("trade_date") != trade_date:
            _event(
                conn,
                ticker=ticker,
                horizon=horizon,
                trade_date=str(active.get("trade_date")),
                plan_id=str(active.get("plan_id")),
                action="SESSION_ROLLOVER_TERMINAL",
                direction=str(active.get("direction")),
                candidate_fingerprint=None,
                published_new_trade=False,
                reason="Previous INTRADAY plan expired at the trading-session date boundary.",
                evaluated_at=now,
                payload={"previous": active},
            )
            conn.execute(
                "DELETE FROM tb_signal_lifecycle_current WHERE ticker=? AND horizon=?",
                (ticker, horizon),
            )
            active = None

        if not publishable:
            reason = (
                "Fresh evaluation did not clear every final live-advisory gate. "
                "It cannot publish a new trade or silently erase an existing active plan."
            )
            lifecycle = _public(
                action="NO_NEW_PUBLISHABLE_CANDIDATE",
                published_new_trade=False,
                active=active,
                reason=reason,
                candidate_direction=direction,
                pending_direction=active.get("pending_direction") if active else None,
                pending_count=int(active.get("pending_count") or 0) if active else 0,
            )
            _event(
                conn,
                ticker=ticker,
                horizon=horizon,
                trade_date=trade_date,
                plan_id=active.get("plan_id") if active else None,
                action=lifecycle["action"],
                direction=direction,
                candidate_fingerprint=None,
                published_new_trade=False,
                reason=reason,
                evaluated_at=now,
                payload={"advisory_status": advisory.get("final_status")},
            )
            result = dict(advisory)
            result["signal_lifecycle"] = lifecycle
            return result

        assert horizon is not None and direction is not None and fingerprint is not None

        if active is None:
            plan_id = f"plan-{str(uuid.uuid4())[:12]}"
            now_iso = now.isoformat()
            conn.execute(
                """
                INSERT INTO tb_signal_lifecycle_current(
                    ticker, horizon, plan_id, trade_date, direction, state,
                    plan_fingerprint, advisory_json, pending_direction, pending_count,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
                """,
                (
                    ticker,
                    horizon,
                    plan_id,
                    trade_date,
                    direction,
                    ACTIVE_STATE,
                    fingerprint,
                    json.dumps(advisory, sort_keys=True, ensure_ascii=False, default=str),
                    now_iso,
                    now_iso,
                ),
            )
            active = {
                "plan_id": plan_id,
                "trade_date": trade_date,
                "direction": direction,
                "state": ACTIVE_STATE,
                "pending_direction": None,
                "pending_count": 0,
                "advisory": advisory,
            }
            reason = "No active plan existed for this horizon; the fully gated candidate becomes the active published plan."
            lifecycle = _public(
                action="PUBLISH_NEW",
                published_new_trade=True,
                active=active,
                reason=reason,
                candidate_direction=direction,
            )
            _event(
                conn,
                ticker=ticker,
                horizon=horizon,
                trade_date=trade_date,
                plan_id=plan_id,
                action=lifecycle["action"],
                direction=direction,
                candidate_fingerprint=fingerprint,
                published_new_trade=True,
                reason=reason,
                evaluated_at=now,
                payload={"candidate": candidate},
            )
            result = dict(advisory)
            result["signal_lifecycle"] = lifecycle
            return result

        if active.get("direction") == direction:
            conn.execute(
                """
                UPDATE tb_signal_lifecycle_current
                SET pending_direction=NULL, pending_count=0, updated_at=?
                WHERE ticker=? AND horizon=?
                """,
                (now.isoformat(), ticker, horizon),
            )
            reason = (
                "The new fully gated candidate points in the same direction as the active plan. "
                "The existing published plan remains sticky instead of creating another trade card."
            )
            lifecycle = _public(
                action="REAFFIRM_ACTIVE",
                published_new_trade=False,
                active=active,
                reason=reason,
                candidate_direction=direction,
            )
            _event(
                conn,
                ticker=ticker,
                horizon=horizon,
                trade_date=trade_date,
                plan_id=str(active.get("plan_id")),
                action=lifecycle["action"],
                direction=direction,
                candidate_fingerprint=fingerprint,
                published_new_trade=False,
                reason=reason,
                evaluated_at=now,
                payload={"candidate": candidate},
            )
            result = dict(advisory)
            result["signal_lifecycle"] = lifecycle
            result["active_published_advisory"] = active.get("advisory")
            return result

        pending_direction = str(active.get("pending_direction") or "").upper() or None
        pending_count = int(active.get("pending_count") or 0)
        if pending_direction != direction:
            pending_direction = direction
            pending_count = 1
        else:
            pending_count += 1

        if pending_count < REVERSAL_CONFIRMATIONS_REQUIRED:
            conn.execute(
                """
                UPDATE tb_signal_lifecycle_current
                SET pending_direction=?, pending_count=?, updated_at=?
                WHERE ticker=? AND horizon=?
                """,
                (pending_direction, pending_count, now.isoformat(), ticker, horizon),
            )
            reason = (
                "An opposite-direction candidate appeared, but Trade Brain suppresses one-bar/one-refresh flips. "
                "A subsequent fully gated opposite candidate is required before replacement."
            )
            lifecycle = _public(
                action="REVERSAL_PENDING_CONFIRMATION",
                published_new_trade=False,
                active=active,
                reason=reason,
                candidate_direction=direction,
                pending_direction=pending_direction,
                pending_count=pending_count,
            )
            _event(
                conn,
                ticker=ticker,
                horizon=horizon,
                trade_date=trade_date,
                plan_id=str(active.get("plan_id")),
                action=lifecycle["action"],
                direction=direction,
                candidate_fingerprint=fingerprint,
                published_new_trade=False,
                reason=reason,
                evaluated_at=now,
                payload={"candidate": candidate},
            )
            result = dict(advisory)
            result["signal_lifecycle"] = lifecycle
            result["active_published_advisory"] = active.get("advisory")
            return result

        old_plan_id = str(active.get("plan_id"))
        new_plan_id = f"plan-{str(uuid.uuid4())[:12]}"
        now_iso = now.isoformat()
        conn.execute(
            """
            UPDATE tb_signal_lifecycle_current
            SET plan_id=?, trade_date=?, direction=?, state=?, plan_fingerprint=?,
                advisory_json=?, pending_direction=NULL, pending_count=0,
                created_at=?, updated_at=?
            WHERE ticker=? AND horizon=?
            """,
            (
                new_plan_id,
                trade_date,
                direction,
                ACTIVE_STATE,
                fingerprint,
                json.dumps(advisory, sort_keys=True, ensure_ascii=False, default=str),
                now_iso,
                now_iso,
                ticker,
                horizon,
            ),
        )
        active = {
            "plan_id": new_plan_id,
            "trade_date": trade_date,
            "direction": direction,
            "state": ACTIVE_STATE,
            "pending_direction": None,
            "pending_count": 0,
            "advisory": advisory,
        }
        reason = (
            "The opposite direction cleared the full live gate on consecutive evaluations. "
            "The previous plan is replaced; this is a new event, not a refresh-induced flip."
        )
        lifecycle = _public(
            action="PUBLISH_CONFIRMED_REVERSAL",
            published_new_trade=True,
            active=active,
            reason=reason,
            candidate_direction=direction,
        )
        _event(
            conn,
            ticker=ticker,
            horizon=horizon,
            trade_date=trade_date,
            plan_id=new_plan_id,
            action=lifecycle["action"],
            direction=direction,
            candidate_fingerprint=fingerprint,
            published_new_trade=True,
            reason=reason,
            evaluated_at=now,
            payload={"candidate": candidate, "replaced_plan_id": old_plan_id},
        )
        result = dict(advisory)
        result["signal_lifecycle"] = lifecycle
        return result


def terminate_current_signal(
    horizon: str,
    *,
    reason: str,
    evaluated_at: datetime | str | None = None,
    ticker: str = "BSE",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Explicitly terminate the current advisory plan; intended for deterministic monitors."""
    ensure_signal_lifecycle_schema(db_path)
    now = _aware(evaluated_at)
    ticker = ticker.strip().upper()
    horizon = horizon.strip().upper()
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tb_signal_lifecycle_current WHERE ticker=? AND horizon=?",
            (ticker, horizon),
        ).fetchone()
        active = _row_to_current(row)
        if active is None:
            return {
                "method_version": METHOD_VERSION,
                "action": "NO_ACTIVE_PLAN",
                "terminated": False,
                "reason": reason,
                "trade_authorization": False,
                "order_execution_allowed": False,
            }
        _event(
            conn,
            ticker=ticker,
            horizon=horizon,
            trade_date=str(active.get("trade_date")),
            plan_id=str(active.get("plan_id")),
            action="TERMINATE_ACTIVE",
            direction=str(active.get("direction")),
            candidate_fingerprint=None,
            published_new_trade=False,
            reason=reason,
            evaluated_at=now,
            payload={"previous": active, "terminal_state": TERMINAL_STATE},
        )
        conn.execute(
            "DELETE FROM tb_signal_lifecycle_current WHERE ticker=? AND horizon=?",
            (ticker, horizon),
        )
    return {
        "method_version": METHOD_VERSION,
        "action": "TERMINATE_ACTIVE",
        "terminated": True,
        "plan_id": active.get("plan_id"),
        "reason": reason,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
