import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.equity_costs import (
    calculate_equity_trade_costs,
    cost_profile,
    data_credential_boundary,
    solve_exit_price_for_net_profit,
)
from backend.tradebrain.paper_ledger import (
    close_paper_position,
    create_paper_account,
    get_paper_account,
    open_paper_position,
)
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.trade_modes import product_boundary, to_active_mode

IST = ZoneInfo("Asia/Kolkata")


class Phase6ProductBoundaryTests(unittest.TestCase):
    def test_active_mode_aliases_preserve_legacy_replay_storage(self):
        plan = TradePlan(
            ticker="BSE", exchange="NSE", mode="INTRADAY", direction="LONG",
            entry=2500, stop_loss=2475, take_profit=2525,
            evidence=["phase6:test"],
            evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
        )
        self.assertEqual(plan.mode, "DAY")
        result = evaluate_trade_plan(plan)
        self.assertEqual(result.active_mode, "INTRADAY")
        self.assertEqual(result.action, "PASS")

        swing = TradePlan(
            ticker="BSE", exchange="NSE", mode="SWING", direction="LONG",
            entry=2500, stop_loss=2450, take_profit=2650,
            evidence=["phase6:test"],
            evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
        )
        self.assertEqual(swing.mode, "SWING_POSITION")
        self.assertEqual(evaluate_trade_plan(swing).active_mode, "SWING")

    def test_only_intraday_and_swing_are_active(self):
        boundary = product_boundary()
        self.assertEqual(boundary["active_trade_modes"], ["INTRADAY", "SWING"])
        self.assertTrue(boundary["mtf_enabled_for_research_and_cost_modeling"])
        self.assertTrue(boundary["funded_amount_modeled"])
        self.assertEqual(boundary["swing_funding_modes"], ["CNC_OWN_CASH", "MTF"])
        self.assertFalse(boundary["mtf_broker_order_execution_enabled"])
        self.assertFalse(boundary["intraday_short_overnight_allowed"])
        with self.assertRaises(ValueError):
            to_active_mode("MTF")

    def test_data_credential_identity_does_not_change_resident_profile(self):
        boundary = data_credential_boundary()
        self.assertEqual(boundary["trader_profile"], "RESIDENT_INDIAN")
        self.assertEqual(boundary["kite_credential_role"], "MARKET_DATA_ONLY")
        self.assertTrue(boundary["kite_credential_may_belong_to_nri_account"])
        self.assertFalse(boundary["credential_account_type_affects_policy"])
        self.assertFalse(boundary["credential_account_type_affects_cost_profile"])
        self.assertFalse(boundary["order_api_enabled"])

    def test_swing_short_is_still_blocked_under_active_name(self):
        result = evaluate_trade_plan(
            TradePlan(
                ticker="BSE", mode="SWING", direction="SHORT",
                entry=2500, stop_loss=2550, take_profit=2400,
                evaluated_at_ist=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            )
        )
        self.assertFalse(result.allowed_for_advisory)
        self.assertEqual(result.active_mode, "SWING")


class Phase6ResidentCostTests(unittest.TestCase):
    def test_intraday_costs_have_no_dp_or_financing(self):
        result = calculate_equity_trade_costs(
            mode="INTRADAY", exchange="NSE", direction="LONG",
            entry_price=1000, exit_price=1010, quantity=100,
        )
        self.assertGreater(result["charges"]["brokerage"], 0)
        self.assertGreater(result["charges"]["stt_sell"], 0)
        self.assertEqual(result["charges"]["dp_charge"], 0)
        self.assertEqual(result["charges"]["financing_interest"], 0)
        self.assertFalse(result["mtf_used"])
        self.assertEqual(result["funded_amount"], 0)
        self.assertLess(result["net_pnl"], result["gross_pnl"])
        self.assertGreater(result["break_even_exit_price"], 1000)

    def test_swing_delivery_has_zero_brokerage_and_positive_dp(self):
        result = calculate_equity_trade_costs(
            mode="SWING", exchange="NSE", direction="LONG",
            entry_price=1000, exit_price=1050, quantity=100,
        )
        self.assertEqual(result["charges"]["brokerage"], 0)
        self.assertGreater(result["charges"]["dp_charge"], 0)
        self.assertGreater(result["charges"]["stt_buy"], 0)
        self.assertGreater(result["charges"]["stt_sell"], 0)
        self.assertEqual(result["charges"]["financing_interest"], 0)
        self.assertFalse(result["mtf_used"])

    def test_swing_short_cost_request_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_equity_trade_costs(
                mode="SWING", exchange="NSE", direction="SHORT",
                entry_price=1000, exit_price=950, quantity=100,
            )

    def test_legacy_equity_cost_profile_remains_non_mtf(self):
        profile = cost_profile()
        self.assertEqual(profile["trader_profile"], "RESIDENT_INDIAN")
        self.assertFalse(profile["mtf_enabled"])
        self.assertEqual(profile["funding_interest_pct"], 0.0)
        self.assertFalse(profile["data_credential_boundary"]["order_api_enabled"])

    def test_net_target_solver_really_meets_after_cost_target(self):
        solved_exit = solve_exit_price_for_net_profit(
            desired_net_profit=500,
            mode="INTRADAY", exchange="NSE", direction="LONG",
            entry_price=1000, quantity=100,
        )
        recomputed = calculate_equity_trade_costs(
            mode="INTRADAY", exchange="NSE", direction="LONG",
            entry_price=1000, exit_price=solved_exit, quantity=100,
        )
        self.assertGreaterEqual(recomputed["net_pnl"], 500)
        self.assertFalse(recomputed["mtf_used"])


