import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.tradebrain.exchange_calendar import (
    NSE_HOLIDAY_API,
    collect_nse_cash_calendar,
    ingest_nse_cash_holiday_payload,
    session_for_date,
    upsert_verified_session_override,
)
from backend.tradebrain.schedule import get_operating_mode

IST = ZoneInfo("Asia/Kolkata")


class _FakeCalendarResponse:
    def __init__(self, payload):
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _DirectOnlySession:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if url != NSE_HOLIDAY_API:
            raise AssertionError("Public HTML bootstrap should not be called when direct API succeeds")
        return _FakeCalendarResponse(self.payload)


class Phase8ExchangeCalendarTests(unittest.TestCase):
    PAYLOAD = {
        "CM": [
            {"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day"},
            {"tradingDate": "08-Nov-2026", "weekDay": "Sunday", "description": "Diwali Laxmi Pujan*"},
            {"tradingDate": "10-Nov-2026", "weekDay": "Tuesday", "description": "Diwali-Balipratipada"},
        ]
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        self.db_path = os.path.join(self.tmp.name, "phase8.db")
        ingest_nse_cash_holiday_payload(self.PAYLOAD, db_path=self.db_path)

    def tearDown(self):
        os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        self.tmp.cleanup()

    def test_direct_official_api_is_tried_before_html_bootstrap(self):
        session = _DirectOnlySession(self.PAYLOAD)
        with patch("backend.tradebrain.exchange_calendar.requests.Session", return_value=session):
            result = collect_nse_cash_calendar(db_path=self.db_path)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["transport"], "DIRECT_OFFICIAL_API")
        self.assertEqual(session.urls, [NSE_HOLIDAY_API])

    def test_official_holiday_is_verified_closed(self):
        day = session_for_date("2026-01-26", exchange="NSE", db_path=self.db_path)
        self.assertTrue(day["calendar_verified"])
        self.assertEqual(day["session_type"], "CLOSED")
        self.assertFalse(day["is_trading_session"])

    def test_regular_weekday_is_inferred_only_inside_verified_year(self):
        day = session_for_date("2026-01-27", exchange="NSE", db_path=self.db_path)
        self.assertTrue(day["calendar_verified"])
        self.assertEqual(day["session_type"], "REGULAR")
        self.assertEqual(day["open_time"], "09:15")
        self.assertEqual(day["close_time"], "15:30")

    def test_special_session_without_times_is_fail_closed(self):
        day = session_for_date("2026-11-08", exchange="NSE", db_path=self.db_path)
        self.assertEqual(day["session_type"], "SPECIAL_PENDING")
        self.assertFalse(day["timing_verified"])
        self.assertFalse(day["safe_to_open_new_intraday"])

    def test_uncovered_exchange_year_is_not_called_verified(self):
        day = session_for_date("2026-01-27", exchange="BSE", db_path=self.db_path)
        self.assertFalse(day["calendar_verified"])
        self.assertEqual(day["session_type"], "UNKNOWN")

    def test_official_bse_override_can_verify_special_session(self):
        day = upsert_verified_session_override(
            exchange="BSE", session_date="2026-11-08", session_type="SPECIAL_OPEN",
            source_url="https://www.bseindia.com/markets/MarketInfo/example.aspx",
            description="Verified Muhurat special session",
            open_time="18:00", close_time="19:00", source_sha256="a" * 64,
            db_path=self.db_path,
        )
        self.assertTrue(day["calendar_verified"])
        self.assertEqual(day["session_type"], "SPECIAL_OPEN")
        self.assertTrue(day["timing_verified"])

    def test_lookalike_override_domain_is_rejected(self):
        with self.assertRaises(ValueError):
            upsert_verified_session_override(
                exchange="NSE", session_date="2026-11-08", session_type="CLOSED",
                source_url="https://nseindia.com.evil.example/notice",
                description="fake", source_sha256="b" * 64, db_path=self.db_path,
            )

    def test_scheduler_uses_verified_holiday(self):
        result = get_operating_mode(
            datetime(2026, 1, 26, 10, 0, tzinfo=IST),
            exchange="NSE", db_path=self.db_path, require_verified_calendar=True,
        )
        self.assertTrue(result["calendar_verified"])
        self.assertEqual(result["mode"], "STUDY_REPLAY")
        self.assertEqual(result["intraday_trade_state"], "CLOSED")

    def test_scheduler_fail_closes_when_calendar_required_but_unknown(self):
        result = get_operating_mode(
            datetime(2026, 1, 27, 10, 0, tzinfo=IST),
            exchange="BSE", db_path=self.db_path, require_verified_calendar=True,
        )
        self.assertFalse(result["calendar_verified"])
        self.assertEqual(result["intraday_trade_state"], "CALENDAR_UNVERIFIED")
        self.assertEqual(result["mode"], "STUDY_REPLAY")


if __name__ == "__main__":
    unittest.main()
