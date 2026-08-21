"""Official NSE/BSE equity security-master ingestion for Trade Brain.

Principles:
- archive raw payload before normalization
- hash every payload and register provenance
- accept cross-exchange identity only from a valid ISIN
- idempotent listing/security upserts
- absence from a fresh source never proves delisting
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.provenance import provenance_record, sha256_bytes
from backend.tradebrain.security_store import bulk_upsert_listings
from backend.tradebrain.store import record_raw_artifact, upsert_source

NSE_EQUITY_MASTER_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_REFERER = "https://www.nseindia.com/market-data/securities-available-for-trading"

BSE_SCRIP_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
BSE_REFERER = "https://www.bseindia.com/corporates/List_Scrips.html"
BSE_PARAMS = {
    "Group": "",
    "Scripcode": "",
    "industry": "",
    "segment": "Equity",
    "status": "Active",
}

PARSER_VERSION = "tradebrain-security-master-v1"
_ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/csv,application/json,text/plain,*/*",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


def _archive_raw(exchange: str, payload: bytes, extension: str) -> tuple[str, str]:
    """Archive by content hash so the same exact payload is stored only once."""
    digest = sha256_bytes(payload)
    directory = _data_root() / "raw" / "security_master" / exchange.lower()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{exchange.lower()}_security_master_{digest}.{extension}"
    if not path.exists():
        path.write_bytes(payload)
    return str(path), digest


def _valid_isin(value: Any) -> str | None:
    if value is None:
        return None
    isin = str(value).strip().upper()
    return isin if _ISIN_RE.fullmatch(isin) else None


def _norm_row(row: dict[str, Any]) -> dict[str, Any]:
    """Strip source headers/values while retaining original case-sensitive keys."""
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        k = str(key).strip()
        cleaned[k] = value.strip() if isinstance(value, str) else value
    return cleaned


def _ci_get(row: dict[str, Any], *names: str) -> Any:
    index = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        key = name.strip().lower()
        if key in index:
            return index[key]
    return None


def parse_nse_equity_master(payload: bytes) -> tuple[list[dict], list[dict]]:
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = {str(name).strip().lower() for name in (reader.fieldnames or [])}
    if "symbol" not in headers or not ({"isin number", "isin"} & headers):
        raise ValueError("NSE security-master payload is missing required SYMBOL/ISIN headers")

    valid: list[dict] = []
    rejected: list[dict] = []

    for raw in reader:
        row = _norm_row(raw)
        symbol = str(_ci_get(row, "SYMBOL") or "").strip().upper()
        isin = _valid_isin(_ci_get(row, "ISIN NUMBER", "ISIN"))
        name = str(_ci_get(row, "NAME OF COMPANY", "COMPANY NAME") or "").strip()
        if not symbol or not isin:
            rejected.append({"symbol": symbol or None, "isin": _ci_get(row, "ISIN NUMBER", "ISIN"), "reason": "missing_or_invalid_identity"})
            continue

        valid.append(
            {
                "listing": ExchangeListing(exchange="NSE", symbol=symbol, isin=isin),
                "listing_name": name or symbol,
                "security_name": name or symbol,
                "listing_status": "ACTIVE",
                "exchange_security_id": None,
                "series": str(_ci_get(row, "SERIES") or "").strip() or None,
                "group_name": None,
                "industry": str(_ci_get(row, "INDUSTRY") or "").strip() or None,
                "metadata": {
                    "date_of_listing": _ci_get(row, "DATE OF LISTING"),
                    "paid_up_value": _ci_get(row, "PAID UP VALUE"),
                    "market_lot": _ci_get(row, "MARKET LOT"),
                    "face_value": _ci_get(row, "FACE VALUE"),
                },
            }
        )
    return valid, rejected


def _extract_bse_rows(payload: bytes) -> list[dict[str, Any]]:
    data = json.loads(payload.decode("utf-8-sig", errors="replace"))
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("Table", "Table1", "Data", "data", "results", "Result"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        for value in data.values():
            if isinstance(value, list) and (not value or isinstance(value[0], dict)):
                return [x for x in value if isinstance(x, dict)]
    raise ValueError("Unsupported BSE security-master JSON shape")


def parse_bse_equity_master(payload: bytes) -> tuple[list[dict], list[dict]]:
    rows = _extract_bse_rows(payload)
    valid: list[dict] = []
    rejected: list[dict] = []

    for raw in rows:
        row = _norm_row(raw)
        code_raw = _ci_get(row, "SCRIP_CD", "Scrip Code", "SCRIP_CODE")
        code = str(code_raw or "").strip()
        code = code.zfill(6) if code.isdigit() else code.upper()
        isin = _valid_isin(_ci_get(row, "ISIN_NUMBER", "ISIN CODE", "ISIN", "ISIN_CODE"))
        scrip_id = str(_ci_get(row, "scrip_id", "Instrument Code", "SCRIP_ID") or "").strip().upper()
        name = str(_ci_get(row, "Scrip_Name", "Scrip Name", "SCRIP_NAME") or "").strip()

        if not code or not isin:
            rejected.append({"symbol": code or None, "isin": _ci_get(row, "ISIN_NUMBER", "ISIN CODE", "ISIN"), "reason": "missing_or_invalid_identity"})
            continue

        valid.append(
            {
                "listing": ExchangeListing(exchange="BSE", symbol=code, isin=isin),
                "listing_name": name or scrip_id or code,
                "security_name": name or scrip_id or code,
                "listing_status": "ACTIVE",
                "exchange_security_id": scrip_id or None,
                "series": str(_ci_get(row, "Security Type Flag", "SECURITY_TYPE", "SERIES") or "").strip() or None,
                "group_name": str(_ci_get(row, "GROUP", "Group Name", "GROUP_NAME") or "").strip() or None,
                "industry": str(_ci_get(row, "INDUSTRY", "Industry") or "").strip() or None,
                "metadata": {
                    "scrip_id": scrip_id or None,
                    "market_lot": _ci_get(row, "Market Lot", "MARKET_LOT"),
                    "face_value": _ci_get(row, "Face Value", "FACE_VALUE"),
                },
            }
        )
    return valid, rejected


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    return session


def _fetch_nse(timeout: int = 30) -> bytes:
    session = _session()
    try:
        # Cookie bootstrap is best-effort; the archive URL can also work directly.
        try:
            session.get("https://www.nseindia.com", timeout=timeout)
        except requests.RequestException:
            pass
        response = session.get(NSE_EQUITY_MASTER_URL, headers={"Referer": NSE_REFERER}, timeout=timeout)
        response.raise_for_status()
        return response.content
    finally:
        session.close()


def _fetch_bse(timeout: int = 30) -> bytes:
    session = _session()
    try:
        response = session.get(BSE_SCRIP_LIST_URL, params=BSE_PARAMS, headers={"Referer": BSE_REFERER}, timeout=timeout)
        response.raise_for_status()
        # Preserve the exact response bytes for hashing and replay.
        return response.content
    finally:
        session.close()


def _collect(
    *,
    exchange: str,
    source_key: str,
    source_name: str,
    source_url: str,
    parser,
    fetcher,
    extension: str,
    timeout: int,
    db_path: str | None = None,
) -> dict:
    fetched_at = _utc_now()
    payload = fetcher(timeout=timeout)
    archive_path, digest = _archive_raw(exchange, payload, extension)

    upsert_source(
        source_key,
        source_name,
        source_type="SECURITY_MASTER",
        base_url=source_url,
        is_official=True,
        db_path=db_path,
    )
    artifact_id = record_raw_artifact(
        source_key=source_key,
        source_url=source_url,
        fetched_at=fetched_at.isoformat(),
        sha256=digest,
        raw_archive_path=archive_path,
        parser_version=PARSER_VERSION,
        db_path=db_path,
    )

    rows, rejected = parser(payload)
    if not rows:
        raise ValueError(
            f"{exchange} security-master parsed zero valid rows; raw payload was archived but identity store was not modified"
        )

    write_stats = bulk_upsert_listings(
        rows,
        source_key=source_key,
        source_timestamp=fetched_at.isoformat(),
        db_path=db_path,
    )

    return {
        "collector": source_key,
        "exchange": exchange,
        "status": "SUCCESS",
        "rows_received": len(rows) + len(rejected),
        "rows_valid": len(rows),
        "rows_rejected": len(rejected),
        **write_stats,
        "rejected_sample": rejected[:10],
        "artifact_id": artifact_id,
        "provenance": provenance_record(
            source=source_key,
            source_url=source_url,
            payload_sha256=digest,
            fetched_at=fetched_at,
            raw_archive_path=archive_path,
        ),
        "identity_rule": "Cross-exchange merge only by matching valid ISIN",
        "absence_rule": "A listing missing from this refresh is NOT automatically marked delisted",
    }


def collect_nse_security_master(*, timeout: int = 30, db_path: str | None = None) -> dict:
    return _collect(
        exchange="NSE",
        source_key="NSE_EQUITY_SECURITY_MASTER",
        source_name="NSE Securities available for Equity segment",
        source_url=NSE_EQUITY_MASTER_URL,
        parser=parse_nse_equity_master,
        fetcher=_fetch_nse,
        extension="csv",
        timeout=timeout,
        db_path=db_path,
    )


def collect_bse_security_master(*, timeout: int = 30, db_path: str | None = None) -> dict:
    return _collect(
        exchange="BSE",
        source_key="BSE_EQUITY_SECURITY_MASTER",
        source_name="BSE Active Equity Scrip List",
        source_url=BSE_SCRIP_LIST_URL,
        parser=parse_bse_equity_master,
        fetcher=_fetch_bse,
        extension="json",
        timeout=timeout,
        db_path=db_path,
    )


def collect_all_security_masters(*, timeout: int = 30, db_path: str | None = None) -> dict:
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for exchange, collector in (("NSE", collect_nse_security_master), ("BSE", collect_bse_security_master)):
        try:
            results[exchange] = collector(timeout=timeout, db_path=db_path)
        except Exception as exc:
            errors[exchange] = f"{type(exc).__name__}: {exc}"
    return {
        "status": "SUCCESS" if not errors else ("PARTIAL_SUCCESS" if results else "FAILED"),
        "results": results,
        "errors": errors,
    }
