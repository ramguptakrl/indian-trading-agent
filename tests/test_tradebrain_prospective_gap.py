from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series, upsert_bars
from backend.tradebrain.prospective_gap import collect_prospective_gap_observations
from backend.tradebrain.store import upsert_listing

IST = ZoneInfo("Asia/Kolkata")


class ProspectiveGapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "prospective.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited", listing_status="ACTIVE",
            source_key="TEST_IDENTITY", source_timestamp="2026-08-01T00:00:00+00:00", db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE", symbol="BSE", source_key="TEST_VENDOR", source_symbol="BSE.NS",
            price_mode="RAW_UNADJUSTED", base_interval="5m", source_metadata={"official": False}, db_path=self.db,
        )
        self.sid = self.series["series_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def _daily(self, local_day: datetime, o, h, l, c, era="e1"):
        opened = local_day.replace(hour=9, minute=15, second=0, microsecond=0).astimezone(timezone.utc)
        return {
            "ts_open": opened.isoformat(), "ts_close": (opened + timedelta(hours=6, minutes=15)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": 1000,
            "is_final": True, "era_id": era,
        }

    def _session_5m(self, local_day: datetime, *, gap_open=102.0, confirm=True):
        bars = []
        start = local_day.replace(hour=9, minute=15, second=0, microsecond=0)
        for i in range(72):  # through the 15:15 hard-exit close
            opened_local = start + timedelta(minutes=5 * i)
            opened = opened_local.astimezone(timezone.utc)
            if i < 9:
                o = gap_open + i * 0.08
                c = o + (0.05 if confirm else -0.20)
                low = 101.6 if confirm else (99.8 if i == 4 else min(o, c) - 0.05)
                high = max(o, c) + 0.08
            elif i == 9:  # 10:00 entry bar
                o = 102.80 if confirm else 100.80
                c = o + 0.05
                low = o - 0.10
                high = o + 0.10
            elif i == 10 and confirm:
                # First-window stop is 101.6, so risk=1.2 and target=104.0.
                o = 102.85
                c = 103.9
                low = 102.7
                high = 104.1
            else:
                o = 102.9 if confirm else 100.9
                c = o
                low = o - 0.10
                high = o + 0.10
            bars.append({
                "ts_open": opened.isoformat(), "ts_close": (opened + timedelta(minutes=5)).isoformat(),
                "open": o, "high": high, "low": low, "close": c, "volume": 100,
                "is_final": True, "era_id": "e1",
            })
        return bars

    def test_pre_freeze_sessions_never_count(self):
        day1 = datetime(2026, 8, 20, tzinfo=IST)
        day2 = datetime(2026, 8, 21, tzinfo=IST)
        daily = [self._daily(day1, 100, 101, 99, 100), self._daily(day2, 102, 103, 101, 102)]
        upsert_bars(self.sid, "1d", daily, source_key="TEST_VENDOR", db_path=self.db)
        upsert_bars(self.sid, "5m", self._session_5m(day2), source_key="TEST_VENDOR", db_path=self.db)
        out = collect_prospective_gap_observations(
            self.sid, as_of=daily[-1]["ts_close"], require_verified_calendar=False, persist=False, db_path=self.db,
        )
        self.assertEqual(out["eligible_observations"], 0)
        self.assertEqual(out["summary"]["decision"], "NEEDS_MORE_DATA")

    def test_post_freeze_confirmed_gap_creates_benchmark_and_challenger(self):
        prev_day = datetime(2026, 8, 21, tzinfo=IST)
        future_day = datetime(2026, 8, 24, tzinfo=IST)
        daily = [self._daily(prev_day, 99, 101, 98, 100), self._daily(future_day, 102, 105, 101.5, 104)]
        upsert_bars(self.sid, "1d", daily, source_key="TEST_VENDOR", db_path=self.db)
        bars = self._session_5m(future_day, confirm=True)
        upsert_bars(self.sid, "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        out = collect_prospective_gap_observations(
            self.sid, as_of=bars[-1]["ts_close"], require_verified_calendar=False, persist=False, db_path=self.db,
        )
        self.assertEqual(out["eligible_observations"], 1)
        item = out["observations"][0]
        self.assertTrue(item["confirmation_passed"])
        self.assertTrue(item["benchmark"]["entered"])
        self.assertTrue(item["challenger"]["entered"])
        self.assertEqual(item["benchmark"]["outcome"], "TP_FIRST")
        self.assertEqual(item["challenger"]["outcome"], "TP_FIRST")
        self.assertFalse(item["trade_authorization"])
        self.assertFalse(item["order_execution_allowed"])

    def test_failed_confirmation_becomes_no_trade_not_forced_direction(self):
        prev_day = datetime(2026, 8, 21, tzinfo=IST)
        future_day = datetime(2026, 8, 24, tzinfo=IST)
        daily = [self._daily(prev_day, 99, 101, 98, 100), self._daily(future_day, 102, 103, 99, 101)]
        upsert_bars(self.sid, "1d", daily, source_key="TEST_VENDOR", db_path=self.db)
        bars = self._session_5m(future_day, confirm=False)
        upsert_bars(self.sid, "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        out = collect_prospective_gap_observations(
            self.sid, as_of=bars[-1]["ts_close"], require_verified_calendar=False, persist=False, db_path=self.db,
        )
        self.assertEqual(out["eligible_observations"], 1)
        item = out["observations"][0]
        self.assertFalse(item["confirmation_passed"])
        self.assertTrue(item["benchmark"]["entered"])
        self.assertFalse(item["challenger"]["entered"])
        self.assertEqual(item["challenger"]["outcome"], "NO_TRADE")


if __name__ == "__main__":
    unittest.main()
