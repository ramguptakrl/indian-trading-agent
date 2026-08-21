from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from backend.tradebrain.corporate_event_store import bulk_upsert_events
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data import (
    derive_timeframe,
    normalize_yfinance_frame,
    validate_bars,
)
from backend.tradebrain.market_data_store import (
    assign_price_eras,
    ensure_series,
    get_series,
    query_bars,
    rebuild_vendor_split_eras,
    upsert_bars,
    upsert_corporate_actions,
)
from backend.tradebrain.replay import build_replay_snapshot, compute_event_price_effects
from backend.tradebrain.store import upsert_listing


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        yield from self._rows


class Phase3Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tradebrain.db")
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(self.tmp.name, "data")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited",
            security_name="BSE Limited",
            listing_status="ACTIVE",
            source_key="TEST_MASTER",
            source_timestamp="2026-08-21T00:00:00+00:00",
            db_path=self.db,
        )
        self.series = ensure_series(
            exchange="NSE",
            symbol="BSE",
            source_key="TEST_VENDOR",
            source_symbol="BSE.NS",
            base_interval="5m",
            db_path=self.db,
        )

    def tearDown(self):
        os.environ.pop("TRADEBRAIN_DATA_DIR", None)
        self.tmp.cleanup()

    def bar(self, opened: str, closed: str, o=100, h=102, l=99, c=101, v=1000, era_id=None):
        return {
            "ts_open": opened,
            "ts_close": closed,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "source_timestamp": opened,
            "is_final": True,
            "era_id": era_id,
            "quality_flags": [],
        }


class MarketStoreReplayTests(Phase3Base):
    def test_series_is_bound_to_phase1_identity(self):
        self.assertEqual(self.series["isin"], "INE118H01025")
        with self.assertRaises(ValueError):
            ensure_series(
                exchange="NSE", symbol="NOTREAL", source_key="X", source_symbol="NOTREAL.NS", db_path=self.db
            )

    def test_as_of_excludes_bar_not_closed_yet(self):
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00"),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", o=101, h=103, l=100, c=102),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        visible = query_bars(
            self.series["series_id"], "5m", as_of="2026-08-21T03:52:00+00:00", db_path=self.db
        )
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["ts_close"], "2026-08-21T03:50:00+00:00")

    def test_replay_contains_only_events_known_by_as_of(self):
        event_base = {
            "source_key": "TEST_EVENTS", "exchange": "NSE", "event_fingerprint": "x",
            "listing_symbol": "BSE", "isin": "INE118H01025", "company_name": "BSE Limited",
            "subject": "Test", "details": None, "category": "GENERAL", "subcategory": None,
            "source_category": None, "importance": "LOW", "importance_basis": "RULE_BASED_HEURISTIC",
            "classification_version": "test", "source_url": "https://nseindia.com/test", "attachment_url": None,
            "raw_artifact_id": None, "raw_item_sha256": "x", "source_critical": False,
            "received_at": "2026-08-21T00:00:00+00:00", "raw_payload": {},
        }
        first = dict(event_base, event_id="evt:before", source_event_id="before", announced_at="2026-08-20T10:00:00+00:00")
        second = dict(event_base, event_id="evt:after", source_event_id="after", announced_at="2026-08-22T10:00:00+00:00")
        bulk_upsert_events([first, second], db_path=self.db)
        snap = build_replay_snapshot(
            exchange="NSE", symbol="BSE", as_of="2026-08-21T12:00:00+00:00",
            intervals=["5m"], source_key="TEST_VENDOR", db_path=self.db,
        )
        ids = [e["event_id"] for e in snap["events_known_by_as_of"]]
        self.assertIn("evt:before", ids)
        self.assertNotIn("evt:after", ids)
        self.assertTrue(snap["all_lookahead_checks_pass"])


class MarketDataValidationTests(Phase3Base):
    def test_intraday_gap_is_flagged_without_inventing_holiday_logic(self):
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00"),
            self.bar("2026-08-21T04:00:00+00:00", "2026-08-21T04:05:00+00:00"),
        ]
        issues = validate_bars(bars, "5m")
        self.assertTrue(any(x["issue_type"] == "INTRADAY_GAP" for x in issues))

    def test_normalizer_rejects_bad_ohlc_and_records_split(self):
        rows = [
            (
                datetime(2026, 8, 21, 9, 15, tzinfo=timezone(timedelta(hours=5, minutes=30))),
                {"Open": 100, "High": 102, "Low": 99, "Close": 101, "Volume": 1000, "Dividends": 0, "Stock Splits": 2},
            ),
            (
                datetime(2026, 8, 21, 9, 20, tzinfo=timezone(timedelta(hours=5, minutes=30))),
                {"Open": 100, "High": 90, "Low": 99, "Close": 101, "Volume": 1000, "Dividends": 0, "Stock Splits": 0},
            ),
        ]
        bars, issues, actions = normalize_yfinance_frame(
            _FakeFrame(rows), "5m", fetched_at=datetime(2026, 8, 22, tzinfo=timezone.utc)
        )
        self.assertEqual(len(bars), 1)
        self.assertTrue(any(x["issue_type"] == "INVALID_OHLC_GEOMETRY" for x in issues))
        self.assertEqual(actions[0]["action_type"], "SPLIT")


