from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.tradebrain.kite_history_range import planned_kite_chunks
from backend.tradebrain.kite_stream import (
    KiteMarketDataStream,
    classify_kite_text_message,
    latest_kite_quote,
    parse_kite_binary_frame,
    upsert_latest_kite_quote,
)
from backend.tradebrain.market_source_policy import market_source_status, sync_preferred_history


class KiteBinaryProtocolTests(unittest.TestCase):
    def _quote_frame(self) -> bytes:
        packet = bytearray(44)
        struct.pack_into(">I", packet, 0, 123456)
        struct.pack_into(">i", packet, 4, 329110)   # 3291.10
        struct.pack_into(">I", packet, 8, 7)
        struct.pack_into(">i", packet, 12, 328950)
        struct.pack_into(">I", packet, 16, 100000)
        struct.pack_into(">I", packet, 20, 500)
        struct.pack_into(">I", packet, 24, 600)
        struct.pack_into(">i", packet, 28, 327500)
        struct.pack_into(">i", packet, 32, 333000)
        struct.pack_into(">i", packet, 36, 326000)
        struct.pack_into(">i", packet, 40, 328000)
        return struct.pack(">H", 1) + struct.pack(">H", len(packet)) + bytes(packet)

    def test_quote_packet_parses_documented_binary_fields(self):
        rows = parse_kite_binary_frame(self._quote_frame())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["instrument_token"], 123456)
        self.assertEqual(row["mode"], "quote")
        self.assertAlmostEqual(row["last_price"], 3291.10)
        self.assertEqual(row["volume"], 100000)
        self.assertAlmostEqual(row["open"], 3275.00)
        self.assertEqual(len(row["packet_sha256"]), 64)

    def test_one_byte_heartbeat_is_ignored(self):
        self.assertEqual(parse_kite_binary_frame(b"\x00"), [])

    def test_truncated_frame_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_kite_binary_frame(struct.pack(">H", 1) + struct.pack(">H", 44) + b"x")

    def test_order_postback_text_is_ignored_by_market_data_plane(self):
        item = classify_kite_text_message(json.dumps({"type": "order", "data": {"order_id": "x"}}))
        self.assertEqual(item["type"], "ORDER")
        self.assertTrue(item["ignored"])

    def test_stream_class_has_no_order_mutation_methods(self):
        for name in ("place_order", "modify_order", "cancel_order", "exit_order"):
            self.assertFalse(hasattr(KiteMarketDataStream, name))

    def test_latest_quote_store_keeps_live_state_separate_from_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "live.db")
            quote = parse_kite_binary_frame(self._quote_frame())[0]
            saved = upsert_latest_kite_quote(quote, exchange="NSE", symbol="BSE", db_path=db)
            loaded = latest_kite_quote("NSE", "BSE", db_path=db)
            self.assertEqual(saved["last_price"], loaded["last_price"])
            self.assertEqual(loaded["symbol"], "BSE")
            self.assertIn("received_at", loaded)


class KiteHistoricalRangeTests(unittest.TestCase):
    def test_minute_history_is_chunked_conservatively(self):
        chunks = planned_kite_chunks("minute", "2026-01-01T09:15:00+05:30", "2026-05-01T09:15:00+05:30")
        self.assertGreaterEqual(len(chunks), 3)
        for start, end in chunks:
            self.assertLessEqual((end - start).days, 55)

    def test_invalid_reverse_range_is_rejected(self):
        with self.assertRaises(ValueError):
            planned_kite_chunks("5minute", "2026-05-01", "2026-01-01")


class PreferredSourcePolicyTests(unittest.TestCase):
    def test_without_kite_credentials_yahoo_is_explicit_fallback(self):
        with patch.dict(os.environ, {"KITE_API_KEY": "", "KITE_ACCESS_TOKEN": ""}, clear=False):
            status = market_source_status()
        self.assertFalse(status["kite_credentials_ready"])
        self.assertEqual(status["yahoo_role"], "FALLBACK_AND_RESEARCH")

    def test_kite_is_selected_when_credentials_exist(self):
        with patch.dict(os.environ, {"KITE_API_KEY": "key", "KITE_ACCESS_TOKEN": "token"}, clear=False), patch(
            "backend.tradebrain.market_source_policy.sync_kite_history_range",
            return_value={"status": "SUCCESS", "source_key": "ZERODHA_KITE_CONNECT_MARKET_DATA_ONLY", "rows_received": 10},
        ) as kite_sync:
            out = sync_preferred_history(
                exchange="NSE", symbol="BSE", interval="5m",
                from_time="2026-08-01T09:15:00+05:30", to_time="2026-08-20T15:30:00+05:30",
            )
        self.assertTrue(kite_sync.called)
        self.assertFalse(out["fallback_used"])

    def test_kite_failure_can_fall_back_but_never_hide_source(self):
        with patch.dict(os.environ, {"KITE_API_KEY": "key", "KITE_ACCESS_TOKEN": "token"}, clear=False), patch(
            "backend.tradebrain.market_source_policy.sync_kite_history_range",
            side_effect=RuntimeError("vendor unavailable"),
        ), patch(
            "backend.tradebrain.market_source_policy.sync_yahoo_history",
            return_value={"status": "SUCCESS", "source_key": "YAHOO_FINANCE_VIA_YFINANCE", "rows_received": 5},
        ):
            out = sync_preferred_history(
                exchange="NSE", symbol="BSE", interval="5m",
                from_time="2026-08-01", to_time="2026-08-20",
            )
        self.assertTrue(out["fallback_used"])
        self.assertEqual(out["fallback_source"], "YAHOO_FINANCE_VIA_YFINANCE")
        self.assertIn("vendor unavailable", out["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
