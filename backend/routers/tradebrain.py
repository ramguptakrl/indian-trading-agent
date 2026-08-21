"""Trade Brain architecture, policy, identity, and evidence-store API."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.tradebrain import TRADEBRAIN_VERSION
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


@router.get("/doctrine")
def doctrine():
    """Canonical rules that sit above agent opinions and heuristic recommenders."""
    return {
        "version": TRADEBRAIN_VERSION,
        "mission": "Local-first Indian-market intelligence that converts evidence into advisory trade guidance without allowing AI to override hard safety rules.",
        "architecture": [
            "official/reference data + market data",
            "local memory + provenance + security identity",
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
            "persistent structured plan evaluations and outcomes",
            "soft-evidence annotations for legacy heuristic outputs",
        ],
        "next": [
            "corporate-event and attachment archive with hashing/idempotency",
            "audited OHLCV store and derived multi-timeframe candles",
            "automatic TP-first/SL-first/MAE/MFE/time-to-event outcome backfill",
            "BSE-focused Crash Guard and level-reliability replay",
            "MTF financing + Indian broker cost engine",
            "challenger/promote learning workflow with walk-forward validation",
            "paper-broker adapter; live execution remains a separate later decision",
        ],
    }
