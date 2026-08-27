from backend.tradebrain.signal_lifecycle import (
    apply_signal_lifecycle,
    get_current_signal,
    terminate_current_signal,
)


def _decision(mode: str, direction: str, entry: float = 3300.0) -> str:
    verdict = "BUY CANDIDATE" if direction == "LONG" else "SHORT CANDIDATE"
    stop = entry - 30 if direction == "LONG" else entry + 30
    target = entry + 60 if direction == "LONG" else entry - 60
    return "\n".join(
        [
            f"Candidate Verdict: {verdict}",
            f"Trade Mode: {mode}",
            f"Direction: {direction}",
            f"Entry Price: {entry}",
            f"Stop-Loss: {stop}",
            f"Take-Profit: {target}",
        ]
    )


def _advisory(at: str, status: str = "ADVISORY_CANDIDATE_PASS") -> dict:
    return {
        "ticker": "BSE",
        "exchange": "NSE",
        "evaluated_at_ist": at,
        "final_status": status,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def test_same_direction_refresh_reaffirms_instead_of_republishing(tmp_path):
    db = str(tmp_path / "lifecycle.db")
    first = apply_signal_lifecycle(
        _advisory("2026-08-26T10:00:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "LONG"),
        db_path=db,
    )
    second = apply_signal_lifecycle(
        _advisory("2026-08-26T10:05:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "LONG", 3305.0),
        db_path=db,
    )

    assert first["signal_lifecycle"]["action"] == "PUBLISH_NEW"
    assert first["signal_lifecycle"]["published_new_trade"] is True
    assert second["signal_lifecycle"]["action"] == "REAFFIRM_ACTIVE"
    assert second["signal_lifecycle"]["published_new_trade"] is False
    assert second["signal_lifecycle"]["fixed_trade_count_limit"] is False
    assert second["signal_lifecycle"]["active_plan_id"] == first["signal_lifecycle"]["active_plan_id"]


def test_single_opposite_refresh_is_suppressed_then_confirmed(tmp_path):
    db = str(tmp_path / "lifecycle.db")
    long_result = apply_signal_lifecycle(
        _advisory("2026-08-26T10:00:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "LONG"),
        db_path=db,
    )
    first_short = apply_signal_lifecycle(
        _advisory("2026-08-26T10:05:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "SHORT", 3280.0),
        db_path=db,
    )
    second_short = apply_signal_lifecycle(
        _advisory("2026-08-26T10:10:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "SHORT", 3275.0),
        db_path=db,
    )

    assert first_short["signal_lifecycle"]["action"] == "REVERSAL_PENDING_CONFIRMATION"
    assert first_short["signal_lifecycle"]["published_new_trade"] is False
    assert first_short["signal_lifecycle"]["active_plan_id"] == long_result["signal_lifecycle"]["active_plan_id"]
    assert second_short["signal_lifecycle"]["action"] == "PUBLISH_CONFIRMED_REVERSAL"
    assert second_short["signal_lifecycle"]["published_new_trade"] is True
    assert second_short["signal_lifecycle"]["active_direction"] == "SHORT"


def test_blocked_refresh_does_not_erase_active_plan(tmp_path):
    db = str(tmp_path / "lifecycle.db")
    first = apply_signal_lifecycle(
        _advisory("2026-08-26T10:00:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "LONG"),
        db_path=db,
    )
    blocked = apply_signal_lifecycle(
        _advisory("2026-08-26T10:05:00+05:30", "BLOCK_MARKET_GUARD"),
        final_trade_decision=_decision("INTRADAY", "SHORT", 3280.0),
        db_path=db,
    )

    assert blocked["signal_lifecycle"]["action"] == "NO_NEW_PUBLISHABLE_CANDIDATE"
    assert blocked["signal_lifecycle"]["active_plan_id"] == first["signal_lifecycle"]["active_plan_id"]
    assert get_current_signal("INTRADAY", db_path=db)["direction"] == "LONG"


def test_intraday_plan_expires_across_session_date_boundary(tmp_path):
    db = str(tmp_path / "lifecycle.db")
    first = apply_signal_lifecycle(
        _advisory("2026-08-26T14:00:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "LONG"),
        db_path=db,
    )
    next_day = apply_signal_lifecycle(
        _advisory("2026-08-27T09:30:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "LONG", 3340.0),
        db_path=db,
    )

    assert next_day["signal_lifecycle"]["action"] == "PUBLISH_NEW"
    assert next_day["signal_lifecycle"]["active_plan_id"] != first["signal_lifecycle"]["active_plan_id"]
    assert next_day["signal_lifecycle"]["active_trade_date"] == "2026-08-27"


def test_swing_plan_is_sticky_across_dates(tmp_path):
    db = str(tmp_path / "lifecycle.db")
    first = apply_signal_lifecycle(
        _advisory("2026-08-26T14:00:00+05:30"),
        final_trade_decision=_decision("SWING", "LONG"),
        db_path=db,
    )
    later = apply_signal_lifecycle(
        _advisory("2026-08-28T11:00:00+05:30"),
        final_trade_decision=_decision("SWING", "LONG", 3360.0),
        db_path=db,
    )

    assert later["signal_lifecycle"]["action"] == "REAFFIRM_ACTIVE"
    assert later["signal_lifecycle"]["active_plan_id"] == first["signal_lifecycle"]["active_plan_id"]


def test_no_fixed_trade_count_limit_after_explicit_terminal_event(tmp_path):
    db = str(tmp_path / "lifecycle.db")
    first = apply_signal_lifecycle(
        _advisory("2026-08-26T09:30:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "LONG"),
        db_path=db,
    )
    terminal = terminate_current_signal(
        "INTRADAY",
        reason="TARGET_HIT",
        evaluated_at="2026-08-26T10:00:00+05:30",
        db_path=db,
    )
    second = apply_signal_lifecycle(
        _advisory("2026-08-26T11:00:00+05:30"),
        final_trade_decision=_decision("INTRADAY", "SHORT", 3360.0),
        db_path=db,
    )

    assert terminal["terminated"] is True
    assert second["signal_lifecycle"]["action"] == "PUBLISH_NEW"
    assert second["signal_lifecycle"]["fixed_trade_count_limit"] is False
    assert second["signal_lifecycle"]["active_plan_id"] != first["signal_lifecycle"]["active_plan_id"]
