from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.tradebrain.evidence_baseline import build_evidence_baseline, latest_evidence_baseline
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series, upsert_bars
from backend.tradebrain.store import upsert_listing

IST = ZoneInfo("Asia/Kolkata")


class EvidenceBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "evidence.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited", listing_status="ACTIVE",
            source_key="TEST_IDENTITY", source_timestamp="2026-01-01T00:00:00+00:00", db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE", symbol="BSE", source_key="TEST_VENDOR", source_symbol="BSE.NS",
            price_mode="RAW_UNADJUSTED", base_interval="1d",
            source_metadata={"official": False}, db_path=self.db,
        )
        self.sid = self.series["series_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_daily(self, n=60):
        start = datetime(2026, 1, 1, 9, 15, tzinfo=IST).astimezone(timezone.utc)
        bars = []
        for i in range(n):
            o = 100.0 + i
            c = o + (1.0 if i % 2 == 0 else -0.5)
            bars.append({
                "ts_open": (start + timedelta(days=i)).isoformat(),
                "ts_close": (start + timedelta(days=i, hours=6, minutes=15)).isoformat(),
                "open": o,
                "high": max(o, c) + 1.0,
                "low": min(o, c) - 1.0,
                "close": c,
                "volume": 1000 + i,
                "source_timestamp": (start + timedelta(days=i)).isoformat(),
                "is_final": True,
                "era_id": "era-a" if i < 30 else "era-b",
            })
        upsert_bars(self.sid, "1d", bars, source_key="TEST_VENDOR", db_path=self.db)
        return bars

    def _seed_full_5m_session(self):
        opened = datetime(2026, 2, 2, 9, 15, tzinfo=IST)
        bars = []
        for i in range(75):
            local = opened + timedelta(minutes=5 * i)
            utc = local.astimezone(timezone.utc)
            o = 150.0 + i * 0.02
            c = o + (0.03 if i % 2 == 0 else -0.01)
            bars.append({
                "ts_open": utc.isoformat(),
                "ts_close": (utc + timedelta(minutes=5)).isoformat(),
                "open": o,
                "high": max(o, c) + 0.05,
                "low": min(o, c) - 0.05,
                "close": c,
                "volume": 10000 + i,
                "source_timestamp": utc.isoformat(),
                "is_final": True,
                "era_id": "era-b",
            })
        upsert_bars(self.sid, "5m", bars, source_key="TEST_VENDOR", db_path=self.db)

    def test_cross_era_transition_is_excluded_and_report_is_non_authorizing(self):
        bars = self._seed_daily(60)
        self._seed_full_5m_session()
        report = build_evidence_baseline(
            self.sid, as_of=bars[-1]["ts_close"], persist=False, db_path=self.db,
        )
        self.assertEqual(report["daily"]["close_to_close_return_pct"]["n"], 58)
        self.assertEqual(report["daily"]["cross_price_era_transitions_excluded"], 1)
        self.assertEqual(report["intraday"]["full_regular_sessions"], 1)
        self.assertFalse(report["claims"]["strategy_edge_claimed"])
        self.assertFalse(report["claims"]["win_rate_claimed"])
        self.assertFalse(report["claims"]["trade_authorization"])
        self.assertFalse(report["claims"]["order_execution_allowed"])

    def test_as_of_cutoff_excludes_future_completed_bars(self):
        bars = self._seed_daily(60)
        cutoff = bars[54]["ts_close"]
        report = build_evidence_baseline(self.sid, as_of=cutoff, persist=False, db_path=self.db)
        self.assertEqual(report["coverage"]["daily_bars"], 55)
        self.assertEqual(report["daily"]["last_bar"], cutoff)
        self.assertEqual(report["regime_at_cutoff"]["bars"], 55)

    def test_persisted_baseline_is_content_hashed_and_retrievable(self):
        bars = self._seed_daily(60)
        report = build_evidence_baseline(self.sid, as_of=bars[-1]["ts_close"], persist=True, db_path=self.db)
        persistence = report["persistence"]
        self.assertTrue(persistence["run_id"].startswith("evidence:"))
        self.assertEqual(len(persistence["report_sha256"]), 64)
        latest = latest_evidence_baseline(self.sid, db_path=self.db)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["report"]["method_version"], report["method_version"])
        self.assertEqual(latest["report_sha256"], persistence["report_sha256"])


if __name__ == "__main__":
    unittest.main()
