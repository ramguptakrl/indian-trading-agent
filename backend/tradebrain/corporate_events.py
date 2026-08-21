"""Official corporate-event ingestion for Trade Brain Phase 2.

NSE: official Corporate Announcements RSS (recent/live feed).
BSE: official AnnSubCategoryGetData announcement API (paginated).

Raw payloads are content-addressed and registered before normalization. Event
classification/importance is explicitly a rule-based research heuristic; official
source fields remain separately preserved as facts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests

from backend.tradebrain.corporate_event_store import (
    bulk_upsert_events,
    latest_raw_artifact,
)
from backend.tradebrain.provenance import provenance_record, sha256_bytes
from backend.tradebrain.store import record_raw_artifact, upsert_source

IST = ZoneInfo("Asia/Kolkata")

NSE_ANNOUNCEMENTS_RSS_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
NSE_RSS_INFO_URL = "https://www.nseindia.com/static/rss-feed"

BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ANNOUNCEMENTS_REFERER = "https://www.bseindia.com/corporates/ann.html"
BSE_ATTACHMENT_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"

NSE_SOURCE_KEY = "NSE_CORPORATE_ANNOUNCEMENTS_RSS"
BSE_SOURCE_KEY = "BSE_CORPORATE_ANNOUNCEMENTS_API"
PARSER_VERSION = "tradebrain-corporate-events-v1"
CLASSIFICATION_VERSION = "tradebrain-event-taxonomy-v1"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json,application/rss+xml,application/xml,text/xml,text/plain,*/*",
}

_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("FINANCIAL_RESULTS", ("financial result", "quarterly result", "annual result", "earnings result")),
    ("ORDER_CONTRACT", ("award of order", "receipt of order", "work order", "new order", "contract award")),
    ("M_AND_A", ("acquisition", "merger", "amalgamation", "scheme of arrangement", "slump sale", "divestment")),
    ("FUND_RAISE", ("fund raising", "fund raise", "qualified institutional", "qip", "preferential issue", "rights issue", "issue of warrants")),
    ("BUYBACK", ("buyback", "buy back")),
    ("DIVIDEND", ("dividend",)),
    ("MANAGEMENT_CHANGE", ("resignation", "appointment", "change in director", "change in directors", "change in kmp", "chief financial officer", "chief executive officer")),
    ("LITIGATION", ("litigation", "dispute", "arbitration", "show cause", "penalty", "fine imposed", "regulatory action")),
    ("CREDIT_RATING", ("credit rating", "rating revision", "rating action")),
    ("BOARD_MEETING", ("board meeting",)),
    ("INVESTOR_PRESENTATION", ("investor presentation", "analyst meet", "investor meet", "conference call", "earnings call transcript")),
    ("SHAREHOLDING", ("shareholding pattern", "shareholding", "regulation 31")),
    ("CORPORATE_ACTION", ("bonus", "stock split", "sub-division", "sub division", "record date", "book closure")),
    ("NEWSPAPER_PUBLICATION", ("newspaper publication",)),
    ("COMPLIANCE_ROUTINE", ("reg. 74 (5)", "regulation 74 (5)", "loss of certificate", "duplicate certificate", "secretarial compliance")),
]

_HIGH_CATEGORIES = {"FINANCIAL_RESULTS", "ORDER_CONTRACT", "M_AND_A", "FUND_RAISE", "LITIGATION"}
_MEDIUM_CATEGORIES = {
    "BUYBACK", "DIVIDEND", "MANAGEMENT_CHANGE", "CREDIT_RATING", "BOARD_MEETING",
    "INVESTOR_PRESENTATION", "SHAREHOLDING", "CORPORATE_ACTION",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


def _archive_raw(exchange: str, payload: bytes, extension: str) -> tuple[str, str]:
    digest = sha256_bytes(payload)
    directory = _data_root() / "raw" / "corporate_events" / exchange.lower()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{exchange.lower()}_corporate_events_{digest}.{extension}"
    if not path.exists():
        path.write_bytes(payload)
    return str(path), digest


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    return session


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _parse_timestamp(value: Any, *, assume_ist: bool = True) -> str | None:
    raw = _clean(value)
    if not raw:
        return None

    if raw.startswith("/Date(") and raw.endswith(")/"):
        try:
            ms = int(raw[6:-2].split("+")[0])
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            return None

    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST if assume_ist else timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass

    formats = (
        "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            dt = dt.replace(tzinfo=IST if assume_ist else timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def _sha_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_event_id(source_key: str, source_event_id: str | None, fingerprint_parts: list[str | None]) -> tuple[str, str]:
    fingerprint = hashlib.sha256(
        "|".join([source_key, source_event_id or "", *[(x or "") for x in fingerprint_parts]]).encode("utf-8")
    ).hexdigest()
    stable_key = source_event_id or fingerprint
    event_id = f"evt:{source_key.lower()}:{hashlib.sha256(stable_key.encode('utf-8')).hexdigest()}"
    return event_id, fingerprint


def classify_event(subject: str | None, details: str | None = None, source_category: str | None = None, *, source_critical: bool = False) -> dict[str, Any]:
    """Rule-based research classification. It is not an official exchange fact."""
    haystack = " ".join(x for x in (_clean(subject), _clean(details), _clean(source_category)) if x).lower()
    category = "GENERAL"
    for candidate, needles in _CATEGORY_RULES:
        if any(needle in haystack for needle in needles):
            category = candidate
            break

    if source_critical or category in _HIGH_CATEGORIES:
        importance = "HIGH"
    elif category in _MEDIUM_CATEGORIES:
        importance = "MEDIUM"
    else:
        importance = "LOW"

    queue = importance in {"HIGH", "MEDIUM"}
    basis = "BSE_SOURCE_CRITICAL+RULE_BASED_HEURISTIC" if source_critical else "RULE_BASED_HEURISTIC"
    return {
        "category": category,
        "importance": importance,
        "importance_basis": basis,
        "classification_version": CLASSIFICATION_VERSION,
        "queue_for_change_review": queue,
        "queue_priority": importance if queue else "LOW",
        "queue_reason": f"{category} event queued for evidence-backed 'what changed?' review" if queue else None,
    }


def _rss_child_text(item: ET.Element, name: str) -> str | None:
    for child in list(item):
        if child.tag.rsplit("}", 1)[-1].lower() == name.lower():
            return _clean(child.text)
    return None


def _split_nse_summary(summary: str | None) -> tuple[str | None, str | None]:
    if not summary:
        return None, None
    parts = re.split(r"\|\s*SUBJECT\s*:", summary, maxsplit=1, flags=re.IGNORECASE)
    headline = _clean(parts[0]) if parts else _clean(summary)
    subject = _clean(parts[1]) if len(parts) > 1 else None
    return headline, subject


def _nse_symbol_from_text_or_link(text: str | None, link: str | None) -> str | None:
    if text:
        m = re.search(r"(?:SYMBOL|SCRIP)\s*:\s*([A-Z0-9&._-]{1,30})", text, flags=re.IGNORECASE)
        if m:
            return m.group(1).upper().strip("._-") or None
    if link:
        filename = urlparse(link).path.rstrip("/").split("/")[-1]
        m = re.match(r"([A-Za-z0-9&._-]+?)(?:\d{3,}|_)", filename)
        if m:
            return m.group(1).upper().strip("._-") or None
    return None


def parse_nse_announcements_rss(payload: bytes, *, raw_artifact_id: str | None = None, received_at: str | None = None) -> tuple[list[dict], list[dict]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed NSE announcement RSS XML: {exc}") from exc

    items = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() == "item"]
    events: list[dict] = []
    rejected: list[dict] = []
    received = received_at or _utc_now().isoformat()

    for item in items:
        title = _rss_child_text(item, "title")
        link = _rss_child_text(item, "link")
        summary = _rss_child_text(item, "description") or _rss_child_text(item, "summary")
        published = _rss_child_text(item, "pubDate") or _rss_child_text(item, "published")
        guid = _rss_child_text(item, "guid")
        announced_at = _parse_timestamp(published, assume_ist=True)
        headline, subject_from_summary = _split_nse_summary(summary)
        subject = subject_from_summary or headline or title
        details = summary if summary and summary != subject else None
        symbol = _nse_symbol_from_text_or_link(summary, link)

        if not (subject or title or link):
            rejected.append({"reason": "empty_rss_item"})
            continue

        source_event_id = guid or link
        event_id, fingerprint = _stable_event_id(
            NSE_SOURCE_KEY, source_event_id, [announced_at, title, subject, link]
        )
        raw_payload = {
            "title": title, "link": link, "summary": summary, "published": published, "guid": guid,
        }
        classification = classify_event(subject, details)
        events.append(
            {
                "event_id": event_id,
                "source_key": NSE_SOURCE_KEY,
                "exchange": "NSE",
                "source_event_id": source_event_id,
                "event_fingerprint": fingerprint,
                "listing_symbol": symbol,
                "isin": None,
                "company_name": title,
                "subject": subject,
                "details": details,
                "subcategory": subject_from_summary,
                "source_category": None,
                "announced_at": announced_at,
                "source_url": NSE_ANNOUNCEMENTS_RSS_URL,
                "attachment_url": link,
                "raw_artifact_id": raw_artifact_id,
                "raw_item_sha256": _sha_json(raw_payload),
                "source_critical": False,
                "received_at": received,
                "raw_payload": raw_payload,
                **classification,
            }
        )
    return events, rejected


def _extract_bse_rows(payload: bytes) -> tuple[list[dict[str, Any]], int | None]:
    try:
        data = json.loads(payload.decode("utf-8-sig", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Malformed BSE announcement JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("BSE announcement payload is not a JSON object")
    rows = data.get("Table") or []
    if not isinstance(rows, list):
        raise ValueError("BSE announcement payload Table is not a list")
    total = None
    meta = data.get("Table1") or []
    if isinstance(meta, list) and meta and isinstance(meta[0], dict):
        try:
            total = int(meta[0].get("ROWCNT"))
        except (TypeError, ValueError):
            total = None
    return [row for row in rows if isinstance(row, dict)], total


def parse_bse_announcements(payload: bytes, *, raw_artifact_id: str | None = None, received_at: str | None = None) -> tuple[list[dict], list[dict], int | None]:
    rows, total = _extract_bse_rows(payload)
    events: list[dict] = []
    rejected: list[dict] = []
    received = received_at or _utc_now().isoformat()

    for row in rows:
        news_id = _clean(row.get("NEWSID"))
        raw_code = _clean(row.get("SCRIP_CD"))
        code = raw_code.zfill(6) if raw_code and raw_code.isdigit() else (raw_code.upper() if raw_code else None)
        subject = _clean(row.get("NEWSSUB")) or _clean(row.get("HEADLINE"))
        details = _clean(row.get("HEADLINE"))
        if details == subject:
            details = None
        announced_at = _parse_timestamp(row.get("DT_TM") or row.get("NEWS_DT") or row.get("DissemDT"), assume_ist=True)
        source_category = _clean(row.get("CATEGORYNAME") or row.get("ANNOUNCEMENT_TYPE"))
        subcategory = _clean(row.get("SUBCATNAME"))
        company = _clean(row.get("SLONGNAME"))
        source_critical = bool(row.get("CRITICALNEWS"))
        attachment_name = _clean(row.get("ATTACHMENTNAME"))
        attachment_url = f"{BSE_ATTACHMENT_BASE}{attachment_name}" if attachment_name else None

        if not (news_id or (code and subject and announced_at)):
            rejected.append({"source_event_id": news_id, "symbol": code, "reason": "missing_stable_event_identity"})
            continue

        event_id, fingerprint = _stable_event_id(
            BSE_SOURCE_KEY, news_id, [code, announced_at, subject, attachment_name]
        )
        classification = classify_event(subject, details, subcategory or source_category, source_critical=source_critical)
        events.append(
            {
                "event_id": event_id,
                "source_key": BSE_SOURCE_KEY,
                "exchange": "BSE",
                "source_event_id": news_id,
                "event_fingerprint": fingerprint,
                "listing_symbol": code,
                "isin": None,
                "company_name": company,
                "subject": subject,
                "details": details,
                "subcategory": subcategory,
                "source_category": source_category,
                "announced_at": announced_at,
                "source_url": BSE_ANNOUNCEMENTS_URL,
                "attachment_url": attachment_url,
                "raw_artifact_id": raw_artifact_id,
                "raw_item_sha256": _sha_json(row),
                "source_critical": source_critical,
                "received_at": received,
                "raw_payload": row,
                **classification,
            }
        )
    return events, rejected, total


def _register_raw(
    *, source_key: str, source_name: str, exchange: str, source_url: str,
    payload: bytes, extension: str, fetched_at: datetime, db_path: str | None,
) -> tuple[str, dict[str, Any]]:
    archive_path, digest = _archive_raw(exchange, payload, extension)
    upsert_source(
        source_key, source_name, source_type="CORPORATE_EVENTS", base_url=source_url,
        is_official=True, db_path=db_path,
    )
    artifact_id = record_raw_artifact(
        source_key=source_key, source_url=source_url, fetched_at=fetched_at.isoformat(),
        sha256=digest, raw_archive_path=archive_path, parser_version=PARSER_VERSION,
        db_path=db_path,
    )
    provenance = provenance_record(
        source=source_key, source_url=source_url, payload_sha256=digest,
        fetched_at=fetched_at, raw_archive_path=archive_path,
    )
    return artifact_id, provenance


def _fetch_nse(timeout: int) -> bytes:
    session = _session()
    try:
        response = session.get(NSE_ANNOUNCEMENTS_RSS_URL, headers={"Referer": NSE_RSS_INFO_URL}, timeout=timeout)
        response.raise_for_status()
        return response.content
    finally:
        session.close()


def collect_nse_corporate_events(*, timeout: int = 30, db_path: str | None = None) -> dict[str, Any]:
    fetched_at = _utc_now()
    payload = _fetch_nse(timeout)
    artifact_id, provenance = _register_raw(
        source_key=NSE_SOURCE_KEY, source_name="NSE Corporate Announcements RSS", exchange="NSE",
        source_url=NSE_ANNOUNCEMENTS_RSS_URL, payload=payload, extension="xml",
        fetched_at=fetched_at, db_path=db_path,
    )
    events, rejected = parse_nse_announcements_rss(
        payload, raw_artifact_id=artifact_id, received_at=fetched_at.isoformat()
    )
    if not events and rejected:
        raise ValueError("NSE announcement RSS contained no valid events; raw payload preserved")
    if not events:
        return {
            "collector": NSE_SOURCE_KEY, "transport": "NSE_OFFICIAL_RSS", "status": "SUCCESS",
            "empty_feed": True, "feed_items_received": 0, "events_rejected": 0,
            "artifact_id": artifact_id, "provenance": provenance,
        }
    stats = bulk_upsert_events(events, db_path=db_path)
    dates = [e["announced_at"] for e in events if e.get("announced_at")]
    return {
        "collector": NSE_SOURCE_KEY, "transport": "NSE_OFFICIAL_RSS", "status": "SUCCESS",
        "empty_feed": False, "feed_items_received": len(events) + len(rejected),
        "feed_min_timestamp": min(dates) if dates else None,
        "feed_max_timestamp": max(dates) if dates else None,
        "events_rejected": len(rejected), "rejected_sample": rejected[:10],
        "artifact_id": artifact_id, "provenance": provenance, **stats,
    }


def replay_latest_nse_archive(*, db_path: str | None = None) -> dict[str, Any]:
    artifact = latest_raw_artifact(NSE_SOURCE_KEY, db_path=db_path)
    if not artifact or not artifact.get("raw_archive_path"):
        raise ValueError("No archived NSE corporate-announcement RSS payload is available")
    path = Path(str(artifact["raw_archive_path"]))
    if not path.exists():
        raise FileNotFoundError(f"Archived NSE RSS payload is missing: {path}")
    payload = path.read_bytes()
    received_at = _utc_now().isoformat()
    events, rejected = parse_nse_announcements_rss(payload, raw_artifact_id=artifact["artifact_id"], received_at=received_at)
    stats = bulk_upsert_events(events, db_path=db_path) if events else {
        "events_inserted": 0, "events_updated": 0, "events_linked_to_entity": 0,
        "events_unresolved": 0, "change_queue_created": 0,
    }
    return {
        "collector": NSE_SOURCE_KEY, "transport": "NSE_OFFICIAL_RSS", "mode": "ARCHIVE_REPLAY",
        "status": "SUCCESS", "empty_feed": not bool(events),
        "feed_items_received": len(events) + len(rejected), "events_rejected": len(rejected),
        "artifact_id": artifact["artifact_id"], **stats,
    }


def _fetch_bse_page(*, page: int, from_date: date, to_date: date, timeout: int) -> bytes:
    params = {
        "pageno": page,
        "strCat": "-1",
        "subcategory": "-1",
        "strPrevDate": from_date.strftime("%Y%m%d"),
        "strToDate": to_date.strftime("%Y%m%d"),
        "strSearch": "P",
        "strscrip": "",
        "strType": "C",
    }
    session = _session()
    try:
        response = session.get(BSE_ANNOUNCEMENTS_URL, params=params, headers={"Referer": BSE_ANNOUNCEMENTS_REFERER}, timeout=timeout)
        response.raise_for_status()
        return response.content
    finally:
        session.close()


def collect_bse_corporate_events(
    *, from_date: date | None = None, to_date: date | None = None,
    max_pages: int = 100, timeout: int = 30, db_path: str | None = None,
) -> dict[str, Any]:
    today_ist = datetime.now(IST).date()
    start = from_date or today_ist
    end = to_date or start
    if start > end:
        raise ValueError("from_date cannot be after to_date")
    if (end - start).days > 31:
        raise ValueError("One BSE live collection window is limited to 31 days; use controlled backfill batches")

    all_events: list[dict] = []
    rejected: list[dict] = []
    artifact_ids: list[str] = []
    provenances: list[dict] = []
    expected_total: int | None = None
    raw_rows_seen = 0

    for page in range(1, max(1, max_pages) + 1):
        fetched_at = _utc_now()
        payload = _fetch_bse_page(page=page, from_date=start, to_date=end, timeout=timeout)
        artifact_id, provenance = _register_raw(
            source_key=BSE_SOURCE_KEY, source_name="BSE Corporate Announcements API", exchange="BSE",
            source_url=BSE_ANNOUNCEMENTS_URL, payload=payload, extension="json",
            fetched_at=fetched_at, db_path=db_path,
        )
        artifact_ids.append(artifact_id)
        provenances.append(provenance)
        events, page_rejected, total = parse_bse_announcements(
            payload, raw_artifact_id=artifact_id, received_at=fetched_at.isoformat()
        )
        rows, _ = _extract_bse_rows(payload)
        raw_rows_seen += len(rows)
        expected_total = total if total is not None else expected_total
        rejected.extend(page_rejected)
        all_events.extend(events)
        if not rows:
            break
        if expected_total is not None and raw_rows_seen >= expected_total:
            break

    if raw_rows_seen and not all_events:
        raise ValueError("BSE announcement API returned rows but zero valid normalized events; raw payloads preserved")
    stats = bulk_upsert_events(all_events, db_path=db_path) if all_events else {
        "events_inserted": 0, "events_updated": 0, "events_linked_to_entity": 0,
        "events_unresolved": 0, "change_queue_created": 0,
    }
    return {
        "collector": BSE_SOURCE_KEY, "transport": "BSE_OFFICIAL_API", "status": "SUCCESS",
        "from_date": start.isoformat(), "to_date": end.isoformat(),
        "empty_feed": not bool(all_events), "feed_items_received": raw_rows_seen,
        "events_rejected": len(rejected), "rejected_sample": rejected[:10],
        "expected_total": expected_total, "raw_artifact_ids": artifact_ids,
        "provenance": provenances, **stats,
    }


def collect_all_corporate_events(*, timeout: int = 30, db_path: str | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    try:
        results["NSE"] = collect_nse_corporate_events(timeout=timeout, db_path=db_path)
    except Exception as exc:
        errors["NSE"] = f"{type(exc).__name__}: {exc}"
    try:
        results["BSE"] = collect_bse_corporate_events(timeout=timeout, db_path=db_path)
    except Exception as exc:
        errors["BSE"] = f"{type(exc).__name__}: {exc}"
    return {
        "status": "SUCCESS" if not errors else ("PARTIAL_SUCCESS" if results else "FAILED"),
        "results": results,
        "errors": errors,
        "source_truth_rule": "Official exchange events are facts; internal category/importance is labelled heuristic",
    }
