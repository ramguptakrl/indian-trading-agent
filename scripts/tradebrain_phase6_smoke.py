"""Observational Phase-6 smoke: live vendor data -> resident paper net economics.

This is a mechanics/transport test, not strategy-performance evidence. It uses recent
BSE Ltd 5-minute vendor candles to create and close one synthetic INTRADAY paper
position. No broker order API is used.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tradebrain.equity_costs import cost_profile, data_credential_boundary
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data import sync_yahoo_history
from backend.tradebrain.market_data_store import find_series, query_bars
from backend.tradebrain.paper_ledger import (
    close_paper_position,
    create_paper_account,
    open_paper_position,
)
from backend.tradebrain.store import upsert_listing

IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    report = {
        "sync": None,
        "paper": None,
        "boundary": data_credential_boundary(),
        "profile": None,
        "errors": {},
        "performance_claim": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(tmp, "tradebrain-data")
        db_path = os.path.join(tmp, "tradebrain-phase6-smoke.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited", listing_status="ACTIVE",
            source_key="PHASE6_SMOKE_IDENTITY", source_timestamp=datetime.now(timezone.utc).isoformat(),
            db_path=db_path,
        )

        now = datetime.now(timezone.utc)
        try:
            sync = sync_yahoo_history(
                exchange="NSE", symbol="BSE", interval="5m",
                start=(now - timedelta(days=7)).date().isoformat(),
                end=(now + timedelta(days=1)).date().isoformat(),
                incremental=False, db_path=db_path,
            )
            report["sync"] = {
                key: sync.get(key) for key in (
                    "status", "series_id", "source_key", "source_official", "source_symbol",
                    "price_mode", "interval", "rows_received", "bars_inserted", "quality_issues",
                    "snapshot_sha256",
                )
            }
        except Exception as exc:
            report["errors"]["sync"] = f"{type(exc).__name__}: {exc}"
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2

        series = find_series("NSE", "BSE", source_key="YAHOO_FINANCE_VIA_YFINANCE", db_path=db_path)
        bars = query_bars(series["series_id"], "5m", limit=10000, db_path=db_path) if series else []
        sessions = defaultdict(list)
        for bar in bars:
            local = datetime.fromisoformat(bar["ts_open"]).astimezone(IST)
            clock = local.time().replace(tzinfo=None)
            if clock.hour < 15 or (clock.hour == 15 and clock.minute <= 0):
                sessions[local.date().isoformat()].append(bar)
        usable = next((items for _, items in sorted(sessions.items()) if len(items) >= 8), None)
        if not usable:
            report["errors"]["bars"] = "No completed session with enough pre-15:10 bars"
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2

        entry_bar = usable[2]
        exit_bar = usable[7]
        account = create_paper_account(name="PHASE6_LIVE_SMOKE", starting_cash=1_000_000, db_path=db_path)
        try:
            opened = open_paper_position(
                account_id=account["account_id"], ticker="BSE", exchange="NSE",
                mode="INTRADAY", direction="LONG", quantity=10,
                entry_price=float(entry_bar["open"]), entry_timestamp=entry_bar["ts_open"],
                data_source="YAHOO_FINANCE_VIA_YFINANCE_LIVE_SMOKE",
                db_path=db_path,
            )
            closed = close_paper_position(
                position_id=opened["position_id"], exit_price=float(exit_bar["close"]),
                exit_timestamp=exit_bar["ts_close"], db_path=db_path,
            )
            report["paper"] = {
                "position_id": closed["position_id"],
                "mode": closed["mode"],
                "direction": closed["direction"],
                "status": closed["status"],
                "mode_violation": closed["mode_violation"],
                "gross_pnl": closed["gross_pnl"],
                "total_charges": closed["total_charges"],
                "net_pnl": closed["net_pnl"],
                "financing_interest": closed["economics"]["charges"]["financing_interest"],
                "mtf_used": closed["economics"]["mtf_used"],
                "funded_amount": closed["economics"]["funded_amount"],
                "data_source": closed["data_source"],
                "synthetic_from_observed_history": True,
            }
        except Exception as exc:
            report["errors"]["paper"] = f"{type(exc).__name__}: {exc}"

        profile = cost_profile()
        report["profile"] = {
            "profile_key": profile["profile_key"],
            "trader_profile": profile["trader_profile"],
            "active_modes": profile["active_modes"],
            "mtf_enabled": profile["mtf_enabled"],
            "swing_funding": profile["swing_funding"],
        }
        report["live_phase6_success"] = bool(
            report.get("sync") and report["sync"].get("rows_received", 0) > 0
            and report.get("paper") and report["paper"].get("status") == "CLOSED"
            and report["paper"].get("mode") == "INTRADAY"
            and report["paper"].get("financing_interest") == 0
            and report["paper"].get("mtf_used") is False
            and report["paper"].get("funded_amount") == 0
            and report["boundary"].get("trader_profile") == "RESIDENT_INDIAN"
            and report["boundary"].get("order_api_enabled") is False
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0 if report["live_phase6_success"] and not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
