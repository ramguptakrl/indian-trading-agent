import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from backend.tradebrain.corporate_action_eras import sync_official_bse_split_price_eras
from backend.tradebrain.corporate_event_store import bulk_upsert_events
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series, query_bars
from backend.tradebrain.store import upsert_listing


class OfficialCorporateActionEraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tradebrain.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited",
            security_name="BSE Limited",
            listing_status="ACTIVE",
            source_key="TEST_MASTER",
            source_timestamp="2026-08-01T00:00:00+00:00",
            db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE",
            symbol="BSE",
            source_key="TEST_AUDITED_VENDOR",
            source_symbol="NSE:BSE",
            base_interval="1d",
            db_path=self.db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _event(self, event_id: str, *, category: str, details: str, announced: str):
        return {
            "event_id": event_id,
            "source_key": "BSE_OFFICIAL_TEST",
            "exchange": "NSE",
            "source_event_id": event_id,
            "event_fingerprint": f"fp-{event_id}",
            "listing_symbol": "BSE",
            "isin": "INE118H01025",
            "company_name": "BSE Limited",
            "subject": details,
            "details": details,
            "category": category,
            "subcategory": None,
            "source_category": "Corporate Actions",
            "importance": "HIGH",
            "importance_basis": "test",
            "classification_version": "test-v1",
            "announced_at": announced,
            "source_url": "https://www.bseindia.com/stock-share-price/bse-ltd/bse/538397/",
            "attachment_url": None,
            "raw_item_sha256": f"sha-{event_id}",
            "source_critical": True,
            "received_at": announced,
            "raw_payload": {},
        }

    def _seed_daily_bars(self):
        from backend.tradebrain.market_data_store import upsert_bars

        session_opens = [
            datetime(2026, 8, 20, 3, 45, tzinfo=timezone.utc),  # Thu
            datetime(2026, 8, 21, 3, 45, tzinfo=timezone.utc),  # Fri
            datetime(2026, 8, 24, 3, 45, tzinfo=timezone.utc),  # Mon split ex-date
            datetime(2026, 8, 25, 3, 45, tzinfo=timezone.utc),  # Tue
        ]
        bars = []
        for opened, close in zip(session_opens, (100.0, 102.0, 52.0, 53.0)):
            bars.append({
                "ts_open": opened.isoformat(),
                "ts_close": (opened + timedelta(hours=6, minutes=15)).isoformat(),
                "open": close,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 1000,
                "source_timestamp": opened.isoformat(),
                "is_final": True,
                "quality_flags": [],
            })
        upsert_bars(
            self.series["series_id"], "1d", bars,
            source_key="TEST_AUDITED_VENDOR", db_path=self.db,
        )

    def test_explicit_official_split_creates_two_raw_price_eras(self):
        self._seed_daily_bars()
        bulk_upsert_events([
            self._event(
                "split-1",
                category="CORPORATE_ACTION",
                details="Stock split: face value of Rs 2 into face value of Rs 1. Ex-date 24-Aug-2026. Record date 25-Aug-2026.",
                announced="2026-08-18T06:00:00+00:00",
            )
        ], db_path=self.db)

        result = sync_official_bse_split_price_eras(
            self.series["series_id"],
            known_by="2026-08-25T12:00:00+00:00",
            db_path=self.db,
        )
        self.assertEqual(result["status"], "OFFICIAL_SPLIT_ERAS_SYNCHRONIZED")
        self.assertEqual(result["split_boundaries"], 1)
        self.assertFalse(result["raw_prices_adjusted"])
        self.assertFalse(result["dividends_create_price_era"])

        bars = query_bars(self.series["series_id"], "1d", limit=100, db_path=self.db)
        boundary = "2026-08-24T03:45:00+00:00"
        before = {bar["era_id"] for bar in bars if bar["ts_open"] < boundary}
        after = {bar["era_id"] for bar in bars if bar["ts_open"] >= boundary}
        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)
        self.assertNotEqual(before, after)

        again = sync_official_bse_split_price_eras(
            self.series["series_id"], known_by="2026-08-25T12:00:00+00:00", db_path=self.db
        )
        self.assertEqual(again["split_boundaries"], 1)
        bars_again = query_bars(self.series["series_id"], "1d", limit=100, db_path=self.db)
        self.assertEqual([bar["era_id"] for bar in bars], [bar["era_id"] for bar in bars_again])

    def test_dividend_does_not_create_structural_price_era(self):
        self._seed_daily_bars()
        bulk_upsert_events([
            self._event(
                "div-1",
                category="DIVIDEND",
                details="Dividend of Rs 5 per equity share. Ex-date 24-Aug-2026. Record date 25-Aug-2026.",
                announced="2026-08-18T06:00:00+00:00",
            )
        ], db_path=self.db)
        result = sync_official_bse_split_price_eras(
            self.series["series_id"], known_by="2026-08-25T12:00:00+00:00", db_path=self.db
        )
        self.assertEqual(result["status"], "NO_KNOWN_OFFICIAL_SPLIT_BOUNDARY")
        self.assertEqual(result["split_boundaries"], 0)
        self.assertFalse(result["dividends_create_price_era"])

    def test_future_known_split_is_excluded_from_earlier_replay(self):
        self._seed_daily_bars()
        bulk_upsert_events([
            self._event(
                "split-future",
                category="CORPORATE_ACTION",
                details="Stock split: face value of Rs 2 into face value of Rs 1. Ex-date 24-Aug-2026.",
                announced="2026-08-23T06:00:00+00:00",
            )
        ], db_path=self.db)
        result = sync_official_bse_split_price_eras(
            self.series["series_id"], known_by="2026-08-21T12:00:00+00:00", db_path=self.db
        )
        self.assertEqual(result["split_boundaries"], 0)
        self.assertEqual(result["status"], "NO_KNOWN_OFFICIAL_SPLIT_BOUNDARY")


if __name__ == "__main__":
    unittest.main()
