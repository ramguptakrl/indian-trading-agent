"""Observational Phase-10 end-to-end smoke.

Uses official NSE calendar transport plus live BSE Ltd vendor candles, then constructs a
synthetic mechanics-only candidate from an observed completed bar. This validates
calendar -> structured parse -> deterministic gate -> resident costs -> execution-off
plumbing. It is NOT strategy-performance evidence.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tradebrain.advisory_pipeline import evaluate_final_advisory, research_label
from backend.tradebrain.exchange_calendar import collect_nse_cash_calendar
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data import sync_yahoo_history
from backend.tradebrain.market_data_store import find_series, query_bars
from backend.tradebrain.store import upsert_listing

IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    report = {
        "calendar": None,
        "sync": None,
        "candidate": None,
        "advisory": None,
        "performance_claim": False,
        "errors": {},
    }
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(tmp, "tradebrain-data")
        db_path = os.path.join(tmp, "phase10-smoke.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited", listing_status="ACTIVE",
            source_key="PHASE10_SMOKE_IDENTITY", source_timestamp=datetime.now(timezone.utc).isoformat(),
            db_path=db_path,
        )

        try:
            calendar = collect_nse_cash_calendar(db_path=db_path)
            report["calendar"] = {
                key: calendar.get(key) for key in (
                    "status", "exchange", "segment", "rows", "covered_years",
                    "source_url", "source_official", "sha256", "special_sessions_pending_times",
                )
            }
        except Exception as exc:
            report["errors"]["calendar"] = f"{type(exc).__name__}: {exc}"

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
            report["errors"]["market_data"] = f"{type(exc).__name__}: {exc}"

        series = find_series("NSE", "BSE", source_key="YAHOO_FINANCE_VIA_YFINANCE", db_path=db_path)
        if not series:
            report["errors"]["series"] = "No audited BSE series created"
        else:
            bars = query_bars(series["series_id"], "5m", limit=10000, db_path=db_path)
            candidates = []
            for bar in bars:
                opened = datetime.fromisoformat(bar["ts_open"]).astimezone(IST)
                if opened.time().hour < 14 and bar.get("is_final", True):
                    candidates.append((bar, opened))
            if not candidates:
                report["errors"]["bars"] = "No completed pre-14:00 IST bar available"
            else:
                bar, evaluated = candidates[-1]
                entry = float(bar["close"])
                text = f"""1. Candidate Verdict: BUY CANDIDATE
2. Trade Mode: INTRADAY
3. Direction: LONG
4. Entry Price: {entry:.4f}
5. Stop-Loss: {entry * 0.99:.4f}
6. Take-Profit: {entry * 1.02:.4f}
7. Risk-Reward Ratio: 2:1
12. Trade Brain Gate: NOT EVALUATED — candidate must pass deterministic Trade Brain gate before any advisory setup is considered valid.
"""
                report["candidate"] = {
                    "synthetic_from_observed_history": True,
                    "research_label": research_label(text),
                    "evaluated_at": evaluated.isoformat(),
                    "entry": round(entry, 4),
                    "performance_claim": False,
                }
                try:
                    advisory = evaluate_final_advisory(
                        ticker="BSE", exchange="NSE", final_trade_decision=text,
                        evaluated_at=evaluated, quantity=10, crash_guard="NORMAL",
                        broker_allows_trade=True, require_verified_calendar=True,
                        db_path=db_path,
                    )
                    report["advisory"] = {
                        "final_status": advisory.get("final_status"),
                        "calendar_verified": (advisory.get("calendar") or {}).get("calendar_verified"),
                        "gate_action": (advisory.get("gate") or {}).get("action"),
                        "soft_preference_source": (advisory.get("gate") or {}).get("preferred_reward_risk_source"),
                        "cost_status": (advisory.get("costs") or {}).get("status"),
                        "trade_authorization": advisory.get("trade_authorization"),
                        "order_execution_allowed": advisory.get("order_execution_allowed"),
                    }
                except Exception as exc:
                    report["errors"]["advisory"] = f"{type(exc).__name__}: {exc}"

        advisory = report.get("advisory") or {}
        report["live_phase10_success"] = bool(
            report.get("calendar") and report["calendar"].get("source_official") is True
            and report.get("sync") and report["sync"].get("rows_received", 0) > 0
            and report.get("candidate") and report["candidate"].get("research_label") == "LONG_CANDIDATE"
            and advisory.get("calendar_verified") is True
            and advisory.get("final_status") in {"ADVISORY_CANDIDATE_PASS", "WAIT", "BLOCK", "HARD_EXIT"}
            and advisory.get("trade_authorization") is False
            and advisory.get("order_execution_allowed") is False
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0 if report["live_phase10_success"] and not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
