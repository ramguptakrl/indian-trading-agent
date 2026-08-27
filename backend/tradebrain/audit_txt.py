"""Human-readable append-only Trade Brain audit trail.

This module intentionally records structured evidence, concise rationale summaries,
rule/gate outcomes, learning/test interpretations and provenance. It does NOT attempt
to persist hidden model chain-of-thought. Credential-like fields are always redacted.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_SENSITIVE_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "enctoken",
    "request_token",
    "access_token",
)


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


def audit_root() -> Path:
    configured = os.getenv("TRADEBRAIN_AUDIT_DIR")
    root = Path(configured).expanduser() if configured else _data_root() / "audit_txt"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in _SENSITIVE_MARKERS)


def redact_sensitive(value: Any) -> Any:
    """Recursively redact credential-like fields before persistence."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    return value


def _safe_text(value: str | None) -> str | None:
    if value is None:
        return None
    # Rationale fields are summaries only; remove accidental bearer-like material.
    text = str(value)
    lowered = text.lower()
    if any(marker in lowered for marker in ("api_secret=", "access_token=", "request_token=", "authorization: token")):
        return "[REDACTED: contained credential-like material]"
    return text


def daily_audit_path(at: datetime | None = None) -> Path:
    stamp = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return audit_root() / f"tradebrain-audit-{stamp.date().isoformat()}.txt"


def append_audit_record(
    *,
    category: str,
    event: str,
    payload: dict[str, Any] | None = None,
    rationale_summary: str | None = None,
    interpretation: str | None = None,
    source: str | None = None,
    at: datetime | None = None,
) -> str:
    """Append one structured, human-readable audit record and return its path."""
    stamp = at or datetime.now(timezone.utc)
    path = daily_audit_path(stamp)
    record = {
        "timestamp_utc": stamp.astimezone(timezone.utc).isoformat(),
        "category": str(category).upper(),
        "event": str(event),
        "source": source,
        "rationale_summary": _safe_text(rationale_summary),
        "interpretation": _safe_text(interpretation),
        "payload": redact_sensitive(payload or {}),
        "hidden_chain_of_thought_persisted": False,
    }
    block = (
        "=" * 88
        + "\n"
        + f"[{record['timestamp_utc']}] {record['category']} | {record['event']}\n"
        + (f"SOURCE: {source}\n" if source else "")
        + (f"RATIONALE SUMMARY: {record['rationale_summary']}\n" if record["rationale_summary"] else "")
        + (f"INTERPRETATION: {record['interpretation']}\n" if record["interpretation"] else "")
        + "STRUCTURED DATA:\n"
        + json.dumps(record["payload"], indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\nHIDDEN CHAIN-OF-THOUGHT STORED: NO\n"
    )
    with _LOCK:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(block)
    return str(path)


def audit_final_advisory(result: dict[str, Any], *, request: dict[str, Any] | None = None) -> str:
    status = str(result.get("final_status") or "UNKNOWN")
    gate = result.get("gate") or {}
    parsed = result.get("ai_candidate") or {}
    geometry = result.get("trade_geometry") or {}
    reasons = gate.get("reasons") if isinstance(gate, dict) else None
    rationale = (
        f"Final status {status}; structured candidate={parsed.get('research_label')}; "
        f"mode={geometry.get('mode') or parsed.get('mode')}; direction={geometry.get('direction') or parsed.get('direction')}; "
        f"deterministic gate={gate.get('action') if isinstance(gate, dict) else None}."
    )
    if reasons:
        rationale += f" Gate reasons: {reasons}."
    return append_audit_record(
        category="DECISION",
        event="FINAL_ADVISORY",
        payload={"request": request or {}, "result": result},
        rationale_summary=rationale,
        interpretation="This is an advisory/audit record only; it is not broker authorization and cannot place an order.",
        source="backend.tradebrain.advisory_pipeline",
    )


def audit_learning(event: str, payload: dict[str, Any], *, interpretation: str | None = None) -> str:
    return append_audit_record(
        category="LEARNING",
        event=event,
        payload=payload,
        interpretation=interpretation,
        source="tradebrain-evidence",
    )


def audit_test_interpretation(event: str, payload: dict[str, Any], *, interpretation: str) -> str:
    return append_audit_record(
        category="TEST",
        event=event,
        payload=payload,
        interpretation=interpretation,
        source="tradebrain-validation",
    )
