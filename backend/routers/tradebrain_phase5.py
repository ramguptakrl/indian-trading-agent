"""Phase 5 API: frozen challenger experiments, walk-forward validation and audit."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.tradebrain.challenger import (
    METHOD_VERSION,
    SUPPORTED_SOFT_PARAMETERS,
    create_challenger,
    evaluate_challenger,
    experiment_report,
    freeze_challenger,
    parameter_class,
    phase5_stats,
    promote_challenger,
    reject_challenger,
)
from backend.tradebrain.challenger_store import list_soft_parameter_versions
from backend.tradebrain.regime_hardening import (
    REGIME_METHOD_VERSION,
    classify_instrument_regime_recent,
)

router = APIRouter(prefix="/api/tradebrain", tags=["tradebrain-phase5"])


class ChallengerCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    series_id: str = Field(min_length=5)
    interval: str = Field(default="5m", min_length=1, max_length=12)
    parameter_key: str = Field(min_length=2, max_length=120)
    incumbent_value: float = Field(gt=0)
    challenger_value: float = Field(gt=0)
    hypothesis: str = Field(min_length=5, max_length=2000)
    thresholds: dict[str, Any] | None = None
    created_by: str = Field(default="HUMAN_REQUEST", min_length=2, max_length=120)


class ChallengerWindow(BaseModel):
    role: Literal["TRAIN", "VALIDATION", "WALK_FORWARD"]
    starts_at: str
    ends_at: str
    ordinal: int | None = Field(default=None, ge=1)


class ChallengerFreezeRequest(BaseModel):
    windows: list[ChallengerWindow] = Field(min_length=3)


class PromotionRequest(BaseModel):
    approved_by: str = Field(min_length=2, max_length=160)
    approval_note: str = Field(min_length=5, max_length=4000)


class RejectionRequest(BaseModel):
    rejected_by: str = Field(min_length=2, max_length=160)
    rejection_note: str = Field(min_length=5, max_length=4000)


@router.post("/challengers")
def create_phase5_challenger(data: ChallengerCreateRequest):
    try:
        return create_challenger(**data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/challengers/{experiment_id}/freeze")
def freeze_phase5_challenger(experiment_id: str, data: ChallengerFreezeRequest):
    try:
        return freeze_challenger(
            experiment_id,
            windows=[window.model_dump(exclude_none=True) for window in data.windows],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/challengers/{experiment_id}/evaluate")
def evaluate_phase5_challenger(experiment_id: str):
    try:
        return evaluate_challenger(experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/challengers/{experiment_id}")
def get_phase5_challenger(experiment_id: str):
    try:
        return experiment_report(experiment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/challengers/{experiment_id}/promote")
def promote_phase5_challenger(experiment_id: str, data: PromotionRequest):
    try:
        return promote_challenger(
            experiment_id,
            approved_by=data.approved_by,
            approval_note=data.approval_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/challengers/{experiment_id}/reject")
def reject_phase5_challenger(experiment_id: str, data: RejectionRequest):
    try:
        return reject_challenger(
            experiment_id,
            rejected_by=data.rejected_by,
            rejection_note=data.rejection_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/challengers/stats/summary")
def phase5_challenger_stats():
    return phase5_stats()


@router.get("/challengers/soft-parameters/versions")
def phase5_soft_parameter_versions(parameter_key: str | None = None, active_only: bool = False):
    return {
        "versions": list_soft_parameter_versions(
            parameter_key=parameter_key, active_only=active_only
        ),
        "runtime_policy_mutated_by_registry": False,
    }


@router.get("/challengers/parameter-class/{parameter_key}")
def get_parameter_class(parameter_key: str):
    return {
        "parameter_key": parameter_key,
        "parameter_class": parameter_class(parameter_key),
        "supported_v1": parameter_key.lower() in SUPPORTED_SOFT_PARAMETERS,
    }


@router.get("/challengers/regime/{series_id}")
def phase5_hardened_regime(series_id: str, as_of: str):
    try:
        return classify_instrument_regime_recent(series_id, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/challengers/doctrine")
def phase5_doctrine():
    return {
        "phase": 5,
        "tradebrain_version": "0.6.0",
        "method_version": METHOD_VERSION,
        "regime_method": REGIME_METHOD_VERSION,
        "supported_soft_parameters": sorted(SUPPORTED_SOFT_PARAMETERS),
        "freeze_rule": "Challenger definition + TRAIN/VALIDATION/WALK_FORWARD windows are SHA-256 frozen before evaluation",
        "validation_rule": "TRAIN results are diagnostic only; promotion readiness is decided from frozen VALIDATION/WALK_FORWARD windows",
        "lookahead_rule": "Outcomes not knowable by a frozen window end are censored from that window",
        "ambiguity_rule": "Phase-4 AMBIGUOUS outcomes remain ambiguous and count against quality gates",
        "promotion_rule": "Evaluation can reach READY_FOR_REVIEW only. Explicit human approval is required to write the soft-parameter registry",
        "runtime_rule": "Promoted values are audited registry entries and do not silently mutate deterministic policy runtime",
        "hard_rule_rule": "Protected safety/execution rules cannot enter automatic challenger promotion",
        "execution": "OFF",
    }
