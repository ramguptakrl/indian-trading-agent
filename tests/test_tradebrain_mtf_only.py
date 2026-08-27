import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.advisory_pipeline import evaluate_final_advisory
from backend.tradebrain.equity_costs import calculate_equity_trade_costs, cost_profile
from backend.tradebrain.exchange_calendar import ingest_nse_cash_holiday_payload
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.swing_mtf import calculate_swing_mtf_trade_costs
from backend.tradebrain.trade_modes import product_boundary, to_swing_funding
from tradingagents.default_config import DEFAULT_CONFIG

IST = ZoneInfo("Asia/Kolkata")

SWING_LONG = """Candidate Verdict: BUY CANDIDATE
Trade Mode: SWING
Direction: LONG
Entry Price: 100
Stop-Loss: 98
Take-Profit: 108
"""


class TradeBrainMtfOnlyPolicyTests(unittest.TestCase):
    def test_product_boundary_exposes_mtf_as_only_active_swing_funding(self):
        boundary = product_boundary()
        self.assertEqual(boundary["active_swing_funding_modes"], ["MTF"])
        self.assertEqual(boundary["swing_funding_required"], "MTF")
        self.assertFalse(boundary["cnc_own_cash_active_swing_allowed"])
        self.assertIn("CNC_OWN_CASH", boundary["legacy_readable_swing_funding_labels"])

    def test_default_agent_config_matches_mtf_only_product_boundary(self):
        self.assertEqual(DEFAULT_CONFIG["swing_funding"], "ZERODHA_MTF_ONLY")
        self.assertEqual(DEFAULT_CONFIG["swing_funding_modes"], ["MTF"])
        self.assertEqual(DEFAULT_CONFIG["advisory_funding_modes"], ["MTF"])
        self.assertFalse(DEFAULT_CONFIG["cnc_own_cash_active_swing_allowed"])
        self.assertIn("CNC_OWN_CASH", DEFAULT_CONFIG["legacy_readable_swing_funding_modes"])

    def test_base_equity_cost_profile_does_not_grant_own_cash_swing_permission(self):
        profile = cost_profile()
        self.assertFalse(profile["mtf_enabled"])
        self.assertEqual(profile["component_scope"], "BASE_RESIDENT_EQUITY_TRANSACTION_COSTS_ONLY")
        self.assertEqual(profile["swing_funding"], "NOT_APPLICABLE_BASE_COMPONENT")
        self.assertNotEqual(profile["swing_funding"], "OWN_CASH_ONLY")

    def test_legacy_cnc_label_remains_readable_but_is_blocked_for_active_swing(self):
        self.assertEqual(to_swing_funding("CNC_OWN_CASH"), "CNC_OWN_CASH")
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE", exchange="NSE", mode="SWING", direction="LONG",
                entry=100, stop_loss=98, take_profit=108, quantity=100,
                swing_funding="CNC_OWN_CASH",
                evidence=["mtf-only:test"],
                evaluated_at_ist=datetime(2026, 8, 25, 12, 0, tzinfo=IST),
            )
        )
        self.assertFalse(result.allowed_for_advisory)
        self.assertEqual(result.action, "BLOCK")
        self.assertIn("requires Zerodha MTF funding", " ".join(result.hard_rule_failures))

    def test_missing_swing_funding_can_only_wait_never_pass(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE", exchange="NSE", mode="SWING", direction="LONG",
                entry=100, stop_loss=98, take_profit=108,
                evidence=["mtf-only:test"],
                evaluated_at_ist=datetime(2026, 8, 25, 12, 0, tzinfo=IST),
            )
        )
        self.assertTrue(result.allowed_for_advisory)
        self.assertEqual(result.action, "WAIT")
        self.assertTrue(result.funding_review_required)

    def test_verified_mtf_swing_can_pass_hard_and_soft_rules(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE", exchange="NSE", mode="SWING", direction="LONG",
                entry=100, stop_loss=98, take_profit=108, quantity=100,
                swing_funding="MTF", mtf_eligible_verified=True,
                funded_amount=8000, mtf_interest_days=5,
                evidence=["mtf-only:test"],
                evaluated_at_ist=datetime(2026, 8, 25, 12, 0, tzinfo=IST),
            )
        )
        self.assertTrue(result.allowed_for_advisory)
        self.assertEqual(result.action, "PASS")
        self.assertEqual(result.swing_funding, "MTF")
        self.assertEqual(result.mtf_interest_days, 5)

    def test_mtf_unverified_or_invalid_funded_amount_blocks(self):
        unverified = evaluate_trade_plan(
            TradePlan(
                ticker="BSE", mode="SWING", direction="LONG",
                entry=100, stop_loss=98, take_profit=108, quantity=100,
                swing_funding="MTF", mtf_eligible_verified=False,
                funded_amount=8000, mtf_interest_days=5,
            )
        )
        self.assertEqual(unverified.action, "BLOCK")
        too_large = evaluate_trade_plan(
            TradePlan(
                ticker="BSE", mode="SWING", direction="LONG",
                entry=100, stop_loss=98, take_profit=108, quantity=100,
                swing_funding="MTF", mtf_eligible_verified=True,
                funded_amount=10000, mtf_interest_days=5,
            )
        )
        self.assertEqual(too_large.action, "BLOCK")
        self.assertIn("below the modeled entry notional", " ".join(too_large.hard_rule_failures))


