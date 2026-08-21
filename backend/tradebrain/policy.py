"""Deterministic Trade Brain policy layer.

The existing multi-agent system may research, debate, rank, and propose ideas. This
module is the final deterministic gate for a structured trade plan. It deliberately
does not place orders and cannot be overridden by an LLM response.

Active product modes are INTRADAY and SWING. Historical DAY and SWING_POSITION
values remain accepted as compatibility aliases only. Human-approved Phase-5 soft
R:R versions may change the advisory WAIT preference, but never any hard rule.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from backend.tradebrain.soft_runtime import effective_reward_risk_preference
from backend.tradebrain.trade_modes import CompatibleTradeMode, to_active_mode, to_legacy_mode

IST = ZoneInfo("Asia/Kolkata")

TradeMode = CompatibleTradeMode
Direction = Literal["LONG", "SHORT"]
CrashGuardState = Literal["NORMAL", "ELEVATED", "SEVERE"]

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

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode_for_legacy_replay_storage(cls, value: str) -> str:
        return to_legacy_mode(value)


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

    if plan.direction == "LONG":
        if not (plan.stop_loss < plan.entry < plan.take_profit):
            failures.append("LONG requires stop_loss < entry < take_profit")
    else:
        if not (plan.take_profit < plan.entry < plan.stop_loss):
            failures.append("SHORT requires take_profit < entry < stop_loss")

    if active_mode == "SWING" and plan.direction == "SHORT":
        failures.append("SWING_POSITION short is not allowed; active mode SWING is LONG cash/delivery equity only")

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
            action = "PASS"
    else:
        action = "PASS"

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
        if rr is not None and rr < preferred:
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
    )
