from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.tradebrain.corporate_event_store import bulk_upsert_events
from backend.tradebrain.focus_lab import (
    classify_instrument_regime,
    crash_guard_calibration,
    evaluate_plan_replay_outcome,
    event_category_relevance,
    focus_cohort_report,
    study_level_reliability,
)
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series, upsert_bars
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.store import record_plan_evaluation, record_plan_outcome, upsert_listing

IST = ZoneInfo("Asia/Kolkata")


class Phase4Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tradebrain.db")
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited",
            security_name="BSE Limited",
            listing_status="ACTIVE",
            source_key="TEST_MASTER",
            source_timestamp="2026-08-21T00:00:00+00:00",
            db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE",
            symbol="BSE",
            source_key="TEST_VENDOR",
            source_symbol="BSE.NS",
            base_interval="5m",
            db_path=self.db,
        )

    def tearDown(self):
        os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        self.tmp.cleanup()

    def bar(self, opened, closed, o=100, h=102, l=99, c=101, v=1000):
        return {
            "ts_open": opened,
            "ts_close": closed,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "source_timestamp": opened,
            "is_final": True,
            "quality_flags": [],
        }

    def seed_plan(
        self,
        *,
        evaluated="2026-08-21T09:15:00+05:30",
        mode="DAY",
        direction="LONG",
        entry=100,
        stop=95,
        target=105,
        crash_guard="NORMAL",
    ):
        plan = TradePlan(
            ticker="BSE",
            exchange="NSE",
            mode=mode,
            direction=direction,
            entry=entry,
            stop_loss=stop,
            take_profit=target,
            crash_guard=crash_guard,
            broker_allows_trade=True,
            evidence=["phase4-test"],
            evaluated_at_ist=datetime.fromisoformat(evaluated),
        )
        gate = evaluate_trade_plan(plan)
        return record_plan_evaluation(plan, gate, db_path=self.db)

    def seed_daily_trend(self, count=60, start_close=100.0):
        bars = []
        start = datetime(2026, 5, 1, 3, 45, tzinfo=timezone.utc)
        for i in range(count):
            opened = start + timedelta(days=i)
            close = start_close + i
            bars.append(
                self.bar(
                    opened.isoformat(),
                    (opened + timedelta(hours=6, minutes=15)).isoformat(),
                    o=close - 0.5,
                    h=close + 1,
                    l=close - 1,
                    c=close,
                    v=10000,
                )
            )
        upsert_bars(self.series["series_id"], "1d", bars, source_key="TEST_VENDOR", db_path=self.db)
        return bars


