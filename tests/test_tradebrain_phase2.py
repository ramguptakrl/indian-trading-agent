import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.tradebrain.corporate_event_store import (
    bulk_upsert_events,
    event_stats,
    get_event,
    list_change_queue,
)
from backend.tradebrain.corporate_events import (
    BSE_SOURCE_KEY,
    NSE_SOURCE_KEY,
    classify_event,
    parse_bse_announcements,
    parse_nse_announcements_rss,
)
from backend.tradebrain.documents import (
    _allowed_official_url,
    extract_document_text,
    ingest_event_attachment,
)
from backend.tradebrain.event_identity import resolve_unresolved_events_exactly
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.security_store import bulk_upsert_listings


class Phase2TestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "phase2.db")
        self.old_data_dir = os.environ.get("TRADEBRAIN_DATA_DIR")
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "data")

    def tearDown(self):
        if self.old_data_dir is None:
            os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        else:
            os.environ["TRADEBRAIN_DATA_DIR"] = self.old_data_dir
        self.tmp.cleanup()

    def seed_listing(self, exchange, symbol, isin, name):
        return bulk_upsert_listings(
            [
                {
                    "listing": ExchangeListing(exchange=exchange, symbol=symbol, isin=isin),
                    "listing_name": name,
                    "security_name": name,
                    "listing_status": "ACTIVE",
                    "metadata": {},
                }
            ],
            source_key="TEST_MASTER",
            source_timestamp="2026-08-21T00:00:00+00:00",
            db_path=self.db_path,
        )

    def event(self, **overrides):
        base = {
            "event_id": "evt:test:1",
            "source_key": "TEST_EVENT_SOURCE",
            "exchange": "NSE",
            "source_event_id": "source-1",
            "event_fingerprint": "fingerprint-1",
            "listing_symbol": None,
            "isin": None,
            "company_name": "ACME LIMITED",
            "subject": "Award of Order",
            "details": "Company received a material work order",
            "category": "ORDER_CONTRACT",
            "subcategory": None,
            "source_category": None,
            "importance": "HIGH",
            "importance_basis": "RULE_BASED_HEURISTIC",
            "classification_version": "test-v1",
            "announced_at": "2026-08-21T10:00:00+00:00",
            "source_url": "https://www.nseindia.com/",
            "attachment_url": "https://nsearchives.nseindia.com/content/test/filing.html",
            "raw_artifact_id": None,
            "raw_item_sha256": "abc",
            "source_critical": False,
            "received_at": "2026-08-21T10:01:00+00:00",
            "raw_payload": {"test": True},
            "queue_for_change_review": True,
            "queue_priority": "HIGH",
            "queue_reason": "test material event",
        }
        base.update(overrides)
        return base


class CorporateEventParserTests(Phase2TestCase):
    def test_empty_nse_rss_is_legitimate_empty_feed(self):
        payload = b"<?xml version='1.0'?><rss><channel><title>NSE</title></channel></rss>"
        events, rejected = parse_nse_announcements_rss(payload)
        self.assertEqual(events, [])
        self.assertEqual(rejected, [])

    def test_malformed_nse_rss_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_nse_announcements_rss(b"<rss><channel>")

    def test_bse_scrip_and_attachment_are_normalized(self):
        payload = json.dumps(
            {
                "Table": [
                    {
                        "NEWSID": "news-1",
                        "SCRIP_CD": 500325,
                        "NEWSSUB": "RELIANCE INDUSTRIES LTD. - Award of Order / Receipt of Order",
                        "DT_TM": "2026-08-21T14:30:00",
                        "ATTACHMENTNAME": "filing.pdf",
                        "SLONGNAME": "RELIANCE INDUSTRIES LTD.",
                        "SUBCATNAME": "Award of Order / Receipt of Order",
                        "CRITICALNEWS": 0,
                    }
                ],
                "Table1": [{"ROWCNT": 1}],
            }
        ).encode()
        events, rejected, total = parse_bse_announcements(payload)
        self.assertEqual(rejected, [])
        self.assertEqual(total, 1)
        self.assertEqual(events[0]["listing_symbol"], "500325")
        self.assertTrue(events[0]["attachment_url"].endswith("/filing.pdf"))
        self.assertEqual(events[0]["category"], "ORDER_CONTRACT")
        self.assertEqual(events[0]["importance_basis"], "RULE_BASED_HEURISTIC")
        self.assertFalse(events[0]["source_critical"])

    def test_bse_string_zero_is_not_critical(self):
        payload = json.dumps(
            {
                "Table": [
                    {
                        "NEWSID": "news-zero",
                        "SCRIP_CD": 500325,
                        "NEWSSUB": "Routine filing",
                        "DT_TM": "2026-08-21T14:30:00",
                        "CRITICALNEWS": "0",
                    }
                ]
            }
        ).encode()
        events, _, _ = parse_bse_announcements(payload)
        self.assertFalse(events[0]["source_critical"])
        self.assertNotEqual(events[0]["importance_basis"], "BSE_SOURCE_CRITICAL+RULE_BASED_HEURISTIC")

    def test_classification_is_explicitly_heuristic(self):
        result = classify_event("Board Meeting to consider dividend")
        self.assertIn(result["importance"], {"MEDIUM", "HIGH"})
        self.assertEqual(result["importance_basis"], "RULE_BASED_HEURISTIC")
        self.assertTrue(result["queue_for_change_review"])