class DerivationTests(Phase3Base):
    def test_one_hour_bucket_is_anchored_to_0915_ist(self):
        bars = []
        start = datetime.fromisoformat("2026-08-21T03:45:00+00:00")  # 09:15 IST
        for i in range(12):
            opened = start + timedelta(minutes=5 * i)
            bars.append(self.bar(opened.isoformat(), (opened + timedelta(minutes=5)).isoformat(), o=100+i, h=102+i, l=99+i, c=101+i))
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = derive_timeframe(
            self.series["series_id"], source_interval="5m", target_interval="1h",
            as_of="2026-08-21T04:45:00+00:00", db_path=self.db,
        )
        self.assertEqual(result["derived"], 1)
        derived = query_bars(self.series["series_id"], "1h", as_of="2026-08-21T04:45:00+00:00", db_path=self.db)
        self.assertEqual(derived[0]["ts_open"], "2026-08-21T03:45:00+00:00")
        self.assertEqual(derived[0]["ts_close"], "2026-08-21T04:45:00+00:00")

    def test_partial_target_bucket_is_excluded(self):
        start = datetime.fromisoformat("2026-08-21T03:45:00+00:00")
        bars = []
        for i in range(6):
            opened = start + timedelta(minutes=5 * i)
            bars.append(self.bar(opened.isoformat(), (opened + timedelta(minutes=5)).isoformat()))
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = derive_timeframe(
            self.series["series_id"], source_interval="5m", target_interval="1h",
            as_of="2026-08-21T04:15:00+00:00", db_path=self.db,
        )
        self.assertEqual(result["derived"], 0)


class PriceEraTests(Phase3Base):
    def test_vendor_split_creates_raw_price_comparability_boundary(self):
        upsert_corporate_actions(
            self.series["series_id"],
            [{"action_type": "SPLIT", "effective_at": "2026-08-21T03:45:00+00:00", "value": 2.0}],
            source_key="TEST_VENDOR", db_path=self.db,
        )
        result = rebuild_vendor_split_eras(self.series["series_id"], db_path=self.db)
        self.assertEqual(result["split_boundaries"], 1)
        self.assertEqual(result["eras_created"], 2)


class EventPriceEffectTests(Phase3Base):
    def _insert_event(self, announced_at="2026-08-21T03:47:00+00:00"):
        event = {
            "event_id": "evt:test:phase3", "source_key": "TEST_EVENTS", "exchange": "NSE",
            "source_event_id": "phase3", "event_fingerprint": "phase3", "listing_symbol": "BSE",
            "isin": "INE118H01025", "company_name": "BSE Limited", "subject": "Order received",
            "details": None, "category": "ORDER_CONTRACT", "subcategory": None, "source_category": None,
            "importance": "HIGH", "importance_basis": "RULE_BASED_HEURISTIC",
            "classification_version": "test", "announced_at": announced_at,
            "source_url": "https://nseindia.com/test", "attachment_url": None, "raw_artifact_id": None,
            "raw_item_sha256": "phase3", "source_critical": False,
            "received_at": announced_at, "raw_payload": {},
        }
        bulk_upsert_events([event], db_path=self.db)
        return event["event_id"]

    def test_event_anchor_skips_candle_already_in_progress(self):
        event_id = self._insert_event()
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", o=100, h=105, l=99, c=104),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", o=104, h=106, l=103, c=105),
            self.bar("2026-08-21T03:55:00+00:00", "2026-08-21T04:00:00+00:00", o=105, h=108, l=104, c=107),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = compute_event_price_effects(
            event_id, series_id=self.series["series_id"], interval="5m",
            horizons_sessions=[1], persist=False, db_path=self.db,
        )
        effect = result["effects"][0]
        self.assertEqual(effect["anchor_bar_open"], "2026-08-21T03:50:00+00:00")
        self.assertEqual(effect["anchor_price"], 104.0)
        self.assertTrue(result["lookahead_safe"])

    def test_cross_price_era_effect_is_not_reported_as_comparable_return(self):
        event_id = self._insert_event("2026-08-21T03:44:00+00:00")
        bars = [
            self.bar("2026-08-21T03:45:00+00:00", "2026-08-21T03:50:00+00:00", era_id="era:a"),
            self.bar("2026-08-21T03:50:00+00:00", "2026-08-21T03:55:00+00:00", era_id="era:b"),
        ]
        upsert_bars(self.series["series_id"], "5m", bars, source_key="TEST_VENDOR", db_path=self.db)
        result = compute_event_price_effects(
            event_id, series_id=self.series["series_id"], interval="5m",
            horizons_sessions=[1], persist=False, db_path=self.db,
        )
        self.assertEqual(result["effects"][0]["status"], "RAW_PRICE_CROSSES_COMPARABILITY_ERA")


if __name__ == "__main__":
    unittest.main()
