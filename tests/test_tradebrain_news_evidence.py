"""Regression tests for Trade Brain official-first BSE news evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from backend.tradebrain.news_evidence import build_bse_news_evidence, news_evidence_for_prompt


class TradeBrainNewsEvidenceTests(unittest.TestCase):
    @patch("backend.tradebrain.news_evidence._is_today_ist", return_value=False)
    @patch("backend.tradebrain.news_evidence.query_news_known_by")
    @patch("backend.tradebrain.news_evidence.list_events")
    def test_historical_pack_uses_only_known_stored_evidence(self, list_events, query_news, _today):
        list_events.return_value = [
            {
                "isin": "INE118H01025",
                "exchange": "NSE",
                "listing_symbol": "BSE",
                "source_key": "NSE_CORPORATE_ANNOUNCEMENTS_RSS",
                "announced_at": "2026-08-20T05:00:00+00:00",
                "subject": "BSE Ltd official disclosure",
                "details": "Official fact",
                "attachment_url": "https://nsearchives.nseindia.com/example.pdf",
            },
            {
                "isin": "INE118H01025",
                "exchange": "NSE",
                "listing_symbol": "BSE",
                "source_key": "NSE_CORPORATE_ANNOUNCEMENTS_RSS",
                "announced_at": "2026-08-27T05:00:00+00:00",
                "subject": "Future disclosure",
            },
        ]
        query_news.return_value = [
            {
                "source": "MoneyControl - Markets",
                "source_type": "rss",
                "title": "BSE market context",
                "summary": "Secondary media interpretation",
                "url": "https://example.com/story",
                "published_at_source": "2026-08-20 10:00",
                "first_seen_at": "2026-08-20T05:00:00+00:00",
                "relevance": "BSE_DIRECT",
            }
        ]

        pack = build_bse_news_evidence("2026-08-26")
        self.assertEqual(len(pack["official_company_events"]), 1)
        self.assertEqual(pack["official_company_events"][0]["source_tier"], "OFFICIAL_EXCHANGE")
        self.assertEqual(pack["media_context"][0]["source_tier"], "MEDIA_CONTEXT")
        self.assertFalse(pack["media_context"][0]["official_fact"])
        self.assertEqual(pack["media_context"][0]["freshness_status"], "RECENT")
        self.assertTrue(pack["high_confidence_media_claim_requires_official_confirmation"])
        self.assertEqual(pack["media_freshness_window_days"], 30)
        self.assertEqual(pack["official_sebi_context"], [])

    @patch("backend.tradebrain.news_evidence._is_today_ist", return_value=False)
    @patch("backend.tradebrain.news_evidence.query_news_known_by")
    @patch("backend.tradebrain.news_evidence.list_events", return_value=[])
    def test_old_article_newly_seen_is_not_current_news(self, _events, query_news, _today):
        query_news.return_value = [
            {
                "source": "GuruFocus (via yfinance)",
                "source_type": "yfinance",
                "title": "BSE Ltd Q3 earnings call highlights",
                "summary": "Old earnings article rediscovered later",
                "url": "https://example.com/old-story",
                "published_at_source": "2026-02-09 10:00",
                "first_seen_at": "2026-08-26T05:00:00+00:00",
                "relevance": "BSE_DIRECT",
            }
        ]

        pack = build_bse_news_evidence("2026-08-26")
        self.assertEqual(pack["media_context"], [])
        self.assertTrue(pack["stale_or_undated_media_excluded_from_current_context"])
        prompt = news_evidence_for_prompt("2026-08-26")
        self.assertIn("Recent media context: unavailable", prompt)
        self.assertNotIn("Q3 earnings call highlights", prompt)

    @patch("backend.tradebrain.news_evidence._is_today_ist", return_value=True)
    @patch("backend.tradebrain.news_evidence.archive_current_bse_context_news")
    @patch("backend.tradebrain.news_evidence.collect_nse_corporate_events")
    @patch("backend.tradebrain.news_evidence._fetch_sebi_listing")
    @patch("backend.tradebrain.news_evidence.query_news_known_by", return_value=[])
    @patch("backend.tradebrain.news_evidence.list_events", return_value=[])
    def test_current_pack_refreshes_official_and_media_sources(
        self, _events, _news, sebi, collect_nse, archive_media, _today
    ):
        sebi.return_value = [
            {
                "source_tier": "OFFICIAL_REGULATOR",
                "source": "SEBI",
                "date": "Aug 26, 2026",
                "title": "Stock exchange market structure circular",
                "detail": "Official SEBI circular/press-release listing context.",
                "url": "https://www.sebi.gov.in/example",
                "official_fact": True,
            }
        ]
        pack = build_bse_news_evidence("2026-08-26")
        collect_nse.assert_called_once()
        archive_media.assert_called_once()
        self.assertGreaterEqual(sebi.call_count, 2)
        self.assertEqual(pack["official_sebi_context"][0]["source"], "SEBI")
        self.assertIn("NSE_OFFICIAL_REFRESH_OK", pack["refresh_notes"])
        self.assertIn("MEDIA_ARCHIVE_REFRESH_OK", pack["refresh_notes"])

    @patch("backend.tradebrain.news_evidence.build_bse_news_evidence")
    def test_prompt_declares_source_authority_and_media_confirmation_rule(self, build_pack):
        build_pack.return_value = {
            "official_company_events": [{
                "source": "NSE_CORPORATE_ANNOUNCEMENTS_RSS",
                "date": "2026-08-26",
                "title": "Official disclosure",
                "detail": "Fact",
            }],
            "official_sebi_context": [],
            "media_context": [{
                "source": "MoneyControl - Markets",
                "date": "2026-08-26",
                "title": "Media context",
                "detail": "Interpretation",
            }],
            "media_freshness_window_days": 30,
            "refresh_notes": [],
        }
        prompt = news_evidence_for_prompt("2026-08-26")
        self.assertIn("NSE/BSE official disclosure > SEBI official > archived major media", prompt)
        self.assertIn("Do not label a media-only claim HIGH confidence", prompt)
        self.assertIn("30 calendar days", prompt)
        self.assertIn("MoneyControl", prompt)


if __name__ == "__main__":
    unittest.main()
