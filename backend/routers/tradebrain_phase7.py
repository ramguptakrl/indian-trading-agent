"""Phase 7 API: reviewed soft-parameter runtime application."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from backend.tradebrain.soft_runtime import effective_reward_risk_preference, effective_soft_runtime

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain-phase7"])


@router.get("/phase7/doctrine")
def phase7_doctrine():
    return {
        "phase": 7,
        "tradebrain_version": "0.8.0",
        "runtime_soft_registry_enabled": True,
        "human_approval_required": True,
        "automatic_soft_promotion": False,
        "hard_policy_mutation_allowed": False,
        "supported_runtime_preferences": [
            "INTRADAY minimum reward:risk",
            "SWING minimum reward:risk",
        ],
        "fail_safe": "Missing/malformed/ambiguous registry state falls back to documented defaults.",
    }


@router.get("/phase7/soft-runtime")
def phase7_soft_runtime():
    return effective_soft_runtime()


@router.get("/phase7/soft-runtime/{mode}")
def phase7_soft_runtime_mode(mode: Literal["INTRADAY", "SWING"]):
    return effective_reward_risk_preference(mode)
