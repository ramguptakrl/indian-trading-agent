from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from backend.tradebrain.context_index import (
    INDEX_KEY,
    KITE_SOURCE_KEY,
    ensure_context_index_schema,
    nifty50_correction_context,
    query_context_index_bars,
)


class AuditedNiftyContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tradebrain.db")
        ensure_context_index_schema(self.db)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                """
                INSERT INTO tb_context_index_series(
                    index_key, exchange, symbol, source_key, instrument_token,
                    source_symbol, created_at, updated_at, last_sync_at
                ) VALUES (?, 'NSE', 'NIFTY 50', ?, 256265, 'NSE:NIFTY 50', ?, ?, ?)
                """,
                (INDEX_KEY, KITE_SOURCE_KEY, now, now, now),
            )

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self, count: int = 60, *, falling: bool = False) -> list[dict]:
        start = datetime(2026, 5, 1, 3, 45, tzinfo=timezone.utc)
        rows = []
        with sqlite3.connect(self.db) as conn:
            for idx in range(count):
                opened = start + timedelta(days=idx)
                price = 25000.0 - idx * 40.0 if falling else 24000.0 + idx * 20.0
                closed = opened + timedelta(hours=6, minutes=15)
                conn.execute(
                    """
                    INSERT INTO tb_context_index_bars(
                        index_key, interval, ts_open, ts_close, open, high, low, close,
                        volume, source_key, source_timestamp, ingested_at, is_final,
                        quality_flags_json
                    ) VALUES (?, '1d', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 1, '[]')
                    """,
                    (
                        INDEX_KEY, opened.isoformat(), closed.isoformat(), price,
                        price + 25, price - 25, price, KITE_SOURCE_KEY,
                        opened.isoformat(), closed.isoformat(),
                    ),
                )
                rows.append({"ts_open": opened.isoformat(), "ts_close": closed.isoformat(), "close": price})
        return rows

    def test_missing_history_stays_unknown_and_never_authorizes(self):
        result = nifty50_correction_context(
            as_of="2026-08-25T12:00:00+00:00", db_path=self.db
        )
        self.assertEqual(result["status"], "INSUFFICIENT_AUDITED_NIFTY_CONTEXT")
        self.assertEqual(result["correction_state"], "UNKNOWN")
        self.assertEqual(result["source_required"], KITE_SOURCE_KEY)
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])

    def test_as_of_excludes_future_completed_index_bars(self):
        rows = self._seed(3)
        cutoff = rows[1]["ts_close"]
        visible = query_context_index_bars(as_of=cutoff, limit=100, db_path=self.db)
        self.assertEqual(len(visible), 2)
        self.assertEqual(visible[-1]["ts_close"], cutoff)
        self.assertNotEqual(visible[-1]["ts_close"], rows[2]["ts_close"])

    def test_completed_audited_downtrend_becomes_context_not_trade_signal(self):
        rows = self._seed(70, falling=True)
        result = nifty50_correction_context(as_of=rows[-1]["ts_close"], db_path=self.db)
        self.assertEqual(result["status"], "AUDITED_NIFTY_DAILY_CONTEXT")
        self.assertIn(result["correction_state"], {"TREND_DOWN", "HIGH_VOL_TREND_DOWN", "SEVERE_CORRECTION"})
        self.assertEqual(result["source_key"], KITE_SOURCE_KEY)
        self.assertTrue(result["context_only"])
        self.assertFalse(result["trade_target"])
        self.assertFalse(result["hard_external_web_fetch_used"])
        self.assertFalse(result["trade_authorization"])
        self.assertFalse(result["order_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