class Phase6PaperLedgerTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.path)
        self.account = create_paper_account(name="phase6", starting_cash=100000, db_path=self.path)
        self.account_id = self.account["account_id"]

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_insufficient_cash_is_rejected_without_leverage(self):
        with self.assertRaises(ValueError):
            open_paper_position(
                account_id=self.account_id, ticker="BSE", exchange="NSE", mode="SWING",
                direction="LONG", entry_price=2000, quantity=100,
                entry_timestamp=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
                db_path=self.path,
            )

    def test_intraday_open_after_1510_is_rejected(self):
        with self.assertRaises(ValueError):
            open_paper_position(
                account_id=self.account_id, ticker="BSE", exchange="NSE", mode="INTRADAY",
                direction="LONG", entry_price=1000, quantity=10,
                entry_timestamp=datetime(2026, 8, 21, 15, 10, tzinfo=IST),
                db_path=self.path,
            )

    def test_intraday_close_applies_net_pnl_once(self):
        position = open_paper_position(
            account_id=self.account_id, ticker="BSE", exchange="NSE", mode="INTRADAY",
            direction="LONG", entry_price=1000, quantity=10,
            entry_timestamp=datetime(2026, 8, 21, 10, 0, tzinfo=IST),
            db_path=self.path,
        )
        result = close_paper_position(
            position_id=position["position_id"], exit_price=1010,
            exit_timestamp=datetime(2026, 8, 21, 11, 0, tzinfo=IST), db_path=self.path,
        )
        account = get_paper_account(self.account_id, db_path=self.path)
        self.assertAlmostEqual(account["cash_balance"], 100000 + result["net_pnl"], places=2)

    def test_intraday_late_exit_is_recorded_as_violation_not_hidden(self):
        position = open_paper_position(
            account_id=self.account_id, ticker="BSE", exchange="NSE", mode="INTRADAY",
            direction="LONG", entry_price=1000, quantity=10,
            entry_timestamp=datetime(2026, 8, 21, 10, 0, tzinfo=IST),
            db_path=self.path,
        )
        result = close_paper_position(
            position_id=position["position_id"], exit_price=1005,
            exit_timestamp=datetime(2026, 8, 21, 15, 20, tzinfo=IST), db_path=self.path,
        )
        self.assertTrue(result["mode_violation"])
        self.assertIn("15:15", result["violation_reason"])

    def test_swing_can_cross_sessions_and_includes_dp(self):
        position = open_paper_position(
            account_id=self.account_id, ticker="BSE", exchange="NSE", mode="SWING",
            direction="LONG", entry_price=1000, quantity=10,
            entry_timestamp=datetime(2026, 8, 21, 14, 0, tzinfo=IST), db_path=self.path,
        )
        result = close_paper_position(
            position_id=position["position_id"], exit_price=1050,
            exit_timestamp=datetime(2026, 8, 24, 11, 0, tzinfo=IST), db_path=self.path,
        )
        self.assertFalse(result["mode_violation"])
        self.assertGreater(result["economics"]["charges"]["dp_charge"], 0)


if __name__ == "__main__":
    unittest.main()
