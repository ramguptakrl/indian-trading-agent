import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.identity import ExchangeListing, can_merge_listings
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.soft_evidence import annotate_recommendation_payload, annotate_daily_verdict

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


if __name__ == "__main__":
    unittest.main()
