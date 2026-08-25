from __future__ import annotations

import os
import tempfile
import unittest

from backend.tradebrain.corporate_action_eras import sync_official_bse_split_price_eras
from backend.tradebrain.corporate_actions import corporate_action_context_from_store
from backend.tradebrain.corporate_event_store import bulk_upsert_events, set_event_status
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data_store import ensure_series
from backend.tradebrain.store import upsert_listing


class PermanentCorporateEventMemoryTests(unittest.TestCase):
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
            source_key="TEST_AUDITED",
            source_symbol="NSE:BSE",
            base_interval="1d",
            db_path=self.db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _event(self, event_id: str, *, category: str, details: str):
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
            "announced_at": "2026-08-18T06:00:00+00:00",
            "source_url": "https://www.bseindia.com/",
            "attachment_url": None,
            "raw_item_sha256": f"sha-{event_id}",
            "source_critical": True,
            "received_at": "2026-08-18T06:00:00+00:00",
            "raw_payload": {},
        }

    def test_reviewed_split_remains_authoritative_price_era_memory(self):
        bulk_upsert_events([
            self._event(
                "split-reviewed",
                category="CORPORATE_ACTION",
                details="Stock split: face value of Rs 2 into face value of Rs 1. Ex-date 25-Aug-2026.",
            )
        ], db_path=self.db)
        set_event_status("split-reviewed", "REVIEWED", db_path=self.db)

        result = sync_official_bse_split_price_eras(
            self.series["series_id"],
            known_by="2026-08-25T12:00:00+00:00",
            db_path=self.db,
        )
        self.assertEqual(result["status"], "OFFICIAL_SPLIT_ERAS_SYNCHRONIZED")
        self.assertEqual(result["split_boundaries"], 1)

    def test_archived_dividend_remains_ex_date_context(self):
        bulk_upsert_events([
            self._event(
                "div-archived",
                category="DIVIDEND",
                details="Dividend of Rs 5 per equity share. Ex-date 25-Aug-2026.",
            )
        ], db_path=self.db)
        set_event_status("div-archived", "ARCHIVED", db_path=self.db)

        result = corporate_action_context_from_store(
            session_date="2026-08-25",
            known_by="2026-08-25T12:00:00+00:00",
            db_path=self.db,
        )
        self.assertTrue(result["dividend_ex_date"])
        self.assertTrue(result["mechanical_gap_risk"])
        self.assertFalse(result["raw_price_series_structural_break"])


if __name__ == "__main__":
    unittest.main()
