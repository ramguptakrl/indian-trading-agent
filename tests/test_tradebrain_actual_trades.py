import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.actual_trade_journal import (
    actual_trade_stats,
    close_actual_trade,
    mark_actual_trade,
    record_actual_trade,
)
from backend.tradebrain.advisory_store import save_final_advisory

IST = ZoneInfo("Asia/Kolkata")


class ActualTradeJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "journal.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _save_long_advisory(self, task_id="adv-1"):
        save_final_advisory(
            task_id,
            {
                "ticker": "BSE",
                "exchange": "NSE",
                "final_status": "ADVISORY_CANDIDATE_PASS",
                "trade_authorization": False,
                "order_execution_allowed": False,
                "ai_candidate": {"entry": 3200.0, "stop_loss": 3160.0, "take_profit": 3260.0},
            },
            research_label="LONG_CANDIDATE",
            db_path=self.db,
        )

    def test_actual_trade_links_to_exact_advisory_snapshot(self):
        self._save_long_advisory()
        trade = record_actual_trade(
            ticker="BSE",
            exchange="NSE",
            mode="INTRADAY",
            direction="LONG",
            quantity=10,
            entry_price=3205,
            entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
            advisory_task_id="adv-1",
            db_path=self.db,
        )
        self.assertEqual(trade["observation_kind"], "ACTUAL_MANUAL_TRADE")
        self.assertEqual(trade["advisory_alignment"], "MATCHED")
        self.assertEqual(trade["advisory_snapshot"]["research_label"], "LONG_CANDIDATE")
        self.assertFalse(trade["order_execution_enabled"])

    def test_direction_mismatch_is_recorded_not_rewritten(self):
        self._save_long_advisory()
        trade = record_actual_trade(
            ticker="BSE",
            exchange="NSE",
            mode="INTRADAY",
            direction="SHORT",
            quantity=5,
            entry_price=3200,
            entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
            advisory_task_id="adv-1",
            db_path=self.db,
        )
        self.assertEqual(trade["direction"], "SHORT")
        self.assertEqual(trade["advisory_alignment"], "DIRECTION_MISMATCH")

    def test_partial_then_full_close_preserves_actual_fills(self):
        trade = record_actual_trade(
            ticker="BSE",
            exchange="NSE",
            mode="INTRADAY",
            direction="LONG",
            quantity=10,
            entry_price=3200,
            entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
            db_path=self.db,
        )
        part = close_actual_trade(
            trade_id=trade["trade_id"],
            quantity=4,
            exit_price=3220,
            exit_timestamp=datetime(2026, 8, 24, 11, 0, tzinfo=IST),
            db_path=self.db,
        )
        self.assertEqual(part["status"], "PARTIALLY_CLOSED")
        self.assertEqual(part["open_quantity"], 6)
        self.assertEqual(len(part["exits"]), 1)

        done = close_actual_trade(
            trade_id=trade["trade_id"],
            exit_price=3230,
            exit_timestamp=datetime(2026, 8, 24, 12, 0, tzinfo=IST),
            db_path=self.db,
        )
        self.assertEqual(done["status"], "CLOSED")
        self.assertEqual(done["open_quantity"], 0)
        self.assertEqual(len(done["exits"]), 2)
        self.assertGreater(done["realized_gross_pnl"], 0)
        self.assertLess(done["realized_net_pnl"], done["realized_gross_pnl"])

    def test_mark_to_market_includes_realized_plus_open_estimate(self):
        trade = record_actual_trade(
            ticker="BSE",
            exchange="NSE",
            mode="SWING",
            direction="LONG",
            quantity=10,
            entry_price=3200,
            entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
            db_path=self.db,
        )
        mark = mark_actual_trade(
            trade_id=trade["trade_id"], current_price=3250, source="TEST_QUOTE", db_path=self.db
        )
        self.assertEqual(mark["open_quantity"], 10)
        self.assertEqual(mark["unrealized_gross_pnl"], 500.0)
        self.assertLess(mark["estimated_open_net_pnl_if_closed_now"], 500.0)
        self.assertFalse(mark["order_execution_allowed"])

    def test_intraday_late_close_is_recorded_as_actual_violation(self):
        trade = record_actual_trade(
            ticker="BSE",
            exchange="NSE",
            mode="INTRADAY",
            direction="LONG",
            quantity=2,
            entry_price=3200,
            entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
            db_path=self.db,
        )
        closed = close_actual_trade(
            trade_id=trade["trade_id"],
            exit_price=3210,
            exit_timestamp=datetime(2026, 8, 24, 15, 20, tzinfo=IST),
            db_path=self.db,
        )
        self.assertTrue(closed["entry_policy_violation"])
        self.assertTrue(any("15:15" in x for x in closed["violation_reasons"]))

    def test_actual_charge_override_replaces_estimate_for_closed_slice(self):
        trade = record_actual_trade(
            ticker="BSE",
            exchange="NSE",
            mode="INTRADAY",
            direction="LONG",
            quantity=1,
            entry_price=3200,
            entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
            db_path=self.db,
        )
        closed = close_actual_trade(
            trade_id=trade["trade_id"],
            exit_price=3300,
            exit_timestamp=datetime(2026, 8, 24, 11, 0, tzinfo=IST),
            actual_charges_override=12.34,
            db_path=self.db,
        )
        self.assertAlmostEqual(closed["estimated_or_actual_charges"], 12.34, places=2)
        self.assertAlmostEqual(closed["realized_net_pnl"], 87.66, places=2)

    def test_stats_keep_actual_trades_separate_and_non_executing(self):
        record_actual_trade(
            ticker="BSE",
            exchange="NSE",
            mode="SWING",
            direction="LONG",
            quantity=1,
            entry_price=3200,
            entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
            db_path=self.db,
        )
        stats = actual_trade_stats(self.db)
        self.assertEqual(stats["actual_trades"], 1)
        self.assertEqual(stats["observation_kind"], "ACTUAL_MANUAL_TRADE")
        self.assertFalse(stats["order_execution_enabled"])


if __name__ == "__main__":
    unittest.main()
