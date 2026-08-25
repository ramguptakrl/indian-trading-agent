"""Deterministic Trade Brain policy layer.

The multi-agent system may research, debate, rank, and propose ideas. This module is
the final deterministic gate for a structured trade plan. It does not place orders and
cannot be overridden by an LLM response.

Active product modes are INTRADAY and SWING. Historical DAY and SWING_POSITION values
remain compatibility aliases. Active SWING is LONG-only and MTF-funded. Historical
CNC_OWN_CASH labels remain readable but are not an active SWING funding choice.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from backend.tradebrain.soft_runtime import effective_reward_risk_preference
from backend.tradebrain.trade_modes import CompatibleTradeMode, to_active_mode, to_legacy_mode, to_swing_funding

IST = ZoneInfo("Asia/Kolkata")

TradeMode = CompatibleTradeMode
Direction = Literal["LONG", "SHORT"]
CrashGuardState = Literal["NORMAL", "ELEVATED", "SEVERE"]
SwingFunding = Literal["CNC_OWN_CASH", "MTF"]

INTRADAY_NO_FRESH_ENTRY = time(15, 10)
INTRADAY_HARD_EXIT = time(15, 15)
DAY_NO_FRESH_ENTRY = INTRADAY_NO_FRESH_ENTRY
DAY_HARD_EXIT = INTRADAY_HARD_EXIT


class TradePlan(BaseModel):
    ticker: str = Field(min_length=1)
    exchange: Literal["NSE", "BSE"] = "NSE"
    mode: TradeMode
    direction: Direction
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    quantity: int | None = Field(default=None, gt=0)
    crash_guard: CrashGuardState = "NORMAL"
    broker_allows_trade: bool = True
    evidence: list[str] = Field(default_factory=list)
    evaluated_at_ist: datetime | None = None
    swing_funding: SwingFunding | None = None
    mtf_eligible_verified: bool | None = None
    funded_amount: float | None = Field(default=None, ge=0)
    mtf_interest_days: int | None = Field(default=None, ge=0)
    available_cash: float | None = Field(default=None, ge=0)

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode_for_legacy_replay_storage(cls, value: str) -> str:
        return to_legacy_mode(value)

    @field_validator("swing_funding", mode="before")
    @classmethod
    def normalize_swing_funding(cls, value: str | None) -> str | None:
        return to_swing_funding(value) if value is not None else None


class GateResult(BaseModel):
    allowed_for_advisory: bool
    action: Literal["PASS", "WAIT", "BLOCK", "HARD_EXIT"]
    active_mode: Literal["INTRADAY", "SWING"]
    advisory_only: bool = True
    order_execution_allowed: bool = False
    hard_rule_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reward_risk: float | None = None
    preferred_reward_risk: float | None = None
    preferred_reward_risk_source: str = "DEFAULT_SOFT_PREFERENCE"
    soft_parameter_key: str | None = None
    soft_parameter_version: int | None = None
    soft_parameter_registry_applied: bool = False
    evidence_count: int = 0
    evaluated_at_ist: str
    swing_funding: SwingFunding | None = None
    funding_review_required: bool = False
    mtf_eligible_verified: bool | None = None
    funded_amount: float | None = None
    mtf_interest_days: int | None = None


def _now_ist(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(IST)
    if value.tzinfo is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)


def _reward_risk(plan: TradePlan) -> float | None:
    if plan.direction == "LONG":
        risk = plan.entry - plan.stop_loss
        reward = plan.take_profit - plan.entry
    else:
        risk = plan.stop_loss - plan.entry
        reward = plan.entry - plan.take_profit
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def evaluate_trade_plan(plan: TradePlan, *, db_path: str | None = None) -> GateResult:
    failures: list[str] = []
    warnings: list[str] = []
    now = _now_ist(plan.evaluated_at_ist)
    active_mode = to_active_mode(plan.mode)
    action: Literal["PASS", "WAIT", "BLOCK", "HARD_EXIT"] = "PASS"
    funding_review_required = False

    if plan.direction == "LONG":
        if not (plan.stop_loss < plan.entry < plan.take_profit):
            failures.append("LONG requires stop_loss < entry < take_profit")
    else:
        if not (plan.take_profit < plan.entry < plan.stop_loss):
            failures.append("SHORT requires take_profit < entry < stop_loss")

    if active_mode == "SWING" and plan.direction == "SHORT":
        failures.append("SWING_POSITION short is not allowed; active SWING mode is LONG-only equity")

    if not plan.broker_allows_trade:
        failures.append("Broker/exchange rule does not allow this trade")

    if plan.crash_guard == "SEVERE" and plan.direction == "LONG":
        failures.append("Severe Crash Guard blocks fresh LONG exposure")

    if active_mode == "INTRADAY":
        clock = now.timetz().replace(tzinfo=None)
        if clock >= INTRADAY_HARD_EXIT:
            failures.append("INTRADAY position must be flat before 15:15 IST")
            action = "HARD_EXIT"
        elif clock >= INTRADAY_NO_FRESH_ENTRY:
            failures.append("No fresh INTRADAY entry from 15:10 IST; exit window is active")
            action = "BLOCK"
    else:
        if plan.swing_funding is None:
            funding_review_required = True
            warnings.append("Active SWING is MTF-only; explicit MTF funding details are required before PASS")
        elif plan.swing_funding != "MTF":
            failures.append("Active SWING requires Zerodha MTF funding; CNC_OWN_CASH is historical compatibility only")
        else:
            if plan.mtf_eligible_verified is not True:
                failures.append("MTF SWING requires current broker/security MTF eligibility to be verified")
            if plan.funded_amount is None or plan.funded_amount <= 0:
                failures.append("MTF SWING requires a positive funded_amount")
            if plan.quantity is not None and plan.funded_amount is not None:
                notional = float(plan.entry) * int(plan.quantity)
                if plan.funded_amount >= notional:
                    failures.append("MTF funded_amount must be below the modeled entry notional")
            if plan.mtf_interest_days is None or plan.mtf_interest_days < 1:
                funding_review_required = True
                warnings.append("MTF interest-days scenario is required before net-cost SWING advice can PASS")

    rr = _reward_risk(plan)
    soft = effective_reward_risk_preference(active_mode, db_path=db_path)
    preferred = float(soft["value"])
    if soft.get("warning"):
        warnings.append(str(soft["warning"]))

    if rr is None:
        warnings.append("Reward/risk could not be computed from the submitted geometry")
    elif rr < preferred:
        source_note = (
            f"human-approved soft registry v{soft['version']}"
            if soft.get("registry_applied")
            else "documented default soft preference"
        )
        warnings.append(
            f"Reward/risk {rr:.2f}:1 is below the current {active_mode} soft preference "
            f"{preferred:.2f}:1 ({source_note}); treat as WAIT/research."
        )

    if not plan.evidence:
        warnings.append("No evidence references supplied; the plan is ungrounded even if hard rules pass")

    if failures:
        if action != "HARD_EXIT":
            action = "BLOCK"
        allowed = False
    else:
        allowed = True
        if (rr is not None and rr < preferred) or funding_review_required:
            action = "WAIT"

    return GateResult(
        allowed_for_advisory=allowed,
        action=action,
        active_mode=active_mode,
        hard_rule_failures=failures,
        warnings=warnings,
        reward_risk=round(rr, 3) if rr is not None else None,
        preferred_reward_risk=preferred,
        preferred_reward_risk_source=str(soft["source"]),
        soft_parameter_key=str(soft["parameter_key"]),
        soft_parameter_version=soft.get("version"),
        soft_parameter_registry_applied=bool(soft.get("registry_applied")),
        evidence_count=len(plan.evidence),
        evaluated_at_ist=now.isoformat(),
        swing_funding=plan.swing_funding if active_mode == "SWING" else None,
        funding_review_required=funding_review_required,
        mtf_eligible_verified=plan.mtf_eligible_verified if active_mode == "SWING" else None,
        funded_amount=plan.funded_amount if active_mode == "SWING" else None,
        mtf_interest_days=plan.mtf_interest_days if active_mode == "SWING" else None,
    )
