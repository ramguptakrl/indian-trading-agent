"""Non-blocking live smoke for Phase 3 market-data transport and replay.

Uses a temporary DB, seeds only the known NSE:BSE identity needed for the smoke,
fetches raw/unadjusted daily Yahoo history through yfinance, and verifies replay can
reconstruct an earlier evidence boundary without future candles.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data import derive_timeframe, sync_yahoo_history
from backend.tradebrain.market_data_store import find_series, query_bars
from backend.tradebrain.replay import build_replay_snapshot
from backend.tradebrain.store import upsert_listing


def main() -> int:
    report: dict = {"sync": None, "derive": None, "replay": None, "errors": {}}
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(tmp, "tradebrain-data")
        db_path = os.path.join(tmp, "tradebrain-smoke.db")

        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited",
            listing_status="ACTIVE", source_key="PHASE3_SMOKE_IDENTITY",
            source_timestamp=datetime.now(timezone.utc).isoformat(), db_path=db_path,
        )

        now = datetime.now(timezone.utc)
        try:
            sync = sync_yahoo_history(
                exchange="NSE", symbol="BSE", interval="1d",
                start=(now - timedelta(days=45)).date().isoformat(),
                end=(now + timedelta(days=1)).date().isoformat(),
                incremental=False, db_path=db_path,
            )
            report["sync"] = {
                key: sync.get(key) for key in (
                    "status", "series_id", "source_key", "source_official", "source_symbol",
                    "price_mode", "interval", "rows_received", "bars_inserted", "bars_updated",
                    "quality_issues", "corporate_actions", "snapshot_sha256", "snapshot_kind",
                )
            }
        except Exception as exc:
            report["errors"]["sync"] = f"{type(exc).__name__}: {exc}"
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2

        series = find_series("NSE", "BSE", source_key="YAHOO_FINANCE_VIA_YFINANCE", db_path=db_path)
        if not series:
            report["errors"]["series"] = "Audited series was not created"
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2

        bars = query_bars(series["series_id"], "1d", limit=1000, db_path=db_path)
        if len(bars) < 5:
            report["errors"]["bars"] = f"Only {len(bars)} completed daily bars available"
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2

        cutoff = bars[-3]["ts_close"]
        try:
            derive = derive_timeframe(
                series["series_id"], source_interval="1d", target_interval="1w",
                as_of=cutoff, db_path=db_path,
            )
            report["derive"] = {
                key: derive.get(key) for key in (
                    "source_interval", "target_interval", "source_bars", "derived", "lookahead_safe",
                )
            }
        except Exception as exc:
            report["errors"]["derive"] = f"{type(exc).__name__}: {exc}"

        try:
            replay = build_replay_snapshot(
                exchange="NSE", symbol="BSE", as_of=cutoff,
                intervals=["1d", "1w"], source_key="YAHOO_FINANCE_VIA_YFINANCE",
                derive_missing_from="1d", bars_per_interval=100, event_limit=0, db_path=db_path,
            )
            report["replay"] = {
                "as_of": replay["as_of"],
                "all_lookahead_checks_pass": replay["all_lookahead_checks_pass"],
                "daily_bars": replay["frames"]["1d"]["bar_count"],
                "weekly_bars": replay["frames"]["1w"]["bar_count"],
                "daily_latest_close": replay["frames"]["1d"]["latest_completed_bar_close"],
                "weekly_latest_close": replay["frames"]["1w"]["latest_completed_bar_close"],
            }
        except Exception as exc:
            report["errors"]["replay"] = f"{type(exc).__name__}: {exc}"

        report["live_market_data_success"] = bool(
            report.get("sync") and report["sync"].get("rows_received", 0) > 0
            and report.get("replay") and report["replay"].get("all_lookahead_checks_pass")
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0 if report["live_market_data_success"] and not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
