import os
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.exchange_calendar import ingest_nse_cash_holiday_payload
from backend.tradebrain.live_advisory import evaluate_live_guarded_advisory

IST = ZoneInfo("Asia/Kolkata")

VALID_LONG = """Candidate Verdict: BUY CANDIDATE
Trade Mode: INTRADAY
Direction: LONG
Entry Price: 100
Stop-Loss: 99
Take-Profit: 102
"""


def _db():
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "live.db")
    ingest_nse_cash_holiday_payload(
        {"CM": [{"tradingDate": "26-Jan-2026", "description": "Republic Day"}]},
        db_path=path,
    )
    return tmp, path


def _base(path):
    return dict(
        ticker="BSE",
        exchange="NSE",
        final_trade_decision=VALID_LONG,
        evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
        quantity=10,
        crash_guard="NORMAL",
        broker_allows_trade=True,
        db_path=path,
    )


def test_missing_price_range_fails_closed():
    tmp, path = _db()
    try:
        result = evaluate_live_guarded_advisory(
            **_base(path), last_price=100.0, lower_limit=None, upper_limit=None
        )
        assert result["final_status"] == "BLOCK_PRICE_RANGE_UNVERIFIED"
        assert result["trade_authorization"] is False
    finally:
        tmp.cleanup()


def test_freak_tick_requires_confirmation_before_pass():
    tmp, path = _db()
    try:
        result = evaluate_live_guarded_advisory(
            **_base(path),
            last_price=104.0,
            previous_accepted_price=100.0,
            lower_limit=80.0,
            upper_limit=120.0,
            best_bid=103.9,
            best_ask=104.1,
        )
        assert result["final_status"] == "BLOCK_DATA_CONFIRMATION_REQUIRED"
    finally:
        tmp.cleanup()


def test_confirmed_halt_blocks_before_policy():
    tmp, path = _db()
    try:
        result = evaluate_live_guarded_advisory(
            **_base(path),
            last_price=100.0,
            lower_limit=80.0,
            upper_limit=120.0,
            halt_confirmed=True,
            official_halt_state="EXCHANGE_CONFIRMED",
        )
        assert result["final_status"] == "BLOCK_MARKET_HALT_CONFIRMED"
    finally:
        tmp.cleanup()


def test_normal_verified_market_state_can_reach_existing_advisory_pass():
    tmp, path = _db()
    try:
        result = evaluate_live_guarded_advisory(
            **_base(path),
            last_price=100.0,
            previous_accepted_price=99.9,
            lower_limit=80.0,
            upper_limit=120.0,
            best_bid=99.95,
            best_ask=100.05,
        )
        assert result["final_status"] == "ADVISORY_CANDIDATE_PASS"
        assert result["market_guard_checked_before_advisory"] is True
        assert result["market_guard"]["hard_block_new_entries"] is False
    finally:
        tmp.cleanup()
