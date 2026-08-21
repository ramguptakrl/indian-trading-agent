"""Official filing/document ingestion for Trade Brain Phase 2.

Security boundary:
- attachment URL must already belong to a stored corporate event;
- only HTTPS NSE/BSE-owned hosts are allowed;
- redirects are revalidated;
- downloads are size capped;
- persistence is content-addressed by SHA-256.

Text extraction is local and deterministic. PDF extraction uses embedded text only;
OCR is deliberately out of scope here so scanned PDFs remain explicitly unparsed.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests

from backend.tradebrain.corporate_event_store import (
    get_document,
    get_event_attachment,
    link_event_document,
    list_events,
    upsert_document,
)

DEFAULT_MAX_BYTES = 25 * 1024 * 1024
_ALLOWED_ROOT_DOMAINS = ("nseindia.com", "bseindia.com")

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/html,application/xml,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppressed = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() in {"script", "style", "noscript"}:
            self._suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._suppressed:
            self._suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self._suppressed:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)

    def text(self) -> str:
        return "\n".join(self.parts)


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


def _allowed_official_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() != "https":
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return any(host == root or host.endswith("." + root) for root in _ALLOWED_ROOT_DOMAINS)


def _guess_url_extension(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix if re.fullmatch(r"[a-z0-9]{1,8}", suffix or "") else ""


def _detect_document_type(payload: bytes, mime_type: str | None, source_url: str) -> tuple[str, str]:
    head = payload[:4096].lstrip()
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    url_ext = _guess_url_extension(source_url)

    if payload.startswith(b"%PDF-"):
        return "PDF", "pdf"

    if payload.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                if "word/document.xml" in archive.namelist():
                    return "DOCX", "docx"
        except zipfile.BadZipFile:
            pass

    lowered = head[:512].lower()
    if mime == "text/html" or lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html"):
        return "HTML", "html"
    if mime in {"application/xml", "text/xml"} or lowered.startswith(b"<?xml"):
        return "XML", "xml"
    if mime == "application/json" or lowered.startswith((b"{", b"[")):
        try:
            json.loads(payload.decode("utf-8-sig"))
            return "JSON", "json"
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    if mime.startswith("text/") or url_ext in {"txt", "csv"}:
        return "TEXT", url_ext or "txt"

    return "BINARY", url_ext or "bin"


def _normalize_extracted_text(text: str) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        value = " ".join(line.split())
        if value:
            lines.append(value)
    return "\n".join(lines).strip()


def _extract_pdf(payload: bytes) -> tuple[str | None, int | None, str, dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, None, "DEPENDENCY_MISSING", {"reason": "pypdf is not installed"}

    try:
        reader = PdfReader(io.BytesIO(payload))
        pages: list[str] = []
        for page in reader.pages:
            value = page.extract_text() or ""
            if value.strip():
                pages.append(value)
        text = _normalize_extracted_text("\n\n".join(pages))
        if not text:
            return None, len(reader.pages), "NO_EMBEDDED_TEXT", {
                "reason": "PDF has no extractable embedded text; OCR was not attempted"
            }
        return text, len(reader.pages), "TEXT_EXTRACTED", {}
    except Exception as exc:
        return None, None, "PARSE_ERROR", {"reason": f"{type(exc).__name__}: {exc}"}


def _extract_docx(payload: bytes) -> tuple[str | None, int | None, str, dict[str, Any]]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            xml_payload = archive.read("word/document.xml")
        root = ET.fromstring(xml_payload)
        values = []
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == "t" and node.text:
                values.append(node.text)
        text = _normalize_extracted_text("\n".join(values))
        return (text or None), None, ("TEXT_EXTRACTED" if text else "NO_EMBEDDED_TEXT"), {}
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return None, None, "PARSE_ERROR", {"reason": f"{type(exc).__name__}: {exc}"}


def _extract_structured_text(payload: bytes, doc_type: str) -> tuple[str | None, int | None, str, dict[str, Any]]:
    try:
        text = payload.decode("utf-8-sig", errors="replace")
        if doc_type == "HTML":
            parser = _HTMLTextExtractor()
            parser.feed(text)
            value = parser.text()
        elif doc_type == "XML":
            root = ET.fromstring(text)
            value = "\n".join(v.strip() for v in root.itertext() if v and v.strip())
        elif doc_type == "JSON":
            value = json.dumps(json.loads(text), ensure_ascii=False, indent=2, sort_keys=True)
        else:
            value = text
        value = _normalize_extracted_text(value)
        return (value or None), None, ("TEXT_EXTRACTED" if value else "NO_EMBEDDED_TEXT"), {}
    except Exception as exc:
        return None, None, "PARSE_ERROR", {"reason": f"{type(exc).__name__}: {exc}"}


def extract_document_text(payload: bytes, doc_type: str) -> tuple[str | None, int | None, str, dict[str, Any]]:
    if doc_type == "PDF":
        return _extract_pdf(payload)
    if doc_type == "DOCX":
        return _extract_docx(payload)
    if doc_type in {"HTML", "XML", "JSON", "TEXT"}:
        return _extract_structured_text(payload, doc_type)
    return None, None, "UNSUPPORTED", {"reason": f"No local extractor for {doc_type}"}


def _download(url: str, *, timeout: int, max_bytes: int) -> tuple[bytes, str | None, str]:
    if not _allowed_official_url(url):
        raise ValueError("Attachment URL is not an approved HTTPS NSE/BSE-owned host")

    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    try:
        with session.get(url, stream=True, allow_redirects=True, timeout=timeout) as response:
            response.raise_for_status()
            final_url = str(response.url)
            if not _allowed_official_url(final_url):
                raise ValueError("Attachment redirect left the approved NSE/BSE host boundary")

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ValueError(f"Attachment exceeds size limit ({max_bytes} bytes)")
                except ValueError as exc:
                    if "exceeds size limit" in str(exc):
                        raise

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Attachment exceeds size limit ({max_bytes} bytes)")
                chunks.append(chunk)
            payload = b"".join(chunks)
            if not payload:
                raise ValueError("Attachment response was empty")
            mime_type = response.headers.get("Content-Type")
            return payload, mime_type, final_url
    finally:
        session.close()


def _archive_document(payload: bytes, extension: str) -> tuple[str, str]:
    digest = hashlib.sha256(payload).hexdigest()
    directory = _data_root() / "documents" / "raw"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.{extension}"
    if not path.exists():
        path.write_bytes(payload)
    return str(path), digest


def _archive_text(document_sha256: str, text: str) -> tuple[str, str]:
    payload = text.encode("utf-8")
    text_sha = hashlib.sha256(payload).hexdigest()
    directory = _data_root() / "documents" / "text"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{document_sha256}.txt"
    if not path.exists():
        path.write_bytes(payload)
    return str(path), text_sha


def ingest_event_attachment(
    event_id: str,
    *,
    timeout: int = 30,
    max_bytes: int = DEFAULT_MAX_BYTES,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Download, hash, locally extract and link one stored official event attachment."""
    event = get_event_attachment(event_id, db_path=db_path)
    if not event:
        raise ValueError(f"Unknown event_id: {event_id}")
    source_url = str(event.get("attachment_url") or "").strip()
    if not source_url:
        raise ValueError("Event has no attachment URL")

    payload, mime_type, final_url = _download(source_url, timeout=timeout, max_bytes=max_bytes)
    doc_type, extension = _detect_document_type(payload, mime_type, final_url)

    expected_ext = _guess_url_extension(source_url)
    if expected_ext == "pdf" and doc_type == "HTML":
        raise ValueError("Official PDF attachment URL returned HTML; likely a block/challenge page")

    local_path, digest = _archive_document(payload, extension)
    text, page_count, extraction_status, extraction_meta = extract_document_text(payload, doc_type)

    text_path = text_sha = None
    if text:
        text_path, text_sha = _archive_text(digest, text)

    parsed = urlparse(final_url)
    metadata = {
        "document_type": doc_type,
        "original_attachment_url": source_url,
        "final_url": final_url,
        "expected_url_extension": expected_ext or None,
        "extraction": extraction_meta,
        "source_exchange": event.get("exchange"),
        "source_key": event.get("source_key"),
        "ocr_attempted": False,
    }
    document_id = upsert_document(
        sha256=digest,
        source_url=final_url,
        source_host=(parsed.hostname or "").lower(),
        mime_type=(mime_type or "").split(";", 1)[0].strip() or None,
        file_extension=extension,
        size_bytes=len(payload),
        local_path=local_path,
        fetched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        extraction_status=extraction_status,
        extracted_text_path=text_path,
        extracted_text_sha256=text_sha,
        text_chars=len(text) if text else None,
        page_count=page_count,
        metadata=metadata,
        db_path=db_path,
    )
    link_event_document(event_id, document_id, final_url, db_path=db_path)
    stored = get_document(document_id, db_path=db_path) or {}
    return {
        "status": "SUCCESS",
        "event_id": event_id,
        "document_id": document_id,
        "sha256": digest,
        "document_type": doc_type,
        "size_bytes": len(payload),
        "extraction_status": extraction_status,
        "text_chars": len(text) if text else 0,
        "page_count": page_count,
        "deduplication_key": "SHA256",
        "ocr_attempted": False,
        "stored": stored,
    }


def ingest_new_event_attachments(
    *,
    exchange: str | None = None,
    limit: int = 10,
    timeout: int = 30,
    max_bytes: int = DEFAULT_MAX_BYTES,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Best-effort attachment ingestion for NEW events; failures are isolated per event."""
    events = list_events(status="NEW", exchange=exchange, limit=max(1, min(limit, 100)), db_path=db_path)
    successes: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    skipped = 0
    for event in events:
        if not event.get("attachment_url"):
            skipped += 1
            continue
        try:
            successes.append(
                ingest_event_attachment(
                    event["event_id"], timeout=timeout, max_bytes=max_bytes, db_path=db_path
                )
            )
        except Exception as exc:
            errors.append({"event_id": event["event_id"], "error": f"{type(exc).__name__}: {exc}"})
    return {
        "status": "SUCCESS" if not errors else ("PARTIAL_SUCCESS" if successes else "FAILED"),
        "events_considered": len(events),
        "documents_ingested": len(successes),
        "events_without_attachment": skipped,
        "errors": errors,
        "results": successes,
    }