class StrictReplayOutcomeTests(Phase4Base):
    def test_tp_first_is_resolved_only_after_entry_bar(self):
        plan_id = self.seed_plan()
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", h=102, l=99, c=101),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", h=104, l=98, c=103),
            self.bar("2026-08-21T03:55:00+00:00", "2026-08-21T04:00:00+00:00", h=106, l=99, c=105),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = evaluate_plan_replay_outcome(
            plan_id, series_id=self.series["series_id"], interval="5m",
            as_of="2026-08-21T04:00:00+00:00", db_path=self.db,
        )
        self.assertEqual(result["outcome"], "TP_FIRST")
        self.assertEqual(result["exit_price"], 105.0)
        self.assertEqual(result["r_multiple"], 1.0)
        self.assertGreaterEqual(result["mfe_pct"], 5.0)

    def test_entry_bar_exit_touch_is_ambiguous_not_optimistic(self):
        plan_id = self.seed_plan()
        upsert_bars(
            self.series["series_id"], "5m",
            [self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", h=106, l=99, c=104)],
            source_key="TEST_VENDOR", db_path=self.db,
        )
        result = evaluate_plan_replay_outcome(
            plan_id, series_id=self.series["series_id"], interval="5m",
            as_of="2026-08-21T03:50:00+00:00", db_path=self.db,
        )
        self.assertEqual(result["outcome"], "AMBIGUOUS")
        self.assertEqual(result["ambiguity_reason"], "ENTRY_BAR_EXIT_THRESHOLD_TOUCH")

    def test_later_bar_touching_tp_and_sl_is_ambiguous(self):
        plan_id = self.seed_plan()
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", h=102, l=99),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", h=106, l=94),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = evaluate_plan_replay_outcome(
            plan_id, series_id=self.series["series_id"], interval="5m",
            as_of="2026-08-21T03:55:00+00:00", db_path=self.db,
        )
        self.assertEqual(result["outcome"], "AMBIGUOUS")
        self.assertEqual(result["ambiguity_reason"], "TP_AND_SL_SAME_BAR_ORDER_UNKNOWN")

    def test_as_of_hides_future_tp_bar(self):
        plan_id = self.seed_plan()
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", h=102, l=99),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", h=103, l=99),
            self.bar("2026-08-21T03:55:00+00:00", "2026-08-21T04:00:00+00:00", h=106, l=99),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = evaluate_plan_replay_outcome(
            plan_id, series_id=self.series["series_id"], interval="5m",
            as_of="2026-08-21T03:57:00+00:00", db_path=self.db,
        )
        self.assertEqual(result["outcome"], "NEITHER")
        self.assertLessEqual(result["observation_end"], "2026-08-21T03:55:00+00:00")

    def test_day_hard_exit_cutoff_blocks_later_threshold_from_replay(self):
        plan_id = self.seed_plan(evaluated="2026-08-21T14:55:00+05:30")
        bars = [
            self.bar("2026-08-21T09:25:00+00:00", "2026-08-21T09:30:00+00:00", h=102, l=99),
            self.bar("2026-08-21T09:30:00+00:00", "2026-08-21T09:35:00+00:00", h=103, l=98),
            self.bar("2026-08-21T09:45:00+00:00", "2026-08-21T09:50:00+00:00", h=110, l=99),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = evaluate_plan_replay_outcome(
            plan_id, series_id=self.series["series_id"], interval="5m",
            as_of="2026-08-21T10:00:00+00:00", db_path=self.db,
        )
        self.assertEqual(result["outcome"], "NEITHER")
        self.assertLessEqual(result["observation_end"], "2026-08-21T09:45:00+00:00")

    def test_hypothetical_replay_does_not_overwrite_manual_outcome(self):
        plan_id = self.seed_plan()
        record_plan_outcome(plan_id, outcome="MANUAL_REAL_WIN", exit_price=104, db_path=self.db)
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", h=102, l=99),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", h=106, l=99),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        evaluate_plan_replay_outcome(
            plan_id, series_id=self.series["series_id"], interval="5m",
            as_of="2026-08-21T03:55:00+00:00", db_path=self.db,
        )
        conn = sqlite3.connect(self.db)
        manual = conn.execute("SELECT outcome FROM tb_trade_plan_outcomes WHERE plan_id=?", (plan_id,)).fetchone()[0]
        replay = conn.execute("SELECT outcome FROM tb_replay_plan_outcomes WHERE plan_id=?", (plan_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(manual, "MANUAL_REAL_WIN")
        self.assertEqual(replay, "TP_FIRST")


class FocusLabResearchTests(Phase4Base):
    def test_regime_uses_only_daily_bars_completed_by_as_of(self):
        bars = self.seed_daily_trend(60)
        cutoff = bars[-1]["ts_close"]
        future_open = datetime.fromisoformat(bars[-1]["ts_open"]) + timedelta(days=1)
        future = self.bar(
            future_open.isoformat(), (future_open + timedelta(hours=6, minutes=15)).isoformat(),
            o=10, h=11, l=9, c=10,
        )
        upsert_bars(self.series["series_id"], "1d", [future], source_key="TEST_VENDOR", db_path=self.db)
        result = classify_instrument_regime(self.series["series_id"], as_of=cutoff, db_path=self.db)
        self.assertEqual(result["regime"], "TREND_UP")
        self.assertEqual(result["close"], 159.0)

    def test_cohort_and_crash_guard_keep_severe_as_counterfactual(self):
        normal_id = self.seed_plan(evaluated="2026-08-21T09:15:00+05:30", crash_guard="NORMAL")
        severe_id = self.seed_plan(evaluated="2026-08-21T09:30:00+05:30", crash_guard="SEVERE")
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", h=102, l=99),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", h=106, l=99),
            self.bar("2026-08-21T04:00:00+00:00", "2026-08-21T04:05:00+00:00", h=102, l=99),
            self.bar("2026-08-21T04:05:00+00:00", "2026-08-21T04:10:00+00:00", h=106, l=99),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        for pid in (normal_id, severe_id):
            evaluate_plan_replay_outcome(
                pid, series_id=self.series["series_id"], interval="5m",
                as_of="2026-08-21T04:10:00+00:00", db_path=self.db,
            )
        cohorts = focus_cohort_report(series_id=self.series["series_id"], interval="5m", db_path=self.db)
        crash = crash_guard_calibration(series_id=self.series["series_id"], interval="5m", db_path=self.db)
        self.assertEqual(cohorts["overall"]["n"], 2)
        self.assertIn("SEVERE", cohorts["cohorts"]["crash_guard"])
        self.assertEqual(crash["severe_counterfactual"]["resolved_n"], 1)
        self.assertIn("does not auto-relax", crash["interpretation_boundary"])

    def test_level_reliability_resolves_from_bars_after_touch_only(self):
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", h=100.2, l=99.8, c=100),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", h=101.0, l=99.8, c=100.8),
            self.bar("2026-08-21T03:55:00+00:00", "2026-08-21T04:00:00+00:00", h=101.1, l=100.2, c=101),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = study_level_reliability(
            series_id=self.series["series_id"], interval="5m", level_type="SUPPORT",
            level_price=100, tolerance_pct=0.2, reaction_pct=0.5, break_pct=0.3,
            horizon_bars=2, persist=False, db_path=self.db,
        )
        self.assertEqual(result["touch_episodes"], 1)
        self.assertEqual(result["outcomes"]["REACTION_FIRST"], 1)
        self.assertEqual(result["reaction_first_rate_resolved_pct"], 100.0)

    def test_event_category_relevance_uses_only_comparable_effects(self):
        base = {
            "source_key": "TEST_EVENTS", "exchange": "NSE", "event_fingerprint": "x",
            "listing_symbol": "BSE", "isin": "INE118H01025", "company_name": "BSE Limited",
            "details": None, "subcategory": None, "source_category": None,
            "importance": "HIGH", "importance_basis": "RULE_BASED_HEURISTIC",
            "classification_version": "test", "source_url": "https://nseindia.com/test", "attachment_url": None,
            "raw_artifact_id": None, "source_critical": False, "raw_payload": {},
        }
        events = []
        for idx, ret in enumerate((2.0, -1.0, None), start=1):
            announced = f"2026-08-{10+idx:02d}T10:00:00+00:00"
            events.append(dict(
                base,
                event_id=f"evt:phase4:{idx}", source_event_id=f"p4-{idx}", raw_item_sha256=f"p4-{idx}",
                event_fingerprint=f"p4-{idx}", subject="Quarterly results", category="FINANCIAL_RESULTS",
                announced_at=announced, received_at=announced,
            ))
        bulk_upsert_events(events, db_path=self.db)
        conn = sqlite3.connect(self.db)
        for idx, ret in enumerate((2.0, -1.0, None), start=1):
            conn.execute(
                """
                INSERT INTO tb_event_price_effects(
                    event_id, series_id, interval, horizon_sessions, anchor_bar_open,
                    anchor_price, end_bar_close, end_price, return_pct, mae_pct, mfe_pct,
                    bars_observed, method, computed_at
                ) VALUES (?, ?, '5m', 5, ?, 100, ?, ?, ?, 1.5, 2.5, 5, 'TEST', ?)
                """,
                (
                    f"evt:phase4:{idx}", self.series["series_id"], f"2026-08-{10+idx:02d}T10:05:00+00:00",
                    f"2026-08-{15+idx:02d}T10:05:00+00:00", 100 + (ret or 0), ret,
                    "2026-08-21T12:00:00+00:00",
                ),
            )
        conn.commit()
        conn.close()
        result = event_category_relevance(
            series_id=self.series["series_id"], horizon_sessions=5, db_path=self.db
        )
        category = result["categories"]["FINANCIAL_RESULTS"]
        self.assertEqual(category["events_total"], 3)
        self.assertEqual(category["events_comparable"], 2)
        self.assertEqual(category["positive_return_rate_pct"], 50.0)
        self.assertIn("association", result["causation_warning"])


if __name__ == "__main__":
    unittest.main()