class CorporateEventIdentityTests(Phase2TestCase):
    def test_bse_event_links_by_exact_scrip_code(self):
        self.seed_listing("BSE", "500325", "INE002A01018", "RELIANCE INDUSTRIES LTD.")
        event = self.event(
            event_id="evt:bse:1",
            source_event_id="bse-1",
            exchange="BSE",
            listing_symbol="500325",
            company_name="RELIANCE INDUSTRIES LTD.",
        )
        stats = bulk_upsert_events([event], db_path=self.db_path)
        stored = get_event("evt:bse:1", db_path=self.db_path)
        self.assertEqual(stats["events_linked_to_entity"], 1)
        self.assertEqual(stored["isin"], "INE002A01018")
        self.assertEqual(stored["identity_method"], "EXACT_EXCHANGE_LISTING")

    def test_unresolved_nse_event_can_link_by_unique_exact_name(self):
        self.seed_listing("NSE", "ACME", "INE111A01010", "ACME LIMITED")
        event = self.event(event_id="evt:nse:name", source_event_id="nse-name")
        bulk_upsert_events([event], db_path=self.db_path)
        before = get_event("evt:nse:name", db_path=self.db_path)
        self.assertEqual(before["identity_status"], "UNRESOLVED")
        result = resolve_unresolved_events_exactly(db_path=self.db_path)
        after = get_event("evt:nse:name", db_path=self.db_path)
        self.assertEqual(result["exact_unique_name_links_added"], 1)
        self.assertEqual(after["listing_symbol"], "ACME")
        self.assertEqual(after["isin"], "INE111A01010")
        self.assertEqual(after["identity_method"], "EXACT_UNIQUE_LISTING_NAME")
        self.assertFalse(result["fuzzy_matching_used"])

    def test_ambiguous_exact_name_is_not_linked(self):
        self.seed_listing("NSE", "ACME1", "INE111A01010", "ACME LIMITED")
        self.seed_listing("NSE", "ACME2", "INE222A01020", "ACME LIMITED")
        event = self.event(event_id="evt:nse:amb", source_event_id="nse-amb")
        bulk_upsert_events([event], db_path=self.db_path)
        result = resolve_unresolved_events_exactly(db_path=self.db_path)
        stored = get_event("evt:nse:amb", db_path=self.db_path)
        self.assertEqual(result["ambiguous_exact_names_skipped"], 1)
        self.assertEqual(stored["identity_status"], "UNRESOLVED")

    def test_repeat_event_ingest_is_idempotent_and_queue_is_singleton(self):
        event = self.event(event_id="evt:repeat", source_event_id="repeat-1")
        first = bulk_upsert_events([event], db_path=self.db_path)
        second = bulk_upsert_events([event], db_path=self.db_path)
        stats = event_stats(self.db_path)
        queue = list_change_queue(db_path=self.db_path)
        self.assertEqual(first["events_inserted"], 1)
        self.assertEqual(second["events_updated"], 1)
        self.assertEqual(stats["total_events"], 1)
        self.assertEqual(len(queue), 1)


class DocumentMemoryTests(Phase2TestCase):
    def test_official_host_boundary_rejects_lookalike_domains(self):
        self.assertTrue(_allowed_official_url("https://www.bseindia.com/xml-data/test.pdf"))
        self.assertTrue(_allowed_official_url("https://nsearchives.nseindia.com/content/test.pdf"))
        self.assertFalse(_allowed_official_url("https://bseindia.com.evil.example/test.pdf"))
        self.assertFalse(_allowed_official_url("http://www.bseindia.com/test.pdf"))

    def test_repeat_same_attachment_deduplicates_by_sha(self):
        event = self.event(event_id="evt:doc", source_event_id="doc-1")
        bulk_upsert_events([event], db_path=self.db_path)
        payload = b"<html><body><h1>Material order</h1><p>Order value Rs 100 crore.</p></body></html>"
        final_url = "https://nsearchives.nseindia.com/content/test/filing.html"
        with patch("backend.tradebrain.documents._download", return_value=(payload, "text/html", final_url)):
            first = ingest_event_attachment("evt:doc", db_path=self.db_path)
            second = ingest_event_attachment("evt:doc", db_path=self.db_path)
        stats = event_stats(self.db_path)
        stored = get_event("evt:doc", db_path=self.db_path)
        self.assertEqual(first["document_id"], second["document_id"])
        self.assertEqual(stats["documents"], 1)
        self.assertEqual(len(stored["documents"]), 1)
        self.assertEqual(first["extraction_status"], "TEXT_EXTRACTED")
        self.assertGreater(first["text_chars"], 0)

    def test_blank_pdf_is_not_ocr_guessed(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        text, pages, status, metadata = extract_document_text(buffer.getvalue(), "PDF")
        self.assertIsNone(text)
        self.assertEqual(pages, 1)
        self.assertEqual(status, "NO_EMBEDDED_TEXT")
        self.assertIn("OCR was not attempted", metadata["reason"])


if __name__ == "__main__":
    unittest.main()
