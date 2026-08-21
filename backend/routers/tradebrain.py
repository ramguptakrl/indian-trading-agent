"""Trade Brain architecture, policy, identity, evidence, and corporate-memory API."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.tradebrain import TRADEBRAIN_VERSION
from backend.tradebrain.corporate_event_store import (
    event_stats,
    get_event,
    get_document,
    list_change_queue,
    list_events,
    set_change_queue_status,
    set_event_status,
)
from backend.tradebrain.corporate_events import (
    collect_all_corporate_events,
    collect_bse_corporate_events,
    collect_nse_corporate_events,
    replay_latest_nse_archive,
)
from backend.tradebrain.documents import ingest_event_attachment, ingest_new_event_attachments
from backend.tradebrain.event_identity import resolve_unresolved_events_exactly
from backend.tradebrain.identity import ExchangeListing, validate_listing_identity
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.schedule import get_operating_mode
from backend.tradebrain.security_master import (
    collect_all_security_masters,
    collect_bse_security_master,
    collect_nse_security_master,
)
from backend.tradebrain.security_store import (
    get_exchange_listing,
    get_identity_by_isin,
    security_master_stats,
)
from backend.tradebrain.store import (
    record_plan_evaluation,
    record_plan_outcome,
    store_stats,
    upsert_listing,
)

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain"])


class IdentityUpsertRequest(BaseModel):
    listing: ExchangeListing
    listing_name: str | None = None
    security_name: str | None = None
    listing_status: str = "UNKNOWN"
    source_key: str | None = None
    source_timestamp: str | None = None


class PlanOutcomeRequest(BaseModel):
    outcome: str
    exit_price: float | None = None
    exit_timestamp: str | None = None
    mae_pct: float | None = None
    mfe_pct: float | None = None
    r_multiple: float | None = None
    time_to_event_minutes: float | None = None
    notes: str | None = None


class StatusUpdateRequest(BaseModel):
    status: str


@router.get("/doctrine")
def doctrine():
    """Canonical rules that sit above agent opinions and heuristic recommenders."""
    return {
        "version": TRADEBRAIN_VERSION,
        "mission": "Local-first Indian-market intelligence that converts evidence into advisory trade guidance without allowing AI to override hard safety rules.",
        "architecture": [
            "official/reference data + market data",
            "local memory + provenance + security identity",
            "official corporate events + local document memory",
            "multi-agent research and repo-native scanners",
            "market structure + regime + historical outcomes",
            "risk / Crash Guard",
            "deterministic hard-rule arbiter",
            "DAY or SWING_POSITION structured plan",
            "advisory guidance only",
        ],
        "hard_rules": [
            "AUTO/ORDER execution remains disabled",
            "new plans require explicit entry, take-profit and stop-loss geometry",
            "DAY: no fresh entry from 15:10 IST and flat before 15:15 IST",
            "SWING_POSITION: LONG-only in the current equity/MTF architecture",
            "verified broker/exchange restrictions outrank model opinions",
            "Severe Crash Guard blocks fresh LONG exposure",
            "AI cannot override the deterministic gate",
        ],
        "soft_learnable": [
            "signal weights",
            "timeframe usefulness",
            "support/resistance reliability",
            "event importance/relevance after outcome validation",
            "regime importance",
            "Crash Guard threshold candidates",
            "DAY reward/risk threshold candidates",
            "SWING target candidates",
            "historical analogue weights",
            "probability/confidence calibration",
        ],
        "profiles": {
            "INDIAN_MARKET_MASTER": "Broad discovery, research, market context, company/event intelligence and cross-market learning.",
            "FOCUS_INSTRUMENT_LAB": "Strict evidence/replay/calibration path for a chosen instrument such as BSE Ltd; no assumption that broad-market weights transfer unchanged.",
        },
        "source_truth": {
            "llm": "reasoning/orchestration only",
            "security_identity": "ISIN for cross-exchange security identity; issuer entity above listings",
            "corporate_events": "official NSE/BSE source facts with raw archive and provenance",
            "event_classification": "rule-based heuristic until validated; never overwrites official source fields",
            "market_data": "vendor/official source with timestamp and provenance",
            "heuristic_scores": "soft evidence until validated out-of-sample",
        },
    }


@router.get("/operating-mode")
def operating_mode():
    return get_operating_mode()


@router.post("/validate-plan")
def validate_plan(
    plan: TradePlan,
    persist: bool = Query(False, description="Persist this evaluation for later outcome learning"),
):
    """Run a structured candidate through deterministic Trade Brain rules."""
    result = evaluate_trade_plan(plan)
    payload = result.model_dump()
    if persist:
        payload["plan_id"] = record_plan_evaluation(plan, result)
        payload["persisted"] = True
    else:
        payload["persisted"] = False
    return payload


@router.post("/plans/{plan_id}/outcome")
def save_plan_outcome(plan_id: str, data: PlanOutcomeRequest):
    """Attach plan-specific outcomes for replay/calibration learning."""
    record_plan_outcome(plan_id, **data.model_dump())
    return {"status": "saved", "plan_id": plan_id}


@router.post("/identity/validate")
def validate_identity(listing: ExchangeListing):
    return validate_listing_identity(listing)


@router.post("/identity/upsert")
def persist_identity(data: IdentityUpsertRequest):
    """Persist one safe listing/security identity without fuzzy name merging."""
    return upsert_listing(
        data.listing,
        listing_name=data.listing_name,
        security_name=data.security_name,
        listing_status=data.listing_status,
        source_key=data.source_key,
        source_timestamp=data.source_timestamp,
    )


@router.get("/identity/isin/{isin}")
def identity_by_isin(isin: str):
    result = get_identity_by_isin(isin)
    if result is None:
        raise HTTPException(status_code=404, detail="ISIN not found in Trade Brain identity store")
    return result


@router.get("/identity/listing/{exchange}/{symbol}")
def identity_by_listing(exchange: str, symbol: str):
    exchange = exchange.upper()
    if exchange not in {"NSE", "BSE"}:
        raise HTTPException(status_code=400, detail="exchange must be NSE or BSE")
    result = get_exchange_listing(exchange, symbol)
    if result is None:
        raise HTTPException(status_code=404, detail="Exchange listing not found")
    return result


@router.post("/identity/events/resolve-exact")
def resolve_event_identities(limit: int = Query(10000, ge=1, le=100000)):
    """Retry unresolved event linkage using exact identifiers/unique exact names only."""
    return resolve_unresolved_events_exactly(limit=limit)


@router.post("/security-master/nse")
def refresh_nse_security_master(timeout: int = Query(30, ge=5, le=120)):
    try:
        return collect_nse_security_master(timeout=timeout)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE security-master collection failed: {type(exc).__name__}: {exc}") from exc


@router.post("/security-master/bse")
def refresh_bse_security_master(timeout: int = Query(30, ge=5, le=120)):
    try:
        return collect_bse_security_master(timeout=timeout)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BSE security-master collection failed: {type(exc).__name__}: {exc}") from exc


@router.post("/security-master/refresh")
def refresh_all_security_masters(timeout: int = Query(30, ge=5, le=120)):
    return collect_all_security_masters(timeout=timeout)


@router.get("/security-master/stats")
def get_security_master_stats():
    return security_master_stats()


# ---------------------------------------------------------------------------
# Phase 2: official corporate events + local document memory
# ---------------------------------------------------------------------------


@router.post("/corporate-events/nse")
def refresh_nse_corporate_events(timeout: int = Query(30, ge=5, le=120)):
    try:
        return collect_nse_corporate_events(timeout=timeout)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE corporate-event collection failed: {type(exc).__name__}: {exc}") from exc


@router.post("/corporate-events/nse/replay-latest-archive")
def replay_nse_corporate_event_archive():
    try:
        return replay_latest_nse_archive()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NSE archive replay failed: {type(exc).__name__}: {exc}") from exc


@router.post("/corporate-events/bse")
def refresh_bse_corporate_events(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    max_pages: int = Query(100, ge=1, le=500),
    timeout: int = Query(30, ge=5, le=120),
):
    try:
        return collect_bse_corporate_events(
            from_date=from_date, to_date=to_date, max_pages=max_pages, timeout=timeout
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BSE corporate-event collection failed: {type(exc).__name__}: {exc}") from exc


@router.post("/corporate-events/refresh")
def refresh_all_corporate_events(timeout: int = Query(30, ge=5, le=120)):
    return collect_all_corporate_events(timeout=timeout)


@router.get("/events/stats")
def get_event_stats():
    return event_stats()


@router.get("/events")
def get_events(
    status: str | None = Query("NEW"),
    exchange: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if exchange and exchange.upper() not in {"NSE", "BSE"}:
        raise HTTPException(status_code=400, detail="exchange must be NSE or BSE")
    return {
        "events": list_events(status=status, exchange=exchange, limit=limit, offset=offset),
        "source_truth": "Official source fields are facts; category/importance are labelled heuristics",
    }


# Static attachment route must be declared before /events/{event_id}.
@router.post("/events/download-new-attachments")
def download_new_event_attachments(
    exchange: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
    timeout: int = Query(30, ge=5, le=120),
    max_megabytes: int = Query(25, ge=1, le=100),
):
    if exchange and exchange.upper() not in {"NSE", "BSE"}:
        raise HTTPException(status_code=400, detail="exchange must be NSE or BSE")
    return ingest_new_event_attachments(
        exchange=exchange,
        limit=limit,
        timeout=timeout,
        max_bytes=max_megabytes * 1024 * 1024,
    )


@router.get("/events/{event_id}")
def get_corporate_event(event_id: str):
    result = get_event(event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Corporate event not found")
    return result


@router.post("/events/{event_id}/status")
def update_event_status(event_id: str, data: StatusUpdateRequest):
    try:
        set_event_status(event_id, data.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "saved", "event_id": event_id, "inbox_status": data.status.upper()}


@router.post("/events/{event_id}/download-attachment")
def download_event_attachment(
    event_id: str,
    timeout: int = Query(30, ge=5, le=120),
    max_megabytes: int = Query(25, ge=1, le=100),
):
    try:
        return ingest_event_attachment(
            event_id, timeout=timeout, max_bytes=max_megabytes * 1024 * 1024
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Attachment ingestion failed: {type(exc).__name__}: {exc}") from exc


@router.get("/documents/{document_id}")
def get_corporate_document(document_id: str):
    result = get_document(document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return result


@router.get("/change-queue")
def get_change_queue(
    status: str | None = Query("PENDING"), limit: int = Query(100, ge=1, le=500)
):
    return {
        "items": list_change_queue(status=status, limit=limit),
        "purpose": "Evidence-backed review queue for material corporate events; not an AI trade signal",
    }


@router.post("/change-queue/{queue_id}/status")
def update_change_queue_status(queue_id: str, data: StatusUpdateRequest):
    try:
        set_change_queue_status(queue_id, data.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "saved", "queue_id": queue_id, "queue_status": data.status.upper()}


@router.get("/store/stats")
def get_store_stats():
    return store_stats()


@router.get("/roadmap")
def roadmap():
    return {
        "completed": [
            "deterministic hard-rule gate",
            "market/study operating-mode scheduler",
            "ISIN-first identity primitives",
            "persistent issuer/security/listing tables",
            "provenance hashing + raw-artifact registry",
            "official NSE/BSE equity security-master collectors",
            "idempotent official-master upserts and identity lookup APIs",
            "official NSE/BSE corporate-event collectors",
            "raw corporate-feed archive + archive replay",
            "repeat-safe event inbox and exact identity re-resolution",
            "rule-labelled event categorization/importance and what-changed queue",
            "official attachment download with SHA-256 document deduplication",
            "local PDF/DOCX/HTML/XML/JSON/text extraction without OCR",
            "persistent structured plan evaluations and outcomes",
            "soft-evidence annotations for legacy heuristic outputs",
        ],
        "next": [
            "audited OHLCV store and derived multi-timeframe candles",
            "automatic TP-first/SL-first/MAE/MFE/time-to-event outcome backfill",
            "event/filing historical price-effect study and BSE relevance calibration",
            "BSE-focused Crash Guard and level-reliability replay",
            "MTF financing + Indian broker cost engine",
            "challenger/promote learning workflow with walk-forward validation",
            "paper-broker adapter; live execution remains a separate later decision",
        ],
    }
