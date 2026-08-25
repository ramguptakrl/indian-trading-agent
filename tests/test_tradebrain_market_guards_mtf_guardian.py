from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from backend.tradebrain.market_guards import (
    extract_kite_price_range,
    freak_tick_guard,
    market_halt_guard,
    price_range_guard,
)
from backend.tradebrain.mtf_economics import (
    calculate_mtf_incremental_costs,
    mtf_to_cnc_conversion_review,
)
from backend.tradebrain.position_guardian import assess_open_trade_risk

IST = ZoneInfo("Asia/Kolkata")


def _trade(*, mode="INTRADAY", direction="LONG", stop=95.0, target=110.0):
    return {
        "trade_id": "t1",
        "status": "OPEN",
        "open_quantity": 10,
        "mode": mode,
        "direction": direction,
        "avg_entry_price": 100.0,
        "entry_timestamp": datetime(2026, 8, 25, 10, 0, tzinfo=IST).astimezone(timezone.utc).isoformat(),
        "stop_loss": stop,
        "take_profit": target,
    }


def test_price_range_never_invents_missing_circuit_percentage():
    extracted = extract_kite_price_range({"last_price": 100})
    assert extracted["status"] == "UNKNOWN"
    assert extracted["hardcoded_percentage_used"] is False
    guard = price_range_guard(100, lower_limit=None, upper_limit=None)
    assert guard["state"] == "RANGE_UNKNOWN"
    assert guard["hard_block"] is False


def test_reported_range_and_freak_tick_fail_closed_when_price_is_impossible():
    extracted = extract_kite_price_range({"lower_circuit_limit": 90, "upper_circuit_limit": 110})
    assert extracted["status"] == "KNOWN"
    guard = freak_tick_guard(
        last_price=120,
        previous_accepted_price=100,
        lower_limit=90,
        upper_limit=110,
    )
    assert guard["state"] == "FREAK_TICK_SUSPECT"
    assert guard["hard_block"] is True
    assert guard["requires_confirmation"] is True


def test_market_halt_threshold_is_not_treated_as_confirmed_halt():
    potential = market_halt_guard(index_move_pct=-10.5, halt_confirmed=False)
    assert potential["state"] == "POTENTIAL_MARKET_WIDE_CIRCUIT"
    assert potential["hard_block_new_entries"] is False
    confirmed = market_halt_guard(index_move_pct=-10.5, halt_confirmed=True, official_state="HALTED")
    assert confirmed["state"] == "MARKET_HALT_CONFIRMED"
    assert confirmed["hard_block_new_entries"] is True


def test_position_guardian_intraday_hard_exit_outranks_everything():
    result = assess_open_trade_risk(
        _trade(),
        current_price=102,
        evaluated_at=datetime(2026, 8, 25, 15, 15, tzinfo=IST),
    )
    assert result["state"] == "HARD_EXIT_REQUIRED_BY_INTRADAY_POLICY"
    assert result["priority"] == "CRITICAL"
    assert result["order_execution_allowed"] is False


def test_position_guardian_short_stop_and_swing_event_review():
    short = assess_open_trade_risk(
        _trade(direction="SHORT", stop=105, target=90),
        current_price=106,
        evaluated_at=datetime(2026, 8, 25, 11, 0, tzinfo=IST),
    )
    assert short["state"] == "EXIT_REVIEW_STOP_BREACHED"

    swing = assess_open_trade_risk(
        _trade(mode="SWING", direction="LONG", stop=90, target=120),
        current_price=98,
        evaluated_at=datetime(2026, 8, 26, 11, 0, tzinfo=IST),
        event_risk="HIGH",
    )
    assert swing["state"] == "EARLY_EXIT_REVIEW"


def test_mtf_incremental_costs_use_funded_amount_and_versioned_broker_rules():
    costs = calculate_mtf_incremental_costs(
        entry_value=100000,
        exit_value=105000,
        funded_amount=80000,
        interest_days=10,
        purchase_date_count=1,
    )
    assert costs["costs"]["mtf_interest"] == 320.0
    assert costs["costs"]["mtf_buy_brokerage"] == 20.0
    assert costs["costs"]["mtf_sell_brokerage"] == 20.0
    assert costs["user_cash_contribution"] == 20000.0
    assert costs["normal_equity_statutory_costs_included"] is False
    assert costs["order_execution_allowed"] is False


def test_mtf_to_cnc_is_t_plus_one_and_cash_gated():
    same_day = mtf_to_cnc_conversion_review(
        purchase_date=date(2026, 8, 25),
        now=datetime(2026, 8, 25, 15, 0, tzinfo=IST),
        funded_amount_remaining=80000,
        available_cash=100000,
    )
    assert same_day["eligible_for_full_conversion"] is False
    assert "MTF_TO_CNC_NOT_ALLOWED_ON_PURCHASE_DAY" in same_day["reasons"]

    next_day = mtf_to_cnc_conversion_review(
        purchase_date=date(2026, 8, 25),
        now=datetime(2026, 8, 26, 15, 0, tzinfo=IST),
        funded_amount_remaining=80000,
        available_cash=100000,
    )
    assert next_day["eligible_for_full_conversion"] is True
    assert next_day["expected_processing_window"] == "SAME_DAY_SUBJECT_TO_BROKER_PROCESSING"
