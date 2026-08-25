"""Versioned Zerodha MTF funding/economics for Trade Brain SWING research.

Verified against Zerodha Support on 2026-08-25. This module models funding/charges and
conversion eligibility only; it does not expose broker order or position-mutation APIs.

Official references:
- https://support.zerodha.com/category/trading-and-markets/margins/margin-trading-facility/articles/interest-calculation-for-mtf
- https://support.zerodha.com/category/trading-and-markets/margins/margin-trading-facility/articles/convert-mtf-to-cnc
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
PROFILE_KEY = "ZERODHA_MTF_INCREMENTAL_2026_08_25_V1"
VERIFIED_ON = "2026-08-25"
DAILY_INTEREST_RATE = 0.0004  # 0.04% per day on funded amount
BROKERAGE_RATE = 0.003  # 0.3% per executed MTF order, capped below
BROKERAGE_CAP = 20.0
GST_RATE = 0.18
PLEDGE_BASE_PER_ISIN_PURCHASE_DATE = 15.0
UNPLEDGE_BASE_PER_ISIN_PURCHASE_DATE = 15.0
RMS_SQUAREOFF_BASE_PER_ORDER = 50.0


def mtf_rule_snapshot() -> dict[str, Any]:
    return {
        "profile_key": PROFILE_KEY,
        "verified_on": VERIFIED_ON,
        "interest_daily_pct_on_funded_amount": DAILY_INTEREST_RATE * 100.0,
        "interest_starts": "T+1",
        "brokerage": "min(0.3% of executed order value, INR 20) per MTF executed order",
        "pledge_charge": "INR 15 + 18% GST per ISIN per purchase date",
        "unpledge_charge": "INR 15 + 18% GST per ISIN per purchase date",
        "rms_squareoff_charge": "INR 50 + 18% GST per broker-squared-off order",
        "mtf_to_cnc_same_purchase_day_allowed": False,
        "mtf_to_cnc_from": "T+1",
        "mtf_to_cnc_requires_sufficient_funds": True,
        "conversion_before_16_00_ist_processed_same_day_subject_to_broker_restrictions": True,
        "conversion_exceptions": ["DAY_BEFORE_SETTLEMENT_HOLIDAY", "CORPORATE_ACTION_EX_DATE"],
        "credential_role": "MARKET_DATA_ONLY",
        "broker_order_execution_allowed": False,
    }


def _mtf_brokerage(order_value: float) -> float:
    if order_value < 0:
        raise ValueError("order_value must be >= 0")
    return min(BROKERAGE_CAP, order_value * BROKERAGE_RATE)


def calculate_mtf_incremental_costs(
    *,
    entry_value: float,
    funded_amount: float,
    interest_days: int,
    exit_value: float | None = None,
    purchase_date_count: int = 1,
    rms_squareoff_orders: int = 0,
    include_unpledge: bool = True,
) -> dict[str, Any]:
    """Calculate MTF-specific costs that sit on top of normal equity statutory costs.

    `interest_days` is explicit rather than guessed from timestamps. This avoids silently
    encoding settlement/calendar assumptions in a generic calculator. Callers/backtests
    must derive the eligible T+1..exit funding days using their verified calendar model.
    """
    if entry_value <= 0:
        raise ValueError("entry_value must be positive")
    if funded_amount < 0 or funded_amount > entry_value:
        raise ValueError("funded_amount must be between 0 and entry_value")
    if interest_days < 0:
        raise ValueError("interest_days must be >= 0")
    if exit_value is not None and exit_value <= 0:
        raise ValueError("exit_value must be positive when supplied")
    if purchase_date_count <= 0:
        raise ValueError("purchase_date_count must be positive")
    if rms_squareoff_orders < 0:
        raise ValueError("rms_squareoff_orders must be >= 0")

    interest = funded_amount * DAILY_INTEREST_RATE * interest_days
    buy_brokerage = _mtf_brokerage(entry_value)
    sell_brokerage = _mtf_brokerage(exit_value) if exit_value is not None else 0.0
    brokerage = buy_brokerage + sell_brokerage
    brokerage_gst = brokerage * GST_RATE

    pledge_base = PLEDGE_BASE_PER_ISIN_PURCHASE_DATE * purchase_date_count
    pledge_gst = pledge_base * GST_RATE
    unpledge_base = UNPLEDGE_BASE_PER_ISIN_PURCHASE_DATE * purchase_date_count if include_unpledge else 0.0
    unpledge_gst = unpledge_base * GST_RATE

    rms_base = RMS_SQUAREOFF_BASE_PER_ORDER * rms_squareoff_orders
    rms_gst = rms_base * GST_RATE
    total = interest + brokerage + brokerage_gst + pledge_base + pledge_gst + unpledge_base + unpledge_gst + rms_base + rms_gst

    return {
        "profile_key": PROFILE_KEY,
        "verified_on": VERIFIED_ON,
        "entry_value": round(entry_value, 2),
        "exit_value": round(exit_value, 2) if exit_value is not None else None,
        "funded_amount": round(funded_amount, 2),
        "user_cash_contribution": round(entry_value - funded_amount, 2),
        "interest_days": int(interest_days),
        "costs": {
            "mtf_interest": round(interest, 2),
            "mtf_buy_brokerage": round(buy_brokerage, 2),
            "mtf_sell_brokerage": round(sell_brokerage, 2),
            "gst_on_mtf_brokerage": round(brokerage_gst, 2),
            "pledge": round(pledge_base + pledge_gst, 2),
            "unpledge": round(unpledge_base + unpledge_gst, 2),
            "rms_squareoff_if_applicable": round(rms_base + rms_gst, 2),
            "mtf_incremental_total": round(total, 2),
        },
        "normal_equity_statutory_costs_included": False,
        "combine_with_versioned_equity_exchange_statutory_costs": True,
        "interest_days_must_come_from_verified_calendar": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def mtf_to_cnc_conversion_review(
    *,
    purchase_date: date,
    now: datetime,
    funded_amount_remaining: float,
    available_cash: float,
    settlement_holiday_block: bool = False,
    corporate_action_ex_date_block: bool = False,
) -> dict[str, Any]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    local = now.astimezone(IST)
    if funded_amount_remaining < 0 or available_cash < 0:
        raise ValueError("funded_amount_remaining and available_cash must be >= 0")
    reasons: list[str] = []
    eligible = True
    if local.date() <= purchase_date:
        eligible = False
        reasons.append("MTF_TO_CNC_NOT_ALLOWED_ON_PURCHASE_DAY")
    if settlement_holiday_block:
        eligible = False
        reasons.append("SETTLEMENT_HOLIDAY_RESTRICTION")
    if corporate_action_ex_date_block:
        eligible = False
        reasons.append("CORPORATE_ACTION_EX_DATE_RESTRICTION")
    if available_cash < funded_amount_remaining:
        eligible = False
        reasons.append("INSUFFICIENT_CASH_FOR_FULL_CONVERSION")

    processing = "SAME_DAY_SUBJECT_TO_BROKER_PROCESSING" if local.time().replace(tzinfo=None) < time(16, 0) else "NEXT_WORKING_DAY"
    return {
        "profile_key": PROFILE_KEY,
        "eligible_for_full_conversion": eligible,
        "reasons": reasons,
        "purchase_date": purchase_date.isoformat(),
        "reviewed_at_ist": local.isoformat(),
        "funded_amount_remaining": round(funded_amount_remaining, 2),
        "available_cash": round(available_cash, 2),
        "expected_processing_window": processing if eligible else None,
        "partial_conversion_may_be_possible_when_cash_is_insufficient": available_cash > 0 and available_cash < funded_amount_remaining,
        "manual_broker_action_required": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }
