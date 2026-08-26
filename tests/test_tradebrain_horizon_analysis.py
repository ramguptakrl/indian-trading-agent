import unittest
from pathlib import Path
from unittest.mock import patch

from backend.routers import analysis_horizons
from backend.routers.analysis import _tasks
from backend.routers.analysis_horizons import HorizonAnalysisRequest
from backend.tradebrain.trade_date import normalize_trade_date
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

    def test_decision_agents_share_horizon_policy_source(self):
        root = Path(__file__).resolve().parents[1]
        sources = [
            (root / "tradingagents/agents/trader/trader.py").read_text(encoding="utf-8"),
            (root / "tradingagents/agents/managers/research_manager.py").read_text(encoding="utf-8"),
            (root / "tradingagents/agents/managers/portfolio_manager.py").read_text(encoding="utf-8"),
        ]

        for source in sources:
            self.assertIn("from tradingagents.horizon_policy import horizon_instruction", source)
            self.assertNotIn("def _horizon_instruction", source)
            self.assertNotIn("MTF disabled", source)
            self.assertNotIn("funded with the trader's own cash", source)

        research_manager = sources[1]
        self.assertIn("requested_trade_mode: str | None = None", research_manager)
        self.assertIn("horizon_instruction(requested_trade_mode)", research_manager)
        self.assertIn("Never substitute SWING for a weak INTRADAY setup", research_manager)

    def test_run_horizon_pair_registers_one_shared_pack_and_two_decision_tasks(self):
        req = HorizonAnalysisRequest(ticker="BSE", trade_date="2026-08-25")
        created_ids = []

        with patch.object(analysis_horizons.threading, "Thread") as thread_cls:
            result = analysis_horizons.run_horizon_pair(req)
            thread_cls.return_value.start.assert_called_once()

        try:
            intraday_id = result["tasks"]["INTRADAY"]
            swing_id = result["tasks"]["SWING"]
            created_ids.extend([intraday_id, swing_id])
            self.assertNotEqual(intraday_id, swing_id)
            self.assertEqual(
                _tasks[intraday_id]["shared_research_pack_id"],
                _tasks[swing_id]["shared_research_pack_id"],
            )
            self.assertEqual(
                result["shared_research_pack_id"],
                _tasks[intraday_id]["shared_research_pack_id"],
            )
            self.assertTrue(result["shared_data_pull"])
            self.assertTrue(result["shared_analyst_research"])
            self.assertTrue(result["independent_decision_graph_runs"])
            self.assertFalse(result["shared_final_decision"])
            self.assertFalse(result["horizon_substitution_allowed"])
            self.assertEqual(
                result["provider_load_scheduling"],
                "SHARED_RESEARCH_ONCE_THEN_SERIAL_DECISIONS",
            )
            self.assertEqual(result["swing_funding"], "ZERODHA_MTF_ONLY")
            self.assertFalse(result["order_execution_allowed"])
        finally:
            for task_id in created_ids:
                _tasks.pop(task_id, None)

    def test_graph_setup_has_shared_research_and_forked_decision_modes(self):
        root = Path(__file__).resolve().parents[1]
        setup_source = (root / "tradingagents/graph/setup.py").read_text(encoding="utf-8")
        self.assertIn('GRAPH_MODE_SHARED_RESEARCH_ONLY = "SHARED_RESEARCH_ONLY"', setup_source)
        self.assertIn(
            'GRAPH_MODE_DECISION_FROM_SHARED_RESEARCH = "DECISION_FROM_SHARED_RESEARCH"',
            setup_source,
        )
        self.assertIn('workflow.add_edge(START, "Bull Researcher")', setup_source)
        self.assertIn("workflow.add_edge(current_clear, END)", setup_source)
        self.assertIn("create_research_manager(", setup_source)
        self.assertIn("requested_trade_mode=requested_trade_mode", setup_source)

    def test_offset_midnight_trade_date_is_canonicalized(self):
        request = HorizonAnalysisRequest(
            ticker="BSE",
            trade_date="2026-08-26T00:00:00+05:30",
        )
        self.assertEqual(request.trade_date, "2026-08-26")
        self.assertEqual(
            normalize_trade_date("2026-08-26T00:00:00+05:30"),
            "2026-08-26",
        )

    def test_non_bse_target_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            HorizonAnalysisRequest(ticker="RELIANCE", trade_date="2026-08-25")
        self.assertIn("BSE", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
