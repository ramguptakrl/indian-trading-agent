"""Verified exchange-calendar memory for Trade Brain Phase 8.

NSE cash-market holidays are collected from the official NSE holiday-master API.
Special-session overrides are stored separately with official evidence. Unknown or
unverified dates are never silently labelled as verified exchange sessions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from backend.db import DB_PATH

IST = ZoneInfo("Asia/Kolkata")
NSE_HOLIDAY_API = "https://www.nseindia.com/api/holiday-master?type=trading"
NSE_HOLIDAY_PAGE = "https://www.nseindia.com/resources/exchange-communication-holidays"
PARSER_VERSION = "tradebrain-exchange-calendar-v1"
REGULAR_OPEN = time(9, 15)
REGULAR_CLOSE = time(15, 30)


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


def ensure_exchange_calendar_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_exchange_calendar_sources (
                source_key TEXT PRIMARY KEY,
                exchange TEXT NOT NULL,
                segment TEXT NOT NULL,
                source_url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                is_official INTEGER NOT NULL,
                covered_years_json TEXT NOT NULL,
                raw_archive_path TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tb_exchange_calendar_days (
                exchange TEXT NOT NULL,
                segment TEXT NOT NULL,
                session_date TEXT NOT NULL,
                session_type TEXT NOT NULL,
                open_time TEXT,
                close_time TEXT,
                description TEXT,
                source_key TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                timing_verified INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(exchange, segment, session_date),
                FOREIGN KEY(source_key) REFERENCES tb_exchange_calendar_sources(source_key)
            );

            CREATE INDEX IF NOT EXISTS idx_tb_calendar_days_date
                ON tb_exchange_calendar_days(session_date, exchange, segment);
            """
        )


def _archive_root() -> Path:
    root = os.getenv("TRADEBRAIN_DATA_DIR")
    if root:
        return Path(root)
    return Path.home() / ".tradingagents" / "tradebrain"


def _archive_payload(raw: bytes, *, exchange: str) -> tuple[str, str]:
    digest = hashlib.sha256(raw).hexdigest()
    folder = _archive_root() / "raw" / "exchange_calendar" / exchange.lower()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{exchange.lower()}_calendar_{digest}.json"
    if not path.exists():
        path.write_bytes(raw)
    return digest, str(path)


def _parse_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%d-%b-%Y").date()


