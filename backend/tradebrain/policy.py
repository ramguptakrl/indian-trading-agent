"""Deterministic Trade Brain policy layer.

The existing multi-agent system may research, debate, rank, and propose ideas. This
module is the final deterministic gate for a structured trade plan. It deliberately
does not place orders and cannot be overridden by an LLM response.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

IST = ZoneInfo("Asia/Kolkata")

TradeMode = Literal["DAY", "SWING_POSITION"]
Direction = Literal["LONG", "SHORT"]
CrashGuardState = Literal["NORMAL", "ELEVATED", "SEVERE"]

DAY_NO_FRESH_ENTRY = time(15, 10)
DAY_HARD_EXIT = time(15, 15)


class TradePlan(BaseModel):
    """Structured candidate sent to the deterministic policy gate."""

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


class GateResult(BaseModel):
    """Policy decision. `advisory_only` is always true by design."""

    allowed_for_advisory: bool
    action: Literal["PASS", "WAIT", "BLOCK", "HARD_EXIT"]
    advisory_only: bool = True
    order_execution_allowed: bool = False
    hard_rule_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reward_risk: float | None = None
    preferred_reward_risk: float | None = None
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


def evaluate_trade_plan(plan: TradePlan) -> GateResult:
    """Apply immutable/user-controlled rules before any trade guidance is trusted.

    Soft preferences (for example DAY >= 1:1 and SWING around 1:3) create warnings,
    not silent hard rules. They should later be challenged with replay data.
    """

    failures: list[str] = []
    warnings: list[str] = []
    now = _now_ist(plan.evaluated_at_ist)

    # Mandatory TP/SL geometry.
    if plan.direction == "LONG":
        if not (plan.stop_loss < plan.entry < plan.take_profit):
            failures.append("LONG requires stop_loss < entry < take_profit")
    else:
        if not (plan.take_profit < plan.entry < plan.stop_loss):
            failures.append("SHORT requires take_profit < entry < stop_loss")

    # Current product architecture: swing/position is long equity only.
    if plan.mode == "SWING_POSITION" and plan.direction == "SHORT":
        failures.append("SWING_POSITION short is not allowed in the current architecture")

    # Broker/exchange restrictions, once known, outrank model opinions.
    if not plan.broker_allows_trade:
        failures.append("Broker/exchange rule does not allow this trade")

    # Crash Guard gates exposure; a crash signal never creates an automatic short.
    if plan.crash_guard == "SEVERE" and plan.direction == "LONG":
        failures.append("Severe Crash Guard blocks fresh LONG exposure")

    # User hard clock: no fresh DAY entries from 15:10; DAY positions invalid at 15:15.
    if plan.mode == "DAY":
        clock = now.timetz().replace(tzinfo=None)
        if clock >= DAY_HARD_EXIT:
            failures.append("DAY position must be flat before 15:15 IST")
            action = "HARD_EXIT"
        elif clock >= DAY_NO_FRESH_ENTRY:
            failures.append("No fresh DAY entry from 15:10 IST; exit window is active")
            action = "BLOCK"
        else:
            action = "PASS"
    else:
        action = "PASS"

    rr = _reward_risk(plan)
    preferred = 1.0 if plan.mode == "DAY" else 3.0
    if rr is None:
        # Geometry failure is already captured above; keep output explicit.
        warnings.append("Reward/risk could not be computed from the submitted geometry")
    elif rr < preferred:
        label = "1:1 DAY starting floor" if plan.mode == "DAY" else "~1:3 SWING starting preference"
        warnings.append(
            f"Reward/risk {rr:.2f}:1 is below the provisional {label}; treat as WAIT/research until evidence supports it"
        )

    if not plan.evidence:
        warnings.append("No evidence references supplied; the plan is ungrounded even if hard rules pass")

    if failures:
        if action != "HARD_EXIT":
            action = "BLOCK"
        allowed = False
    else:
        allowed = True
        # A hard-rule pass is not a BUY/SELL command. Weak soft geometry becomes WAIT.
        if rr is not None and rr < preferred:
            action = "WAIT"

    return GateResult(
        allowed_for_advisory=allowed,
        action=action,
        hard_rule_failures=failures,
        warnings=warnings,
        reward_risk=round(rr, 3) if rr is not None else None,
        preferred_reward_risk=preferred,
        evidence_count=len(plan.evidence),
        evaluated_at_ist=now.isoformat(),
    )
