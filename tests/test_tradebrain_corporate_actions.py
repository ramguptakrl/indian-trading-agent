from backend.tradebrain.corporate_actions import corporate_action_context, normalize_corporate_action


def test_dividend_keeps_explicit_dates_and_amount_only():
    event = {
        "event_id": "evt-div",
        "category": "DIVIDEND",
        "subject": "Final dividend of Rs. 12.50 per equity share",
        "details": "Record date: 18-09-2026. Ex-date: 17-09-2026. Payment date: 30-09-2026.",
        "announced_at": "2026-08-25T10:00:00+00:00",
    }
    action = normalize_corporate_action(event)
    assert action is not None
    assert action["action_type"] == "DIVIDEND"
    assert action["cash_dividend_per_share"] == 12.5
    assert action["ex_date"] == "2026-09-17"
    assert action["record_date"] == "2026-09-18"
    assert action["payment_date"] == "2026-09-30"
    assert action["cash_amount_inferred_from_percent"] is False


def test_dividend_never_guesses_ex_date_from_record_date():
    event = {
        "event_id": "evt-div-record-only",
        "category": "DIVIDEND",
        "subject": "Dividend of 250%",
        "details": "Record date is 18 September 2026",
    }
    action = normalize_corporate_action(event)
    assert action is not None
    assert action["record_date"] == "2026-09-18"
    assert action["ex_date"] is None
    assert action["dividend_percent_stated"] == 250.0
    assert action["cash_dividend_per_share"] is None
    assert action["ex_date_inferred_from_record_date"] is False


def test_split_face_value_conversion_produces_adjustment_context():
    event = {
        "event_id": "evt-split",
        "category": "CORPORATE_ACTION",
        "subject": "Sub-division of equity shares",
        "details": (
            "Stock split: face value of Rs. 10 per equity share into equity shares "
            "of face value of Rs. 2 each. Ex-date: 04-Nov-2026. Record date: 05-Nov-2026."
        ),
    }
    action = normalize_corporate_action(event)
    assert action is not None
    assert action["action_type"] == "STOCK_SPLIT"
    assert action["share_multiplier"] == 5.0
    assert action["raw_price_adjustment_factor"] == 0.2
    assert action["ratio_basis"] == "EXPLICIT_FACE_VALUE_CONVERSION"
    assert action["ex_date"] == "2026-11-04"
    assert action["raw_price_series_structural_break"] is True


def test_ex_date_context_marks_raw_gap_non_comparable():
    events = [
        {
            "event_id": "evt-div",
            "category": "DIVIDEND",
            "subject": "Dividend of INR 8 per share",
            "details": "Ex-dividend date: 17/09/2026; record date: 18/09/2026",
        }
    ]
    context = corporate_action_context(events, session_date="2026-09-17")
    assert context["dividend_ex_date"] is True
    assert context["mechanical_gap_risk"] is True
    assert context["raw_overnight_gap_comparable"] is False
    assert context["requires_adjusted_or_event_aware_return_logic"] is True


def test_record_date_without_ex_date_does_not_block_gap_by_guess():
    events = [
        {
            "event_id": "evt-record-only",
            "category": "DIVIDEND",
            "subject": "Dividend declared",
            "details": "Record date: 18-09-2026",
        }
    ]
    context = corporate_action_context(events, session_date="2026-09-18")
    assert context["record_date_actions"]
    assert context["known_ex_date_event"] is False
    assert context["mechanical_gap_risk"] is False
    assert context["raw_overnight_gap_comparable"] is True
    assert context["unknown_ex_date_is_not_guessed"] is True
