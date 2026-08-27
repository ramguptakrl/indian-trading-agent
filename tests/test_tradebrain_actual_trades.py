import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.tradebrain.actual_trade_journal import (
    actual_trade_stats,
    close_actual_trade,
    ensure_actual_trade_schema,
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

    def _swing(self, *, quantity=10, entry_price=3200):
        return record_actual_trade(
            ticker="BSE",
            exchange="NSE",
            mode="SWING",
            direction="LONG",
            quantity=quantity,
            entry_price=entry_price,
            entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
            swing_funding="MTF",
            mtf_eligible_verified=True,
            funded_amount=entry_price * quantity * 0.8,
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
        self.assertEqual(trade["mtf_metadata_status"], "NOT_APPLICABLE")
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

    def test_active_swing_requires_verified_mtf_and_funded_amount(self):
        with self.assertRaises(ValueError):
            record_actual_trade(
                ticker="BSE", exchange="NSE", mode="SWING", direction="LONG",
                quantity=10, entry_price=3200,
                entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
                db_path=self.db,
            )
        with self.assertRaises(ValueError):
            record_actual_trade(
                ticker="BSE", exchange="NSE", mode="SWING", direction="LONG",
                quantity=10, entry_price=3200,
                entry_timestamp=datetime(2026, 8, 24, 10, 0, tzinfo=IST),
                swing_funding="MTF", mtf_eligible_verified=False, funded_amount=25000,
                db_path=self.db,
            )

        trade = self._swing()
        self.assertEqual(trade["swing_funding"], "MTF")
        self.assertTrue(trade["mtf_eligible_verified"])
        self.assertGreater(trade["funded_amount"], 0)
        self.assertEqual(trade["mtf_metadata_status"], "COMPLETE")

    def test_swing_mark_requires_days_then_includes_mtf_financing(self):
        trade = self._swing()
        pending = mark_actual_trade(
            trade_id=trade["trade_id"], current_price=3250, source="TEST_QUOTE", db_path=self.db
        )
        self.assertEqual(pending["estimate_status"], "MTF_INTEREST_DAYS_REQUIRED")
        self.assertIsNone(pending["estimated_open_net_pnl_if_closed_now"])

        mark = mark_actual_trade(
            trade_id=trade["trade_id"], current_price=3250, source="TEST_QUOTE",
            mtf_interest_days=5, db_path=self.db,
        )
        self.assertEqual(mark["open_quantity"], 10)
        self.assertEqual(mark["unrealized_gross_pnl"], 500.0)
        self.assertLess(mark["estimated_open_net_pnl_if_closed_now"], 500.0)
        self.assertEqual(mark["mtf_interest_days"], 5)
        self.assertEqual(mark["cost_allocation_method"], "PRO_RATA_ORIGINAL_POSITION_ESTIMATE")
        self.assertFalse(mark["order_execution_allowed"])

    def test_swing_partial_close_allocates_full_position_mtf_costs_pro_rata(self):
        trade = self._swing(quantity=10, entry_price=1000)
        closed = close_actual_trade(
            trade_id=trade["trade_id"], quantity=4, exit_price=1050,
            exit_timestamp=datetime(2026, 8, 29, 11, 0, tzinfo=IST),
            mtf_interest_days=5, db_path=self.db,
        )
        self.assertEqual(closed["status"], "PARTIALLY_CLOSED")
        exit_row = closed["exits"][0]
        self.assertEqual(exit_row["mtf_interest_days"], 5)
        self.assertEqual(exit_row["cost_allocation_method"], "PRO_RATA_ORIGINAL_POSITION_ESTIMATE")
        self.assertAlmostEqual(exit_row["mtf_funded_amount_allocated"], 3200.0, places=2)
        self.assertGreater(exit_row["estimated_charges"], 0)
        self.assertIsNotNone(exit_row["economics"])

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

    def test_additive_migration_keeps_old_swing_row_readable_and_marks_metadata_missing(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                """CREATE TABLE tb_actual_trades (
                    trade_id TEXT PRIMARY KEY, advisory_task_id TEXT, advisory_snapshot_json TEXT,
                    ticker TEXT NOT NULL, exchange TEXT NOT NULL, mode TEXT NOT NULL, direction TEXT NOT NULL,
                    original_quantity INTEGER NOT NULL, open_quantity INTEGER NOT NULL, avg_entry_price REAL NOT NULL,
                    entry_timestamp TEXT NOT NULL, stop_loss REAL, take_profit REAL, broker_order_ref TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN', advisory_alignment TEXT NOT NULL DEFAULT 'UNLINKED_MANUAL',
                    entry_policy_violation INTEGER NOT NULL DEFAULT 0, violation_reasons_json TEXT,
                    realized_gross_pnl REAL NOT NULL DEFAULT 0, estimated_or_actual_charges REAL NOT NULL DEFAULT 0,
                    realized_net_pnl REAL NOT NULL DEFAULT 0, notes TEXT, manual_tracking_only INTEGER NOT NULL DEFAULT 1,
                    order_execution_enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    closed_at TEXT
                )"""
            )
            conn.execute(
                """INSERT INTO tb_actual_trades(
                    trade_id,ticker,exchange,mode,direction,original_quantity,open_quantity,avg_entry_price,
                    entry_timestamp,created_at,updated_at
                ) VALUES ('legacy','BSE','NSE','SWING','LONG',1,1,3200,'2026-08-24T04:30:00+00:00','x','x')"""
            )
        ensure_actual_trade_schema(self.db)
        from backend.tradebrain.actual_trade_journal import get_actual_trade
        legacy = get_actual_trade("legacy", db_path=self.db)
        self.assertEqual(legacy["mtf_metadata_status"], "LEGACY_MTF_METADATA_MISSING")
        with self.assertRaises(ValueError):
            mark_actual_trade(trade_id="legacy", current_price=3250, mtf_interest_days=1, db_path=self.db)

    def test_stats_keep_actual_trades_separate_and_count_mtf_swing(self):
        self._swing(quantity=1)
        stats = actual_trade_stats(self.db)
        self.assertEqual(stats["actual_trades"], 1)
        self.assertEqual(stats["swing_mtf"], 1)
        self.assertEqual(stats["legacy_swing_missing_mtf_metadata"], 0)
        self.assertEqual(stats["observation_kind"], "ACTUAL_MANUAL_TRADE")
        self.assertFalse(stats["order_execution_enabled"])


if __name__ == "__main__":
    unittest.main()
