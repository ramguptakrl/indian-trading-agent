"""Authoritative raw-price era boundaries from explicit official BSE split events."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.corporate_actions import normalize_corporate_action
from backend.tradebrain.corporate_event_store import list_events
from backend.tradebrain.market_data_store import _connect, ensure_market_data_schema, get_series

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SOURCE_KEY = "OFFICIAL_BSE_CORPORATE_EVENT_MEMORY"
BOUNDARY_SOURCE = "OFFICIAL_BSE_SPLIT_EVENT"
METHOD_VERSION = "OFFICIAL_BSE_SPLIT_PRICE_ERAS_V1"


def _utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _session_open_utc(day: str) -> str:
    parsed = datetime.fromisoformat(day).date()
    return datetime.combine(parsed, SESSION_OPEN, tzinfo=IST).astimezone(timezone.utc).isoformat()


def _official_split_boundaries(*, known_by: str | datetime | None, db_path: str | None) -> list[dict[str, Any]]:
    cutoff = _utc(known_by)
    boundaries: dict[str, dict[str, Any]] = {}
    # Inbox status is workflow metadata only. Split truth remains part of permanent memory.
    for event in list_events(status=None, limit=500, db_path=db_path):
        action = normalize_corporate_action(event)
        if not action or action.get("action_type") != "STOCK_SPLIT" or not action.get("ex_date"):
            continue
        first_known = _utc(action.get("first_known_at"))
        if cutoff is not None and (first_known is None or first_known > cutoff):
            continue
        effective_at = _session_open_utc(str(action["ex_date"]))
        candidate = {
            "effective_at": effective_at,
            "event_id": action.get("event_id"),
            "ex_date": action.get("ex_date"),
            "adjustment_factor": action.get("raw_price_adjustment_factor"),
            "share_multiplier": action.get("share_multiplier"),
            "ratio_basis": action.get("ratio_basis"),
            "first_known_at": action.get("first_known_at"),
            "verification_status": (
                "OFFICIAL_EVENT_EXPLICIT_EX_DATE_AND_RATIO"
                if action.get("raw_price_adjustment_factor") is not None
                else "OFFICIAL_EVENT_EXPLICIT_EX_DATE_RATIO_UNRESOLVED"
            ),
        }
        existing = boundaries.get(effective_at)
        if existing is None or (existing.get("adjustment_factor") is None and candidate.get("adjustment_factor") is not None):
            boundaries[effective_at] = candidate
    return [boundaries[key] for key in sorted(boundaries)]


def sync_official_bse_split_price_eras(
    series_id: str,
    *,
    known_by: str | datetime | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Build official split eras and assign them to all stored intervals for one BSE series.

    This never adjusts OHLC values. It only creates comparability barriers. Dividends are
    intentionally excluded because they are mechanical ex-date context, not a share-count
    / raw-price-scale structural break.
    """
    ensure_market_data_schema(db_path)
    series = get_series(series_id, db_path=db_path)
    if series is None:
        raise ValueError(f"Unknown market series: {series_id}")
    if str(series.get("symbol") or "").upper() != "BSE" or str(series.get("exchange") or "").upper() != "NSE":
        raise ValueError("Official BSE split eras apply only to the NSE:BSE Trade Brain series")

    boundaries = _official_split_boundaries(known_by=known_by, db_path=db_path)
    if not boundaries:
        return {
            "method_version": METHOD_VERSION,
            "series_id": series_id,
            "status": "NO_KNOWN_OFFICIAL_SPLIT_BOUNDARY",
            "split_boundaries": 0,
            "bars_reassigned": 0,
            "dividends_create_price_era": False,
        }

    starts: list[str | None] = [None] + [item["effective_at"] for item in boundaries]
    ends: list[str | None] = [item["effective_at"] for item in boundaries] + [None]
    assigned = 0

    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM tb_price_eras WHERE series_id=? AND boundary_source=?",
            (series_id, BOUNDARY_SOURCE),
        )

        for boundary in boundaries:
            aid = "action:" + hashlib.sha256(
                f"{series_id}|SPLIT|{boundary['effective_at']}|{SOURCE_KEY}".encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT INTO tb_market_corporate_actions(
                    action_id, series_id, action_type, effective_at, value, source_key,
                    verification_status, source_metadata_json
                ) VALUES (?, ?, 'SPLIT', ?, ?, ?, ?, ?)
                ON CONFLICT(series_id, action_type, effective_at, source_key) DO UPDATE SET
                    value=excluded.value,
                    verification_status=excluded.verification_status,
                    source_metadata_json=excluded.source_metadata_json
                """,
                (
                    aid,
                    series_id,
                    boundary["effective_at"],
                    boundary.get("adjustment_factor"),
                    SOURCE_KEY,
                    boundary["verification_status"],
                    json.dumps(boundary, sort_keys=True, ensure_ascii=False, default=str),
                ),
            )

        eras: list[dict[str, Any]] = []
        for idx, (start, end) in enumerate(zip(starts, ends)):
            boundary = boundaries[idx - 1] if idx > 0 else None
            era_id = "era:" + hashlib.sha256(
                f"{series_id}|official-bse-split|{start}|{end}".encode("utf-8")
            ).hexdigest()
            verification = boundary["verification_status"] if boundary else "DERIVED_FROM_OFFICIAL_SPLIT_BOUNDARIES"
            conn.execute(
                """
                INSERT INTO tb_price_eras(
                    era_id, series_id, starts_at, ends_at, boundary_reason,
                    boundary_source, verification_status, adjustment_factor, source_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    era_id,
                    series_id,
                    start,
                    end,
                    "RAW_PRICE_COMPARABILITY_BOUNDARY" if boundary else "INITIAL_RAW_PRICE_ERA",
                    BOUNDARY_SOURCE,
                    verification,
                    boundary.get("adjustment_factor") if boundary else None,
                    boundary.get("event_id") if boundary else None,
                ),
            )
            eras.append({"era_id": era_id, "starts_at": start, "ends_at": end})

        for era in eras:
            clauses = ["series_id=?"]
            args: list[Any] = [series_id]
            if era["starts_at"]:
                clauses.append("ts_open>=?")
                args.append(era["starts_at"])
            if era["ends_at"]:
                clauses.append("ts_open<?")
                args.append(era["ends_at"])
            cur = conn.execute(
                f"UPDATE tb_ohlcv_bars SET era_id=? WHERE {' AND '.join(clauses)}",
                [era["era_id"], *args],
            )
            assigned += int(cur.rowcount or 0)

    return {
        "method_version": METHOD_VERSION,
        "series_id": series_id,
        "status": "OFFICIAL_SPLIT_ERAS_SYNCHRONIZED",
        "split_boundaries": len(boundaries),
        "eras_created": len(boundaries) + 1,
        "bars_reassigned": assigned,
        "boundary_source": BOUNDARY_SOURCE,
        "dividends_create_price_era": False,
        "raw_prices_adjusted": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
