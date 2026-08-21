"""Build the first real BSE Ltd descriptive evidence baseline.

This runner intentionally does not generate a trading strategy or win rate. It deepens
BSE Ltd data coverage through the existing audited Yahoo/yfinance adapter, assigns
vendor-split comparability eras, and writes an auditable JSON + Markdown evidence pack.
Yahoo is non-official and its intraday lookback limits are reported as source limits.
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

from backend.tradebrain.evidence_baseline import build_evidence_baseline, render_evidence_markdown
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data import sync_yahoo_history
from backend.tradebrain.market_data_store import assign_price_eras, find_series, query_bars
from backend.tradebrain.store import upsert_listing


def _summary(sync: dict) -> dict:
    keys = (
        "status", "series_id", "source_key", "source_official", "source_symbol",
        "price_mode", "interval", "rows_received", "bars_inserted", "bars_updated",
        "quality_issues", "corporate_actions", "snapshot_sha256",
    )
    return {key: sync.get(key) for key in keys}


def main() -> int:
    now = datetime.now(timezone.utc)
    report: dict = {
        "purpose": "BSE Ltd descriptive evidence baseline; no strategy selected",
        "performance_claim": False,
        "syncs": {},
        "baseline": None,
        "errors": {},
    }
    output_dir = Path(os.getenv("TRADEBRAIN_EVIDENCE_OUTPUT_DIR", "artifacts/evidence"))
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(tmp, "tradebrain-data")
        db_path = os.path.join(tmp, "bse-evidence.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited", listing_status="ACTIVE",
            source_key="EVIDENCE_RUNNER_IDENTITY", source_timestamp=now.isoformat(), db_path=db_path,
        )

        # Keep intraday requests comfortably inside Yahoo's rolling limits. Using the
        # next calendar day as an exclusive end can accidentally push an otherwise
        # valid 59/729-day request beyond Yahoo's 60/730-day boundary.
        requests = {
            "daily": {"interval": "1d", "start": "2017-01-01", "end": (now + timedelta(days=1)).date().isoformat()},
            "hourly": {"interval": "1h", "start": (now - timedelta(days=700)).date().isoformat(), "end": now.date().isoformat()},
            "five_minute": {"interval": "5m", "start": (now - timedelta(days=55)).date().isoformat(), "end": now.date().isoformat()},
        }

        series_id = None
        for name, req in requests.items():
            try:
                result = sync_yahoo_history(
                    exchange="NSE", symbol="BSE", interval=req["interval"],
                    start=req["start"], end=req["end"], incremental=False, db_path=db_path,
                )
                report["syncs"][name] = _summary(result)
                series_id = series_id or result.get("series_id")
            except Exception as exc:
                report["errors"][name] = f"{type(exc).__name__}: {exc}"

        series = find_series("NSE", "BSE", source_key="YAHOO_FINANCE_VIA_YFINANCE", db_path=db_path)
        if series:
            series_id = series["series_id"]
        if not series_id:
            report["errors"]["series"] = "No audited BSE series was created"
        else:
            for interval in ("1d", "1h", "5m"):
                try:
                    assign_price_eras(series_id, interval, db_path=db_path)
                except Exception as exc:
                    report["errors"][f"era_assignment_{interval}"] = f"{type(exc).__name__}: {exc}"
            try:
                baseline = build_evidence_baseline(
                    series_id, daily_interval="1d", intraday_interval="5m",
                    as_of=now.isoformat(), persist=True, db_path=db_path,
                )
                report["baseline"] = baseline
            except Exception as exc:
                report["errors"]["baseline"] = f"{type(exc).__name__}: {exc}"

        # Coverage details are written even if one optional intraday transport failed.
        if series_id:
            report["stored_bar_counts"] = {
                interval: len(query_bars(series_id, interval, as_of=now.isoformat(), limit=500000, db_path=db_path))
                for interval in ("1d", "1h", "5m")
            }

    json_path = output_dir / "bse_evidence_baseline.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    if report.get("baseline"):
        md_path = output_dir / "bse_evidence_baseline.md"
        md_path.write_text(render_evidence_markdown(report["baseline"]), encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    daily_rows = ((report.get("syncs") or {}).get("daily") or {}).get("rows_received", 0) or 0
    baseline = report.get("baseline") or {}
    return 0 if daily_rows >= 250 and baseline.get("claims", {}).get("strategy_edge_claimed") is False else 2


if __name__ == "__main__":
    sys.exit(main())
