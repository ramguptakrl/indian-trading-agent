"""Trade Brain architecture and deterministic policy API."""

from fastapi import APIRouter

from backend.tradebrain import TRADEBRAIN_VERSION
from backend.tradebrain.identity import ExchangeListing, validate_listing_identity
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.schedule import get_operating_mode

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain"])


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
def validate_plan(plan: TradePlan):
    """Run a structured candidate through deterministic Trade Brain rules."""
    return evaluate_trade_plan(plan)


@router.post("/identity/validate")
def validate_identity(listing: ExchangeListing):
    return validate_listing_identity(listing)


@router.get("/roadmap")
def roadmap():
    return {
        "completed_in_reframe_foundation": [
            "deterministic hard-rule gate",
            "market/study operating-mode scheduler",
            "ISIN-first identity primitives",
            "provenance hashing primitives",
            "soft-evidence annotations for legacy heuristic outputs",
        ],
        "next": [
            "official NSE/BSE security-master collectors + persisted issuer/security/listing map",
            "corporate-event and attachment archive with hashing/idempotency",
            "audited OHLCV store and derived multi-timeframe candles",
            "plan-specific outcome records (TP-first/SL-first/MAE/MFE/time-to-event)",
            "BSE-focused Crash Guard and level-reliability replay",
            "MTF financing + Indian broker cost engine",
            "challenger/promote learning workflow with walk-forward validation",
            "paper-broker adapter; live execution remains a separate later decision",
        ],
    }
