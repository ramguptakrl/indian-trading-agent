import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.identity import ExchangeListing, can_merge_listings
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.soft_evidence import annotate_recommendation_payload, annotate_daily_verdict
from backend.tradebrain.store import (
    ensure_tradebrain_schema,
    record_plan_evaluation,
    record_plan_outcome,
    store_stats,
    upsert_listing,
)

IST = ZoneInfo("Asia/Kolkata")


class TradeBrainPolicyTests(unittest.TestCase):
    def test_valid_day_long_passes_hard_rules(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE",
                exchange="NSE",
                mode="DAY",
                direction="LONG",
                entry=2500,
                stop_loss=2475,
                take_profit=2525,
                evidence=["market-structure:test"],
                evaluated_at_ist=datetime(2026, 8, 21, 14, 0, tzinfo=IST),
            )
        )
        self.assertTrue(result.allowed_for_advisory)
        self.assertEqual(result.action, "PASS")
        self.assertFalse(result.order_execution_allowed)
        self.assertTrue(result.advisory_only)

    def test_day_entry_is_blocked_from_1510(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE",
                mode="DAY",
                direction="LONG",
                entry=2500,
                stop_loss=2475,
                take_profit=2525,
                evaluated_at_ist=datetime(2026, 8, 21, 15, 10, tzinfo=IST),
            )
        )
        self.assertFalse(result.allowed_for_advisory)
        self.assertEqual(result.action, "BLOCK")

    def test_day_position_is_hard_exit_at_1515(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE",
                mode="DAY",
                direction="LONG",
                entry=2500,
                stop_loss=2475,
                take_profit=2525,
                evaluated_at_ist=datetime(2026, 8, 21, 15, 15, tzinfo=IST),
            )
        )
        self.assertFalse(result.allowed_for_advisory)
        self.assertEqual(result.action, "HARD_EXIT")

    def test_swing_short_is_blocked(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE",
                mode="SWING_POSITION",
                direction="SHORT",
                entry=2500,
                stop_loss=2550,
                take_profit=2350,
                evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            )
        )
        self.assertFalse(result.allowed_for_advisory)
        self.assertIn("SWING_POSITION short", " ".join(result.hard_rule_failures))

    def test_severe_crash_guard_blocks_fresh_long(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE",
                mode="SWING_POSITION",
                direction="LONG",
                entry=2500,
                stop_loss=2450,
                take_profit=2650,
                crash_guard="SEVERE",
                evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            )
        )
        self.assertFalse(result.allowed_for_advisory)
        self.assertIn("Crash Guard", " ".join(result.hard_rule_failures))

    def test_invalid_long_geometry_is_blocked(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE",
                mode="DAY",
                direction="LONG",
                entry=2500,
                stop_loss=2510,
                take_profit=2550,
                evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            )
        )
        self.assertFalse(result.allowed_for_advisory)

    def test_low_swing_rr_is_wait_not_fake_rejection(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE",
                mode="SWING_POSITION",
                direction="LONG",
                entry=2500,
                stop_loss=2475,
                take_profit=2550,
                evidence=["support:test"],
                evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            )
        )
        self.assertTrue(result.allowed_for_advisory)
        self.assertEqual(result.action, "WAIT")
        self.assertEqual(result.preferred_reward_risk, 3.0)


class TradeBrainIdentityTests(unittest.TestCase):
    def test_matching_isin_can_merge_cross_exchange(self):
        nse = ExchangeListing(exchange="NSE", symbol="RELIANCE", isin="INE002A01018")
        bse = ExchangeListing(exchange="BSE", symbol="500325", isin="INE002A01018")
        self.assertTrue(can_merge_listings(nse, bse))

    def test_similar_names_without_isin_cannot_merge(self):
        nse = ExchangeListing(exchange="NSE", symbol="ABC", isin=None)
        bse = ExchangeListing(exchange="BSE", symbol="ABC LTD", isin=None)
        self.assertFalse(can_merge_listings(nse, bse))


class TradeBrainCompatibilityTests(unittest.TestCase):
    def test_legacy_probability_is_labelled_heuristic(self):
        result = annotate_recommendation_payload({"success_probability": 78, "ticker": "BSE"})
        self.assertEqual(result["success_probability"], 78)
        self.assertEqual(result["probability_status"], "HEURISTIC_NOT_LEARNED")
        self.assertFalse(result["trade_authorization"])

    def test_daily_verdict_is_context_only(self):
        result = annotate_daily_verdict({"verdict": "GREEN"})
        self.assertEqual(result["decision_scope"], "SOFT_MARKET_CONTEXT")
        self.assertFalse(result["trade_authorization"])
        self.assertTrue(result["requires_tradebrain_gate"])


class TradeBrainStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "tradebrain-test.db")
        ensure_tradebrain_schema(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_identity_store_maps_matching_isin_without_fuzzy_merge(self):
        nse = upsert_listing(
            ExchangeListing(exchange="NSE", symbol="RELIANCE", isin="INE002A01018"),
            listing_name="Reliance Industries",
            db_path=self.db_path,
        )
        bse = upsert_listing(
            ExchangeListing(exchange="BSE", symbol="500325", isin="INE002A01018"),
            listing_name="Reliance Industries",
            db_path=self.db_path,
        )
        stats = store_stats(self.db_path)
        self.assertTrue(nse["identity_verified_for_merge"])
        self.assertEqual(nse["issuer_entity_id"], bse["issuer_entity_id"])
        self.assertEqual(stats["tb_canonical_securities"], 1)
        self.assertEqual(stats["tb_exchange_listings"], 2)

    def test_plan_evaluation_and_outcome_are_persisted(self):
        plan = TradePlan(
            ticker="BSE",
            mode="DAY",
            direction="LONG",
            entry=2500,
            stop_loss=2475,
            take_profit=2525,
            evidence=["test:evidence"],
            evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
        )
        gate = evaluate_trade_plan(plan)
        plan_id = record_plan_evaluation(plan, gate, db_path=self.db_path)
        record_plan_outcome(
            plan_id,
            outcome="TP_FIRST",
            exit_price=2525,
            mfe_pct=1.2,
            mae_pct=-0.3,
            r_multiple=1.0,
            time_to_event_minutes=47,
            db_path=self.db_path,
        )
        stats = store_stats(self.db_path)
        self.assertEqual(stats["tb_trade_plan_evaluations"], 1)
        self.assertEqual(stats["tb_trade_plan_outcomes"], 1)


if __name__ == "__main__":
    unittest.main()
