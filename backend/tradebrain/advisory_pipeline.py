"""Phase 10 final advisory pipeline.

The upstream multi-agent graph produces research prose. This module accepts only its
explicit structured fields, then applies verified calendar state, deterministic Trade
Brain policy, human-reviewed soft preferences, and resident transaction-cost economics.
Active SWING is LONG-only Zerodha MTF-funded. The pipeline never turns free-form prose
into trade permission and never places an order.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.equity_costs import calculate_equity_trade_costs
from backend.tradebrain.exchange_calendar import session_for_date
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.schedule import get_operating_mode
from backend.tradebrain.swing_mtf import calculate_swing_mtf_trade_costs
from backend.tradebrain.trade_modes import to_active_mode

IST = ZoneInfo("Asia/Kolkata")

FIELD_LABELS = {
    "candidate_verdict": ("Candidate Verdict",),
    "mode": ("Trade Mode",),
    "direction": ("Direction",),
    "entry": ("Entry Price", "Entry"),
    "stop_loss": ("Stop-Loss", "Stop Loss", "SL"),
    "take_profit": ("Take-Profit", "Take Profit", "Primary Take-Profit", "TP"),
}

SAFE_VERDICTS = {"HOLD / WAIT", "HOLD-WAIT", "HOLD", "WAIT", "NO TRADE"}
LONG_VERDICTS = {"STRONG BUY CANDIDATE", "BUY CANDIDATE"}
SHORT_VERDICTS = {"SHORT CANDIDATE"}
EXIT_VERDICTS = {"SELL / EXIT CANDIDATE", "SELL-EXIT CANDIDATE", "EXIT CANDIDATE"}


def _clean(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\*\*", "", value)
    value = re.sub(r"[`_]", "", value)
    return value.strip()


def _field(text: str, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        pattern = re.compile(
            rf"(?im)^\s*(?:[-*]\s*)?(?:\d+[.)]\s*)?(?:\*\*)?{re.escape(alias)}(?:\*\*)?\s*:\s*(.+?)\s*$"
        )
        match = pattern.search(text or "")
        if match:
            return _clean(match.group(1))
    return None


def _normalize_choice(value: str | None, allowed: set[str]) -> str | None:
    if not value:
        return None
    cleaned = _clean(value).upper().replace("–", "-").replace("—", "-")
    first = re.split(r"\s+(?:BECAUSE|DUE TO|AS |\-|\(|\[)", cleaned, maxsplit=1)[0].strip()
    if cleaned in allowed:
        return cleaned
    if first in allowed:
        return first
    return None


def _price(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = _clean(value).upper()
    if cleaned in {"N/A", "NA", "NONE", "NOT APPLICABLE", "-"}:
        return None
    cleaned = cleaned.replace("₹", "").replace("RS.", "").replace("RS", "").replace(",", "").strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(?:\s*(?:INR|RUPEES?))?", cleaned)
    if not match:
        return None
    number = float(match.group(1))
    return number if number > 0 else None


def parse_agent_candidate(text: str) -> dict[str, Any]:
    """Parse only labelled Portfolio Manager fields; never infer from narrative prose."""

    raw = {key: _field(text, aliases) for key, aliases in FIELD_LABELS.items()}
    verdict_allowed = SAFE_VERDICTS | LONG_VERDICTS | SHORT_VERDICTS | EXIT_VERDICTS
    verdict = _normalize_choice(raw["candidate_verdict"], verdict_allowed)
    mode = _normalize_choice(raw["mode"], {"INTRADAY", "SWING", "NONE", "DAY", "SWING_POSITION"})
    direction = _normalize_choice(raw["direction"], {"LONG", "SHORT", "NONE"})
    parsed = {
        "candidate_verdict": verdict,
        "mode": to_active_mode(mode) if mode and mode != "NONE" else None,
        "direction": direction if direction and direction != "NONE" else None,
        "entry": _price(raw["entry"]),
        "stop_loss": _price(raw["stop_loss"]),
        "take_profit": _price(raw["take_profit"]),
        "raw_fields": raw,
        "parser": "STRICT_LABELLED_FIELDS_V1",
        "free_form_inference_used": False,
    }

    errors: list[str] = []
    if verdict is None:
        errors.append("Missing or unsupported Candidate Verdict field")

    safe_no_trade = verdict in SAFE_VERDICTS if verdict else False
    exit_only = verdict in EXIT_VERDICTS and parsed["direction"] is None
    if safe_no_trade or exit_only:
        parsed.update(
            {
                "parse_status": "SAFE_NON_ENTRY",
                "errors": errors,
                "entry_candidate": False,
                "research_label": "EXIT_CANDIDATE" if exit_only else ("WAIT" if verdict != "NO TRADE" else "NO_TRADE"),
            }
        )
        return parsed

    if mode is None or mode == "NONE":
        errors.append("Explicit Trade Mode INTRADAY or SWING is required")
    if direction is None or direction == "NONE":
        errors.append("Explicit Direction LONG or SHORT is required")
    for key, label in (("entry", "Entry Price"), ("stop_loss", "Stop-Loss"), ("take_profit", "Take-Profit")):
        if parsed[key] is None:
            errors.append(f"Unambiguous numeric {label} is required")

    if verdict in LONG_VERDICTS and direction != "LONG":
        errors.append("BUY candidate verdict requires Direction LONG")
    if verdict in SHORT_VERDICTS and direction != "SHORT":
        errors.append("SHORT candidate verdict requires Direction SHORT")
    if verdict in EXIT_VERDICTS:
        errors.append(
            "SELL/EXIT is a reduction/exit label, not permission to initiate a fresh position; "
            "use SHORT CANDIDATE for a new intraday short"
        )

    if errors:
        parsed.update(
            {
                "parse_status": "PARSE_INCOMPLETE",
                "errors": errors,
                "entry_candidate": False,
                "research_label": "NO_TRADE",
            }
        )
        return parsed

    parsed.update(
        {
            "parse_status": "STRUCTURED_CANDIDATE",
            "errors": [],
            "entry_candidate": True,
            "research_label": "LONG_CANDIDATE" if direction == "LONG" else "SHORT_CANDIDATE",
        }
    )
    return parsed


def research_label(text: str) -> str:
    """Safe UI/research label. Never returns BUY or SELL as authorization-like output."""
    return str(parse_agent_candidate(text)["research_label"])


def _aware(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(IST)
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware for a final advisory gate")
    return parsed.astimezone(IST)


def _cost_scenarios(plan: TradePlan, *, quantity: int | None, slippage_bps: float) -> dict[str, Any]:
    if not quantity:
        return {
            "status": "NOT_COMPUTED_QUANTITY_REQUIRED",
            "profile_scope": "RESIDENT_INDIAN_TRANSACTION_COSTS_BEFORE_INCOME_TAX",
            "quantity": None,
            "note": "Quantity is required for net rupee economics. Personal income/capital-gains tax is excluded.",
        }

    if to_active_mode(plan.mode) == "SWING":
        if (
            plan.swing_funding != "MTF"
            or plan.mtf_eligible_verified is not True
            or plan.funded_amount is None
            or plan.funded_amount <= 0
        ):
            return {
                "status": "NOT_COMPUTED_MTF_FUNDING_UNVERIFIED",
                "profile_scope": "RESIDENT_INDIAN_EQUITY_PLUS_ZERODHA_MTF_BEFORE_INCOME_TAX",
                "quantity": quantity,
                "note": "Active SWING requires verified MTF eligibility and funded_amount.",
            }
        if plan.mtf_interest_days is None or plan.mtf_interest_days < 1:
            return {
                "status": "NOT_COMPUTED_MTF_INTEREST_DAYS_REQUIRED",
                "profile_scope": "RESIDENT_INDIAN_EQUITY_PLUS_ZERODHA_MTF_BEFORE_INCOME_TAX",
                "quantity": quantity,
                "note": "A positive MTF interest-days scenario is required; Trade Brain will not invent a holding period.",
            }
        target = calculate_swing_mtf_trade_costs(
            exchange=plan.exchange,
            entry_price=plan.entry,
            exit_price=plan.take_profit,
            quantity=quantity,
            funded_amount=plan.funded_amount,
            interest_days=plan.mtf_interest_days,
            slippage_bps=slippage_bps,
        )
        stop = calculate_swing_mtf_trade_costs(
            exchange=plan.exchange,
            entry_price=plan.entry,
            exit_price=plan.stop_loss,
            quantity=quantity,
            funded_amount=plan.funded_amount,
            interest_days=plan.mtf_interest_days,
            slippage_bps=slippage_bps,
        )
        scope = "RESIDENT_INDIAN_EQUITY_PLUS_ZERODHA_MTF_BEFORE_INCOME_TAX"
    else:
        target = calculate_equity_trade_costs(
            mode=plan.mode,
            exchange=plan.exchange,
            direction=plan.direction,
            entry_price=plan.entry,
            exit_price=plan.take_profit,
            quantity=quantity,
            slippage_bps=slippage_bps,
        )
        stop = calculate_equity_trade_costs(
            mode=plan.mode,
            exchange=plan.exchange,
            direction=plan.direction,
            entry_price=plan.entry,
            exit_price=plan.stop_loss,
            quantity=quantity,
            slippage_bps=slippage_bps,
        )
        scope = "RESIDENT_INDIAN_TRANSACTION_COSTS_BEFORE_INCOME_TAX"

    net_reward = float(target["net_pnl"])
    net_loss = abs(float(stop["net_pnl"])) if float(stop["net_pnl"]) < 0 else 0.0
    return {
        "status": "COMPUTED",
        "profile_scope": scope,
        "quantity": quantity,
        "target_scenario": target,
        "stop_scenario": stop,
        "net_reward_rupees": round(net_reward, 2),
        "net_loss_rupees": round(net_loss, 2),
        "net_reward_risk": round(net_reward / net_loss, 4) if net_reward > 0 and net_loss > 0 else None,
        "mtf_used": to_active_mode(plan.mode) == "SWING",
        "note": "Includes modeled transaction costs/slippage and MTF funding costs for SWING; excludes personal income/capital-gains tax.",
    }


def evaluate_final_advisory(
    *,
    ticker: str,
    exchange: str,
    final_trade_decision: str,
    evaluated_at: datetime | str | None = None,
    quantity: int | None = None,
    crash_guard: str | None = None,
    broker_allows_trade: bool | None = None,
    require_verified_calendar: bool = True,
    slippage_bps: float = 0.0,
    swing_funding: str | None = None,
    mtf_eligible_verified: bool | None = None,
    funded_amount: float | None = None,
    mtf_interest_days: int | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Convert explicit agent structure into a deterministic advisory result."""

    parsed = parse_agent_candidate(final_trade_decision)
    now = _aware(evaluated_at)
    base = {
        "tradebrain_version": "0.13.0",
        "ticker": ticker.strip().upper(),
        "exchange": exchange.strip().upper(),
        "evaluated_at_ist": now.isoformat(),
        "ai_candidate": parsed,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
        "order_endpoint_present": False,
        "final_status": "NO_TRADE",
    }

    if parsed["parse_status"] == "SAFE_NON_ENTRY":
        base["final_status"] = "EXIT_CANDIDATE" if parsed["research_label"] == "EXIT_CANDIDATE" else parsed["research_label"]
        base["gate"] = None
        base["calendar"] = None
        base["costs"] = {"status": "NOT_APPLICABLE_NO_NEW_ENTRY"}
        return base

    if parsed["parse_status"] != "STRUCTURED_CANDIDATE":
        base["final_status"] = "BLOCK_PARSE_INCOMPLETE"
        base["gate"] = None
        base["calendar"] = None
        base["costs"] = {"status": "NOT_COMPUTED_PARSE_INCOMPLETE"}
        return base

    calendar = session_for_date(now, exchange=base["exchange"], db_path=db_path)
    base["calendar"] = calendar
    if require_verified_calendar and not calendar.get("calendar_verified"):
        base["final_status"] = "BLOCK_CALENDAR_UNVERIFIED"
        base["gate"] = None
        base["costs"] = {"status": "NOT_COMPUTED_CALENDAR_BLOCK"}
        return base
    if not calendar.get("is_trading_session"):
        base["final_status"] = (
            "BLOCK_SPECIAL_SESSION_TIMES_UNVERIFIED"
            if calendar.get("session_type") == "SPECIAL_PENDING"
            else "BLOCK_MARKET_CLOSED"
        )
        base["gate"] = None
        base["costs"] = {"status": "NOT_COMPUTED_CALENDAR_BLOCK"}
        return base

    if parsed["mode"] == "INTRADAY":
        operating = get_operating_mode(
            now,
            exchange=base["exchange"],
            db_path=db_path,
            require_verified_calendar=require_verified_calendar,
        )
        base["operating_mode"] = operating
        if operating.get("intraday_trade_state") in {
            "CLOSED",
            "CALENDAR_UNVERIFIED",
            "SPECIAL_SESSION_PENDING_TIMES",
            "SPECIAL_SESSION_RESEARCH_ONLY",
        }:
            base["final_status"] = f"BLOCK_{operating['intraday_trade_state']}"
            base["gate"] = None
            base["costs"] = {"status": "NOT_COMPUTED_SESSION_BLOCK"}
            return base

    if crash_guard not in {"NORMAL", "ELEVATED", "SEVERE"}:
        base["final_status"] = "BLOCK_CRASH_GUARD_UNVERIFIED"
        base["gate"] = None
        base["costs"] = {"status": "NOT_COMPUTED_RISK_STATE_BLOCK"}
        return base
    if broker_allows_trade is None:
        base["final_status"] = "BLOCK_BROKER_PERMISSION_UNVERIFIED"
        base["gate"] = None
        base["costs"] = {"status": "NOT_COMPUTED_BROKER_STATE_BLOCK"}
        return base

    plan = TradePlan(
        ticker=base["ticker"],
        exchange=base["exchange"],
        mode=parsed["mode"],
        direction=parsed["direction"],
        entry=parsed["entry"],
        stop_loss=parsed["stop_loss"],
        take_profit=parsed["take_profit"],
        quantity=quantity,
        crash_guard=crash_guard,
        broker_allows_trade=broker_allows_trade,
        evidence=["AI_STRUCTURED_CANDIDATE_NOT_SOURCE_OF_TRUTH"],
        evaluated_at_ist=now,
        swing_funding=swing_funding,
        mtf_eligible_verified=mtf_eligible_verified,
        funded_amount=funded_amount,
        mtf_interest_days=mtf_interest_days,
    )
    gate = evaluate_trade_plan(plan, db_path=db_path)
    base["gate"] = gate.model_dump()
    base["trade_geometry"] = {
        "mode": gate.active_mode,
        "direction": plan.direction,
        "entry": plan.entry,
        "stop_loss": plan.stop_loss,
        "take_profit": plan.take_profit,
        "gross_reward_risk": gate.reward_risk,
        "soft_preferred_reward_risk": gate.preferred_reward_risk,
        "soft_preference_source": gate.preferred_reward_risk_source,
        "soft_parameter_version": gate.soft_parameter_version,
        "swing_funding": gate.swing_funding,
        "mtf_eligible_verified": gate.mtf_eligible_verified,
        "funded_amount": gate.funded_amount,
        "mtf_interest_days": gate.mtf_interest_days,
    }
    base["costs"] = _cost_scenarios(plan, quantity=quantity, slippage_bps=slippage_bps)

    if gate.action == "PASS" and base["costs"].get("status") != "COMPUTED" and gate.active_mode == "SWING":
        base["final_status"] = "WAIT"
    elif gate.action == "PASS":
        base["final_status"] = "ADVISORY_CANDIDATE_PASS"
    elif gate.action == "WAIT":
        base["final_status"] = "WAIT"
    elif gate.action == "HARD_EXIT":
        base["final_status"] = "HARD_EXIT"
    else:
        base["final_status"] = "BLOCK"
    return base
