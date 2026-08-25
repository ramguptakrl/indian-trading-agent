import unittest
from pathlib import Path
from unittest.mock import patch

from backend.routers import analysis_horizons
from backend.routers.analysis_horizons import HorizonAnalysisRequest
from tradingagents.horizon_policy import horizon_instruction


class TradeBrainHorizonAnalysisTests(unittest.TestCase):
    def test_horizon_instructions_do_not_allow_mode_substitution(self):
        intraday = horizon_instruction("INTRADAY")
        swing = horizon_instruction("SWING")

        self.assertIn("MUST be INTRADAY", intraday)
        self.assertIn("Do not switch to SWING", intraday)
        self.assertIn("15:10 IST", intraday)
        self.assertIn("15:15 IST", intraday)
        self.assertIn("MUST be SWING", swing)
        self.assertIn("Direction` MUST be LONG", swing)
        self.assertIn("Do not switch to INTRADAY", swing)
        self.assertIn("Zerodha MTF only", swing)
        self.assertIn("Never invent", swing)
        self.assertIn("own-cash/CNC substitute", swing)

    def test_trader_and_manager_share_horizon_policy_source(self):
        root = Path(__file__).resolve().parents[1]
        trader_source = (root / "tradingagents/agents/trader/trader.py").read_text(encoding="utf-8")
        manager_source = (root / "tradingagents/agents/managers/portfolio_manager.py").read_text(encoding="utf-8")

        for source in (trader_source, manager_source):
            self.assertIn("from tradingagents.horizon_policy import horizon_instruction", source)
            self.assertNotIn("def _horizon_instruction", source)
            self.assertNotIn("MTF disabled", source)
            self.assertNotIn("funded with the trader's own cash", source)

    def test_run_horizon_pair_launches_two_independent_modes_with_serial_provider_load(self):
        calls = []

        def fake_launch(req, mode, *, wait_for_task_id=None):
            calls.append((mode, wait_for_task_id))
            return f"task-{mode.lower()}"

        with patch.object(analysis_horizons, "_launch", side_effect=fake_launch):
            result = analysis_horizons.run_horizon_pair(
                HorizonAnalysisRequest(ticker="BSE", trade_date="2026-08-25")
            )

        self.assertEqual(
            calls,
            [("INTRADAY", None), ("SWING", "task-intraday")],
        )
        self.assertEqual(
            result["tasks"],
            {"INTRADAY": "task-intraday", "SWING": "task-swing"},
        )
        self.assertTrue(result["independent_graph_runs"])
        self.assertFalse(result["shared_final_decision"])
        self.assertFalse(result["horizon_substitution_allowed"])
        self.assertEqual(result["provider_load_scheduling"], "SERIALIZED_INDEPENDENT_HORIZONS")
        self.assertEqual(result["swing_funding"], "ZERODHA_MTF_ONLY")
        self.assertFalse(result["order_execution_allowed"])

    def test_non_bse_target_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            HorizonAnalysisRequest(ticker="RELIANCE", trade_date="2026-08-25")
        self.assertIn("BSE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
