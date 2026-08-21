import os
import tempfile
import unittest
from datetime import datetime, timezone

from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.kite_data import (
    KITE_SOURCE_KEY,
    KiteDataOnlyClient,
    kite_data_boundary,
    normalize_kite_candles,
    sync_kite_history,
)
from backend.tradebrain.market_data_store import query_bars
from backend.tradebrain.store import upsert_listing


class FakeClient:
    def historical(self, **kwargs):
        return [
            ["2026-08-21T09:15:00+05:30", 100, 101, 99.5, 100.5, 1000],
            ["2026-08-21T09:20:00+05:30", 100.5, 102, 100, 101.5, 1400],
        ]


class DummySession:
    pass


class Phase9KiteBoundaryTests(unittest.TestCase):
    def test_boundary_is_market_data_only_even_if_credential_is_nri(self):
        boundary = kite_data_boundary()
        self.assertEqual(boundary["trader_profile"], "RESIDENT_INDIAN")
        self.assertTrue(boundary["credential_account_type_may_be_nri"])
        self.assertEqual(boundary["credential_role"], "MARKET_DATA_ONLY")
        self.assertFalse(boundary["credential_account_type_affects_policy"])
        self.assertFalse(boundary["credential_account_type_affects_cost_profile"])
        self.assertFalse(boundary["order_api_enabled"])

    def test_client_exposes_no_order_method(self):
        client = KiteDataOnlyClient("api", "access", session=DummySession())
        self.assertFalse(hasattr(client, "place_order"))
        self.assertFalse(hasattr(client, "modify_order"))
        self.assertFalse(hasattr(client, "cancel_order"))

    def test_normalize_kite_5m_candles(self):
        candles = FakeClient().historical()
        bars, issues = normalize_kite_candles(
            candles, "5minute", fetched_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(len(bars), 2)
        self.assertEqual(issues, [])
        self.assertEqual(bars[0]["open"], 100.0)
        self.assertEqual(bars[0]["close"], 100.5)
        self.assertTrue(bars[0]["is_final"])
        self.assertIn("KITE_MARKET_DATA_ONLY", bars[0]["quality_flags"])


class Phase9KiteStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "phase9.db")
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited",
            listing_status="ACTIVE", source_key="PHASE9_TEST",
            source_timestamp="2026-08-21T00:00:00+00:00", db_path=self.db_path,
        )

    def tearDown(self):
        os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        self.tmp.cleanup()

    def test_sync_kite_history_enters_audited_store_without_order_semantics(self):
        result = sync_kite_history(
            exchange="NSE", symbol="BSE", interval="5minute",
            from_time="2026-08-21T09:15:00+05:30",
            to_time="2026-08-21T09:25:00+05:30",
            instrument_token=123456, client=FakeClient(), db_path=self.db_path,
        )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["source_key"], KITE_SOURCE_KEY)
        self.assertEqual(result["rows_received"], 2)
        self.assertEqual(result["credential_role"], "MARKET_DATA_ONLY")
        self.assertFalse(result["order_api_enabled"])
        self.assertEqual(result["trader_profile"], "RESIDENT_INDIAN")
        bars = query_bars(result["series_id"], "5m", limit=10, db_path=self.db_path)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1]["close"], 101.5)


if __name__ == "__main__":
    unittest.main()