def parse_nse_cash_holidays(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("CM")
    if not isinstance(rows, list):
        raise ValueError("NSE holiday payload is missing the CM cash-market list")
    output: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("tradingDate"):
            continue
        day = _parse_date(str(row["tradingDate"]))
        description = str(row.get("description") or "Trading holiday").strip()
        special_pending = bool(re.search(r"diwali\s+laxmi\s+pujan|muhurat", description, re.I))
        output.append(
            {
                "session_date": day.isoformat(),
                "session_type": "SPECIAL_PENDING" if special_pending else "CLOSED",
                "open_time": None,
                "close_time": None,
                "description": description,
                "timing_verified": not special_pending,
            }
        )
    if not output:
        raise ValueError("NSE cash-market holiday payload contained zero usable rows")
    return output


def ingest_nse_cash_holiday_payload(
    payload: dict[str, Any],
    *,
    raw_bytes: bytes | None = None,
    fetched_at: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    rows = parse_nse_cash_holidays(payload)
    raw = raw_bytes or json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sha256, archive_path = _archive_payload(raw, exchange="NSE")
    fetched = fetched_at or datetime.now(timezone.utc).isoformat()
    years = sorted({int(row["session_date"][:4]) for row in rows})
    source_key = "NSE_OFFICIAL_TRADING_HOLIDAY_MASTER_CM"
    ensure_exchange_calendar_schema(db_path)
    with _connect(db_path) as conn:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO tb_exchange_calendar_sources(
                source_key, exchange, segment, source_url, fetched_at, sha256,
                parser_version, is_official, covered_years_json, raw_archive_path, updated_at
            ) VALUES (?, 'NSE', 'CM', ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                source_url=excluded.source_url, fetched_at=excluded.fetched_at,
                sha256=excluded.sha256, parser_version=excluded.parser_version,
                is_official=1, covered_years_json=excluded.covered_years_json,
                raw_archive_path=excluded.raw_archive_path, updated_at=excluded.updated_at
            """,
            (
                source_key, NSE_HOLIDAY_API, fetched, sha256, PARSER_VERSION,
                json.dumps(years), archive_path, now,
            ),
        )
        for row in rows:
            conn.execute(
                """
                INSERT INTO tb_exchange_calendar_days(
                    exchange, segment, session_date, session_type, open_time, close_time,
                    description, source_key, source_url, source_sha256, timing_verified, updated_at
                ) VALUES ('NSE','CM',?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(exchange, segment, session_date) DO UPDATE SET
                    session_type=excluded.session_type, open_time=excluded.open_time,
                    close_time=excluded.close_time, description=excluded.description,
                    source_key=excluded.source_key, source_url=excluded.source_url,
                    source_sha256=excluded.source_sha256,
                    timing_verified=excluded.timing_verified, updated_at=excluded.updated_at
                """,
                (
                    row["session_date"], row["session_type"], row["open_time"], row["close_time"],
                    row["description"], source_key, NSE_HOLIDAY_API, sha256,
                    int(row["timing_verified"]), now,
                ),
            )
    return {
        "status": "SUCCESS",
        "exchange": "NSE",
        "segment": "CM",
        "rows": len(rows),
        "covered_years": years,
        "source_url": NSE_HOLIDAY_API,
        "source_official": True,
        "sha256": sha256,
        "raw_archive_path": archive_path,
        "special_sessions_pending_times": sum(row["session_type"] == "SPECIAL_PENDING" for row in rows),
    }


def collect_nse_cash_calendar(*, db_path: str | None = None, timeout: float = 20.0) -> dict[str, Any]:
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (TradeBrain calendar collector; +https://www.nseindia.com)",
        "Accept": "application/json,text/plain,*/*",
        "Referer": NSE_HOLIDAY_PAGE,
    }
    # NSE may require cookies from the public page before API access.
    session.get(NSE_HOLIDAY_PAGE, headers=headers, timeout=timeout)
    response = session.get(NSE_HOLIDAY_API, headers=headers, timeout=timeout)
    response.raise_for_status()
    raw = response.content
    try:
        payload = response.json()
    except ValueError as exc:
        _archive_payload(raw, exchange="NSE")
        raise ValueError("NSE holiday endpoint did not return valid JSON") from exc
    return ingest_nse_cash_holiday_payload(
        payload, raw_bytes=raw, fetched_at=datetime.now(timezone.utc).isoformat(), db_path=db_path
    )


def _official_calendar_host(url: str, exchange: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    allowed = "nseindia.com" if exchange == "NSE" else "bseindia.com"
    return host == allowed or host.endswith("." + allowed)


def upsert_verified_session_override(
    *,
    exchange: str,
    session_date: str,
    session_type: str,
    source_url: str,
    description: str,
    open_time: str | None = None,
    close_time: str | None = None,
    source_sha256: str,
    segment: str = "CM",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Store a human-reviewed official special/exception session notice.

    This is intentionally not a generic manual calendar edit: the evidence URL must
    belong to the relevant exchange's official domain and the evidence hash is required.
    """

    ex = exchange.strip().upper()
    kind = session_type.strip().upper()
    if ex not in {"NSE", "BSE"}:
        raise ValueError("exchange must be NSE or BSE")
    if kind not in {"CLOSED", "SPECIAL_OPEN"}:
        raise ValueError("session_type must be CLOSED or SPECIAL_OPEN")
    day = date.fromisoformat(session_date).isoformat()
    if not source_url.startswith("https://") or not _official_calendar_host(source_url, ex):
        raise ValueError("Verified session override requires an HTTPS official exchange source URL")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", source_sha256 or ""):
        raise ValueError("source_sha256 must be a full SHA-256 hex digest")
    if kind == "SPECIAL_OPEN":
        if not open_time or not close_time:
            raise ValueError("SPECIAL_OPEN requires verified open_time and close_time")
        time.fromisoformat(open_time)
        time.fromisoformat(close_time)
    else:
        open_time = close_time = None

    source_key = f"{ex}_VERIFIED_SESSION_OVERRIDE_{day}"
    ensure_exchange_calendar_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_exchange_calendar_sources(
                source_key, exchange, segment, source_url, fetched_at, sha256,
                parser_version, is_official, covered_years_json, raw_archive_path, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, NULL, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                source_url=excluded.source_url, fetched_at=excluded.fetched_at,
                sha256=excluded.sha256, parser_version=excluded.parser_version,
                is_official=1, covered_years_json=excluded.covered_years_json,
                updated_at=excluded.updated_at
            """,
            (
                source_key, ex, segment, source_url, now, source_sha256.lower(),
                PARSER_VERSION, json.dumps([int(day[:4])]), now,
            ),
        )
        conn.execute(
            """
            INSERT INTO tb_exchange_calendar_days(
                exchange, segment, session_date, session_type, open_time, close_time,
                description, source_key, source_url, source_sha256, timing_verified, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)
            ON CONFLICT(exchange, segment, session_date) DO UPDATE SET
                session_type=excluded.session_type, open_time=excluded.open_time,
                close_time=excluded.close_time, description=excluded.description,
                source_key=excluded.source_key, source_url=excluded.source_url,
                source_sha256=excluded.source_sha256, timing_verified=1,
                updated_at=excluded.updated_at
            """,
            (
                ex, segment, day, kind, open_time, close_time, description,
                source_key, source_url, source_sha256.lower(), now,
            ),
        )
    return session_for_date(day, exchange=ex, segment=segment, db_path=db_path)


def _source_coverage(exchange: str, segment: str, *, db_path: str | None = None) -> set[int]:
    ensure_exchange_calendar_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT covered_years_json FROM tb_exchange_calendar_sources
               WHERE exchange=? AND segment=? AND is_official=1""",
            (exchange, segment),
        ).fetchall()
    years: set[int] = set()
    for row in rows:
        try:
            years.update(int(x) for x in json.loads(row["covered_years_json"] or "[]"))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    return years


def session_for_date(
    value: str | date | datetime,
    *,
    exchange: str = "NSE",
    segment: str = "CM",
    db_path: str | None = None,
) -> dict[str, Any]:
    ex = exchange.strip().upper()
    if isinstance(value, datetime):
        day = value.astimezone(IST).date() if value.tzinfo else value.date()
    elif isinstance(value, date):
        day = value
    else:
        day = date.fromisoformat(value)
    ensure_exchange_calendar_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM tb_exchange_calendar_days
               WHERE exchange=? AND segment=? AND session_date=?""",
            (ex, segment, day.isoformat()),
        ).fetchone()
    if row:
        item = dict(row)
        item["calendar_verified"] = True
        item["timing_verified"] = bool(item["timing_verified"])
        item["is_trading_session"] = item["session_type"] == "SPECIAL_OPEN"
        item["safe_to_open_new_intraday"] = item["session_type"] == "SPECIAL_OPEN" and item["timing_verified"]
        if item["session_type"] == "CLOSED":
            item["reason"] = "OFFICIAL_EXCHANGE_CLOSURE"
        elif item["session_type"] == "SPECIAL_PENDING":
            item["reason"] = "SPECIAL_SESSION_TIMES_NOT_VERIFIED"
        else:
            item["reason"] = "VERIFIED_SPECIAL_SESSION"
        return item

    covered = day.year in _source_coverage(ex, segment, db_path=db_path)
    weekday = day.weekday() < 5
    if covered:
        return {
            "exchange": ex,
            "segment": segment,
            "session_date": day.isoformat(),
            "session_type": "REGULAR" if weekday else "WEEKEND_CLOSED",
            "open_time": REGULAR_OPEN.isoformat(timespec="minutes") if weekday else None,
            "close_time": REGULAR_CLOSE.isoformat(timespec="minutes") if weekday else None,
            "description": "Regular session inferred from verified annual holiday coverage" if weekday else "Weekend",
            "calendar_verified": True,
            "timing_verified": True,
            "is_trading_session": weekday,
            "safe_to_open_new_intraday": weekday,
            "reason": "VERIFIED_ANNUAL_CALENDAR_REGULAR_DAY" if weekday else "WEEKEND_CLOSED",
        }

    return {
        "exchange": ex,
        "segment": segment,
        "session_date": day.isoformat(),
        "session_type": "UNKNOWN",
        "open_time": None,
        "close_time": None,
        "description": "No verified official calendar coverage for this exchange/year",
        "calendar_verified": False,
        "timing_verified": False,
        "is_trading_session": False,
        "safe_to_open_new_intraday": False,
        "reason": "CALENDAR_UNVERIFIED",
    }


def calendar_stats(*, db_path: str | None = None) -> dict[str, Any]:
    ensure_exchange_calendar_schema(db_path)
    with _connect(db_path) as conn:
        sources = conn.execute("SELECT COUNT(*) FROM tb_exchange_calendar_sources").fetchone()[0]
        days = conn.execute("SELECT COUNT(*) FROM tb_exchange_calendar_days").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM tb_exchange_calendar_days WHERE session_type='SPECIAL_PENDING'"
        ).fetchone()[0]
    return {
        "official_sources": int(sources),
        "explicit_calendar_days": int(days),
        "special_sessions_pending_verified_times": int(pending),
        "nse_official_api": NSE_HOLIDAY_API,
    }
