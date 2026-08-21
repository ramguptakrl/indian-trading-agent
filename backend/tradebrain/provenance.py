"""Small provenance helpers used by future official-source collectors."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(payload: str, encoding: str = "utf-8") -> str:
    return sha256_bytes(payload.encode(encoding))


def provenance_record(
    *,
    source: str,
    source_url: str | None,
    payload_sha256: str,
    fetched_at: datetime | None = None,
    raw_archive_path: str | None = None,
) -> dict:
    ts = fetched_at or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return {
        "source": source,
        "source_url": source_url,
        "fetched_at": ts.astimezone(timezone.utc).isoformat(),
        "sha256": payload_sha256,
        "raw_archive_path": raw_archive_path,
    }
