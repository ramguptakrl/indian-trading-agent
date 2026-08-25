import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.tradebrain.live_decision_context import (
    _as_of_for_trade_date,
    build_bse_decision_context,
    decision_context_for_prompt,
)

ROOT = Path(__file__).resolve().parents[1]


class TradeBrainLiveDecisionContextTests(unittest.TestCase):
    def test_historical_as_of_is_market_close_not_future_data(self):
        now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
        as_of = _as_of_for_trade_date("2026-08-20", now=now)
        self.assertEqual(as_of.astimezone().tzinfo is not None, True)
        self.assertLess(as_of, now)
        self.assertEqual(as_of.astimezone(timezone.utc).date().isoformat(), "2026-08-20")

    def test_future_market_date_is_rejected(self):
        now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "future India market date"):
            _as_of_for_trade_date("2026-08-26", now=now)

    def test_missing_audited_series_is_explicit_and_fail_closed(self):
        with patch("backend.tradebrain.live_decision_context.find_series", return_value=None):
            context = build_bse_decision_context(
                "2026-08-20",
                now=datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(context["status"], "MISSING_AUDITED_SERIES")
        self.assertFalse(context["candidate_evidence_complete"])
        self.assertFalse(context["trade_authorization"])
        text = decision_context_for_prompt(context)
        self.assertIn("Do not invent 1D/4H/1H/15m values", text)

    def test_trader_and_final_manager_consume_same_state_context(self):
        trader = (ROOT / "tradingagents/agents/trader/trader.py").read_text(encoding="utf-8")
        manager = (ROOT / "tradingagents/agents/managers/portfolio_manager.py").read_text(encoding="utf-8")
        propagation = (ROOT / "tradingagents/graph/propagation.py").read_text(encoding="utf-8")
        for source in (trader, manager):
            self.assertIn('state.get("multi_timeframe_context")', source)
            self.assertIn("MISSING_AUDITED_SERIES", source)
            self.assertIn("PRICE_COMPARABILITY_BLOCK", source)
        self.assertIn("build_bse_decision_context", propagation)
        self.assertIn("_runtime_multi_timeframe_context", propagation)
        self.assertIn('"multi_timeframe_context": audited_context', propagation)


if __name__ == "__main__":
    unittest.main()
