import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from backend.tradebrain.corporate_event_store import bulk_upsert_events
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series, upsert_bars
from backend.tradebrain.mtf_replay import evaluate_swing_mtf_replay, list_mtf_replays
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.store import record_plan_evaluation, upsert_listing


class MtfStrictReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tradebrain.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited",
            security_name="BSE Limited",
            listing_status="ACTIVE",
            source_key="TEST_MASTER",
            source_timestamp="2026-08-01T00:00:00+00:00",
            db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE", symbol="BSE", source_key="TEST_AUDITED_VENDOR",
            source_symbol="NSE:BSE", base_interval="5m", db_path=self.db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self, *, target=115.0, stop=95.0, evaluated="2026-08-21T09:15:00+05:30"):
        plan = TradePlan(
            ticker="BSE",
            exchange="NSE",
            mode="SWING",
            direction="LONG",
            entry=100.0,
            stop_loss=stop,
            take_profit=target,
            quantity=100,
            crash_guard="NORMAL",
            broker_allows_trade=True,
            evidence=["mtf-replay-test"],
            evaluated_at_ist=datetime.fromisoformat(evaluated),
            swing_funding="MTF",
            mtf_eligible_verified=True,
            funded_amount=5000.0,
            mtf_interest_days=3,
        )
        gate = evaluate_trade_plan(plan, db_path=self.db)
        return record_plan_evaluation(plan, gate, db_path=self.db)

    def _bar(self, opened: datetime, *, o=100.0, h=102.0, l=99.0, c=101.0):
        return {
            "ts_open": opened.isoformat(),
            "ts_close": (opened + timedelta(minutes=5)).isoformat(),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 1000,
            "source_timestamp": opened.isoformat(),
            "is_final": True,
            "quality_flags": [],
        }

    def test_tp_replay_adds_net_mtf_economics_and_persists(self):
        plan_id = self._plan()
        friday = datetime(2026, 8, 21, 3, 45, tzinfo=timezone.utc)
        monday = datetime(2026, 8, 24, 3, 45, tzinfo=timezone.utc)
        upsert_bars(
            self.series["series_id"],
            "5m",
            [
                self._bar(friday, h=102, l=99, c=101),
                self._bar(friday + timedelta(minutes=5), h=104, l=100, c=103),
                self._bar(monday, h=116, l=108, c=115),
            ],
            source_key="TEST_AUDITED_VENDOR",
            db_path=self.db,
        )

        result = evaluate_swing_mtf_replay(
            plan_id,
            series_id=self.series["series_id"],
            quantity=100,
            funded_amount=5000,
            interest_days=3,
            mtf_eligible_verified=True,
            interval="5m",
            as_of="2026-08-24T04:00:00+00:00",
            db_path=self.db,
        )
        self.assertEqual(result["status"], "MTF_ECONOMICS_COMPLETE")
        self.assertEqual(result["strict_outcome"], "TP_FIRST")
        self.assertGreater(result["gross_pnl"], result["net_pnl"])
        self.assertGreater(result["total_charges"], 0)
        self.assertGreater(result["mtf_interest"], 0)
        self.assertEqual(result["interest_days_source"], "EXPLICIT_CALLER_SCENARIO_NOT_GUESSED")
        self.assertFalse(result["trade_authorization"])
        saved = list_mtf_replays(plan_id=plan_id, db_path=self.db)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["replay_id"], result["replay_id"])

    def test_replay_refuses_to_guess_interest_days(self):
        plan_id = self._plan()
        with self.assertRaisesRegex(ValueError, "will not guess"):
            evaluate_swing_mtf_replay(
                plan_id,
                series_id=self.series["series_id"],
                quantity=100,
                funded_amount=5000,
                interest_days=0,
                mtf_eligible_verified=True,
                persist=False,
                db_path=self.db,
            )

    def test_unverified_mtf_eligibility_is_rejected(self):
        plan_id = self._plan()
        with self.assertRaisesRegex(ValueError, "eligibility"):
            evaluate_swing_mtf_replay(
                plan_id,
                series_id=self.series["series_id"],
                quantity=100,
                funded_amount=5000,
                interest_days=3,
                mtf_eligible_verified=False,
                persist=False,
                db_path=self.db,
            )

    def test_split_boundary_blocks_false_raw_price_stop_and_costing(self):
        plan_id = self._plan(target=120, stop=90)
        friday = datetime(2026, 8, 21, 3, 45, tzinfo=timezone.utc)
        monday = datetime(2026, 8, 24, 3, 45, tzinfo=timezone.utc)
        upsert_bars(
            self.series["series_id"],
            "5m",
            [
                self._bar(friday, h=102, l=99, c=101),
                self._bar(friday + timedelta(minutes=5), h=104, l=98, c=102),
                # 2:1 split raw scale. Without era protection this would look like a huge SL breach.
                self._bar(monday, o=51, h=53, l=49, c=52),
            ],
            source_key="TEST_AUDITED_VENDOR",
            db_path=self.db,
        )
        bulk_upsert_events([
            {
                "event_id": "split-replay",
                "source_key": "BSE_OFFICIAL_TEST",
                "exchange": "NSE",
                "source_event_id": "split-replay",
                "event_fingerprint": "fp-split-replay",
                "listing_symbol": "BSE",
                "isin": "INE118H01025",
                "company_name": "BSE Limited",
                "subject": "Stock split: face value of Rs 2 into face value of Rs 1. Ex-date 24-Aug-2026.",
                "details": "Stock split: face value of Rs 2 into face value of Rs 1. Ex-date 24-Aug-2026.",
                "category": "CORPORATE_ACTION",
                "source_category": "Corporate Actions",
                "importance": "HIGH",
                "importance_basis": "test",
                "classification_version": "test-v1",
                "announced_at": "2026-08-18T06:00:00+00:00",
                "source_url": "https://www.bseindia.com/",
                "raw_item_sha256": "sha-split-replay",
                "source_critical": True,
                "received_at": "2026-08-18T06:00:00+00:00",
                "raw_payload": {},
            }
        ], db_path=self.db)

        result = evaluate_swing_mtf_replay(
            plan_id,
            series_id=self.series["series_id"],
            quantity=100,
            funded_amount=5000,
            interest_days=3,
            mtf_eligible_verified=True,
            interval="5m",
            as_of="2026-08-24T04:00:00+00:00",
            persist=False,
            db_path=self.db,
        )
        self.assertEqual(result["status"], "RAW_PRICE_CROSSES_COMPARABILITY_ERA")
        self.assertIsNone(result["economics"])
        self.assertGreaterEqual(len(result["price_era_ids"]), 2)
        self.assertIn("basis adjustment", result["reason"])


if __name__ == "__main__":
    unittest.main()