class TradeBrainMtfOnlyEconomicsTests(unittest.TestCase):
    def test_combined_swing_costs_add_mtf_financing_to_base_equity_costs(self):
        base = calculate_equity_trade_costs(
            mode="SWING", exchange="NSE", direction="LONG",
            entry_price=1000, exit_price=1050, quantity=100,
        )
        mtf = calculate_swing_mtf_trade_costs(
            exchange="NSE", entry_price=1000, exit_price=1050, quantity=100,
            funded_amount=80000, interest_days=10,
        )
        self.assertTrue(mtf["mtf_used"])
        self.assertEqual(mtf["funded_amount"], 80000)
        self.assertEqual(mtf["charges"]["financing_interest"], 320.0)
        self.assertGreater(mtf["charges"]["total"], base["charges"]["total"])
        self.assertLess(mtf["net_pnl"], base["net_pnl"])
        self.assertFalse(mtf["order_execution_allowed"])
        self.assertFalse(mtf["trade_authorization"])

    def test_mtf_break_even_includes_funding_costs(self):
        result = calculate_swing_mtf_trade_costs(
            exchange="NSE", entry_price=1000, exit_price=1050, quantity=100,
            funded_amount=80000, interest_days=10,
        )
        self.assertGreater(result["break_even_exit_price"], 1000)


class TradeBrainMtfOnlyAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "mtf-only.db")
        ingest_nse_cash_holiday_payload(
            {"CM": [{"tradingDate": "26-Jan-2026", "description": "Republic Day"}]},
            db_path=self.db_path,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_final_swing_advisory_waits_without_mtf_details(self):
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=SWING_LONG,
            evaluated_at=datetime(2026, 8, 25, 12, 0, tzinfo=IST),
            quantity=100, crash_guard="NORMAL", broker_allows_trade=True,
            db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "WAIT")
        self.assertEqual(result["costs"]["status"], "NOT_COMPUTED_MTF_FUNDING_UNVERIFIED")

    def test_final_swing_advisory_combines_mtf_costs_when_verified(self):
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=SWING_LONG,
            evaluated_at=datetime(2026, 8, 25, 12, 0, tzinfo=IST),
            quantity=100, crash_guard="NORMAL", broker_allows_trade=True,
            swing_funding="MTF", mtf_eligible_verified=True,
            funded_amount=8000, mtf_interest_days=5,
            db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "ADVISORY_CANDIDATE_PASS")
        self.assertEqual(result["gate"]["swing_funding"], "MTF")
        self.assertEqual(result["costs"]["status"], "COMPUTED")
        self.assertTrue(result["costs"]["mtf_used"])
        self.assertGreater(result["costs"]["target_scenario"]["charges"]["financing_interest"], 0)
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()