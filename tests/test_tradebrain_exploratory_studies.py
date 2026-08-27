from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.tradebrain.exploratory_studies import opening_gap_exploration
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series, upsert_bars
from backend.tradebrain.store import upsert_listing

IST = ZoneInfo("Asia/Kolkata")


class OpeningGapExplorationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "gap.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited", listing_status="ACTIVE",
            source_key="TEST_IDENTITY", source_timestamp="2026-01-01T00:00:00+00:00", db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE", symbol="BSE", source_key="TEST_VENDOR", source_symbol="BSE.NS",
            price_mode="RAW_UNADJUSTED", base_interval="1d", source_metadata={"official": False}, db_path=self.db,
        )
        self.sid = self.series["series_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rows):
        upsert_bars(self.sid, "1d", rows, source_key="TEST_VENDOR", db_path=self.db)

    def test_gap_up_and_down_definitions_are_directional(self):
        start = datetime(2026, 1, 1, 9, 15, tzinfo=IST).astimezone(timezone.utc)
        rows = [
            {"ts_open": start.isoformat(), "ts_close": (start+timedelta(hours=6, minutes=15)).isoformat(), "open":100,"high":101,"low":99,"close":100,"volume":1,"is_final":True,"era_id":"e1"},
            # +2% gap; fills prev close and closes below open => reversal
            {"ts_open": (start+timedelta(days=1)).isoformat(), "ts_close": (start+timedelta(days=1,hours=6,minutes=15)).isoformat(), "open":102,"high":103,"low":99.5,"close":101,"volume":1,"is_final":True,"era_id":"e1"},
            # -2.97% gap from 101; fills prev close and closes above open => reversal
            {"ts_open": (start+timedelta(days=2)).isoformat(), "ts_close": (start+timedelta(days=2,hours=6,minutes=15)).isoformat(), "open":98,"high":102,"low":97,"close":100,"volume":1,"is_final":True,"era_id":"e1"},
        ]
        self._write(rows)
        out = opening_gap_exploration(self.sid, thresholds_pct=(1.0,), as_of=rows[-1]["ts_close"], db_path=self.db)
        up = out["cohorts"]["1.0"]["GAP_UP"]
        down = out["cohorts"]["1.0"]["GAP_DOWN"]
        self.assertEqual(up["n"], 1)
        self.assertEqual(up["filled_anytime"], 1)
        self.assertEqual(up["closed_reversed_vs_gap"], 1)
        self.assertEqual(down["n"], 1)
        self.assertEqual(down["filled_anytime"], 1)
        self.assertEqual(down["closed_reversed_vs_gap"], 1)
        self.assertTrue(out["interpretation_contract"]["exploratory_only"])
        self.assertFalse(out["interpretation_contract"]["eligible_for_direct_phase5_promotion"])

    def test_cross_era_gap_is_excluded(self):
        start = datetime(2026, 1, 1, 9, 15, tzinfo=IST).astimezone(timezone.utc)
        rows = [
            {"ts_open": start.isoformat(), "ts_close": (start+timedelta(hours=6, minutes=15)).isoformat(), "open":100,"high":101,"low":99,"close":100,"volume":1,"is_final":True,"era_id":"e1"},
            {"ts_open": (start+timedelta(days=1)).isoformat(), "ts_close": (start+timedelta(days=1,hours=6,minutes=15)).isoformat(), "open":120,"high":121,"low":119,"close":120,"volume":1,"is_final":True,"era_id":"e2"},
        ]
        self._write(rows)
        out = opening_gap_exploration(self.sid, thresholds_pct=(0.5,), as_of=rows[-1]["ts_close"], db_path=self.db)
        self.assertEqual(out["cross_price_era_transitions_excluded"], 1)
        self.assertEqual(out["cohorts"]["0.5"]["GAP_UP"]["n"], 0)
        self.assertEqual(out["cohorts"]["0.5"]["GAP_DOWN"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
