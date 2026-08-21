import importlib.util
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.tradebrain.advisory_pipeline import evaluate_final_advisory, parse_agent_candidate, research_label
from backend.tradebrain.advisory_store import get_final_advisory, save_final_advisory
from backend.tradebrain.challenger_store import activate_soft_parameter
from backend.tradebrain.exchange_calendar import ingest_nse_cash_holiday_payload

# Load the actual module file without executing tradingagents.graph.__init__, which
# imports the full LangGraph runtime not installed in the lightweight Trade Brain CI.
_SIGNAL_PATH = Path(__file__).resolve().parents[1] / "tradingagents" / "graph" / "signal_processing.py"
_SPEC = importlib.util.spec_from_file_location("tradebrain_test_signal_processing", _SIGNAL_PATH)
_SIGNAL_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_SIGNAL_MODULE)
SignalProcessor = _SIGNAL_MODULE.SignalProcessor

IST = ZoneInfo("Asia/Kolkata")

VALID_LONG = """1. Candidate Verdict: BUY CANDIDATE
2. Trade Mode: INTRADAY
3. Direction: LONG
4. Entry Price: 100
5. Stop-Loss: 99
6. Take-Profit: 102
7. Risk-Reward Ratio: 2:1
12. Trade Brain Gate: NOT EVALUATED — candidate must pass deterministic Trade Brain gate before any advisory setup is considered valid.
"""


class Phase10FinalAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "phase10.db")
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        ingest_nse_cash_holiday_payload(
            {
                "CM": [
                    {"tradingDate": "26-Jan-2026", "description": "Republic Day"},
                    {"tradingDate": "08-Nov-2026", "description": "Diwali Laxmi Pujan*"},
                ]
            },
            db_path=self.db_path,
        )

    def tearDown(self):
        os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        self.tmp.cleanup()

    def test_free_form_bullish_prose_is_not_guessed_into_trade(self):
        parsed = parse_agent_candidate("The stock looks very bullish and I would buy it here.")
        self.assertEqual(parsed["parse_status"], "PARSE_INCOMPLETE")
        self.assertEqual(parsed["research_label"], "NO_TRADE")
        self.assertFalse(parsed["free_form_inference_used"])

    def test_processor_never_returns_raw_buy_sell(self):
        processor = SignalProcessor(None)
        label = processor.process_signal(VALID_LONG)
        self.assertEqual(label, "LONG_CANDIDATE")
        self.assertNotIn(label, {"BUY", "SELL", "OVERWEIGHT", "UNDERWEIGHT"})

    def test_unverified_calendar_blocks_entry(self):
        result = evaluate_final_advisory(
            ticker="BSE", exchange="BSE", final_trade_decision=VALID_LONG,
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            crash_guard="NORMAL", broker_allows_trade=True,
            db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "BLOCK_CALENDAR_UNVERIFIED")
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])

    def test_verified_holiday_blocks_entry(self):
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=VALID_LONG,
            evaluated_at=datetime(2026, 1, 26, 12, 0, tzinfo=IST),
            crash_guard="NORMAL", broker_allows_trade=True,
            db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "BLOCK_MARKET_CLOSED")

    def test_unknown_crash_guard_blocks_instead_of_assuming_normal(self):
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=VALID_LONG,
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            crash_guard=None, broker_allows_trade=True,
            db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "BLOCK_CRASH_GUARD_UNVERIFIED")

    def test_unknown_broker_permission_blocks(self):
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=VALID_LONG,
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            crash_guard="NORMAL", broker_allows_trade=None,
            db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "BLOCK_BROKER_PERMISSION_UNVERIFIED")

    def test_verified_regular_day_valid_geometry_reaches_advisory_pass(self):
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=VALID_LONG,
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST), quantity=10,
            crash_guard="NORMAL", broker_allows_trade=True,
            db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "ADVISORY_CANDIDATE_PASS")
        self.assertEqual(result["gate"]["action"], "PASS")
        self.assertEqual(result["costs"]["status"], "COMPUTED")
        self.assertLess(result["costs"]["net_reward_rupees"], 20.0)
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])

    def test_human_approved_soft_floor_can_turn_pass_into_wait(self):
        activate_soft_parameter(
            parameter_key="day_min_reward_risk", parameter_scope="DAY", value=2.5,
            source_experiment_id=None, approved_by="reviewer",
            approval_note="Reviewed Phase-10 test promotion", db_path=self.db_path,
        )
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=VALID_LONG,
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            crash_guard="NORMAL", broker_allows_trade=True, db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "WAIT")
        self.assertTrue(result["gate"]["soft_parameter_registry_applied"])
        self.assertEqual(result["gate"]["soft_parameter_version"], 1)

    def test_swing_short_is_blocked(self):
        text = VALID_LONG.replace("BUY CANDIDATE", "SHORT CANDIDATE").replace("INTRADAY", "SWING").replace("LONG", "SHORT").replace("Stop-Loss: 99", "Stop-Loss: 101").replace("Take-Profit: 102", "Take-Profit: 98")
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=text,
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            crash_guard="NORMAL", broker_allows_trade=True, db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "BLOCK")
        self.assertIn("SWING_POSITION short", " ".join(result["gate"]["hard_rule_failures"]))

    def test_exit_candidate_is_not_treated_as_new_short(self):
        text = """Candidate Verdict: SELL / EXIT CANDIDATE
Trade Mode: NONE
Direction: NONE
Entry Price: N/A
Stop-Loss: N/A
Take-Profit: N/A
"""
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=text,
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            db_path=self.db_path,
        )
        self.assertEqual(result["final_status"], "EXIT_CANDIDATE")
        self.assertIsNone(result["gate"])
        self.assertFalse(result["trade_authorization"])

    def test_advisory_persistence_keeps_execution_false(self):
        result = evaluate_final_advisory(
            ticker="BSE", exchange="NSE", final_trade_decision=VALID_LONG,
            evaluated_at=datetime(2026, 8, 21, 12, 0, tzinfo=IST),
            crash_guard="NORMAL", broker_allows_trade=True, db_path=self.db_path,
        )
        save_final_advisory("task-1", result, research_label=research_label(VALID_LONG), db_path=self.db_path)
        stored = get_final_advisory("task-1", db_path=self.db_path)
        self.assertEqual(stored["research_label"], "LONG_CANDIDATE")
        self.assertFalse(stored["trade_authorization"])
        self.assertFalse(stored["order_execution_allowed"])
        self.assertEqual(stored["advisory"]["final_status"], "ADVISORY_CANDIDATE_PASS")


if __name__ == "__main__":
    unittest.main()
