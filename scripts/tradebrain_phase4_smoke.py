"""Non-blocking live smoke for Phase 4 strict outcome reconstruction.

This is a transport/mechanics smoke, not a performance backtest. It downloads recent
BSE Ltd 5-minute vendor history, builds one synthetic hypothetical plan from an early
observed bar, and verifies the strict outcome/cohort path can execute without guessing
intrabar order or touching real/manual outcomes.
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

from backend.tradebrain.focus_lab import evaluate_plan_replay_outcome, focus_cohort_report
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data import sync_yahoo_history
from backend.tradebrain.market_data_store import find_series, query_bars
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.store import record_plan_evaluation, upsert_listing


def main() -> int:
    report = {"sync": None, "plan": None, "outcome": None, "cohort": None, "errors": {}}
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(tmp, "tradebrain-data")
        db_path = os.path.join(tmp, "tradebrain-phase4-smoke.db")
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited", listing_status="ACTIVE",
            source_key="PHASE4_SMOKE_IDENTITY", source_timestamp=datetime.now(timezone.utc).isoformat(),
            db_path=db_path,
        )

        now = datetime.now(timezone.utc)
        try:
            sync = sync_yahoo_history(
                exchange="NSE", symbol="BSE", interval="5m",
                start=(now - timedelta(days=7)).isoformat(), end=(now + timedelta(days=1)).isoformat(),
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
        if not series:
            report["errors"]["series"] = "Audited 5m series was not created"
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2
        bars = query_bars(series["series_id"], "5m", limit=10000, db_path=db_path)
        if len(bars) < 20:
            report["errors"]["bars"] = f"Only {len(bars)} completed 5m bars available"
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2

        # Pick an early completed bar, not the most recent one, leaving future evidence
        # for the outcome engine. Parameters are constructed from observed history only
        # for smoke mechanics and MUST NOT be interpreted as a predictive strategy result.
        anchor = bars[max(0, len(bars) // 4)]
        entry = float(anchor["open"])
        plan = TradePlan(
            ticker="BSE", exchange="NSE", mode="SWING_POSITION", direction="LONG",
            entry=entry, stop_loss=entry * 0.99, take_profit=entry * 1.01,
            crash_guard="NORMAL", broker_allows_trade=True,
            evidence=["PHASE4_LIVE_SMOKE_SYNTHETIC_PLAN_NOT_PERFORMANCE_EVIDENCE"],
            evaluated_at_ist=datetime.fromisoformat(anchor["ts_open"]),
        )
        gate = evaluate_trade_plan(plan)
        plan_id = record_plan_evaluation(plan, gate, db_path=db_path)
        report["plan"] = {
            "plan_id": plan_id,
            "synthetic_from_observed_history": True,
            "performance_claim": False,
            "entry": round(entry, 4),
            "stop_loss": round(entry * 0.99, 4),
            "take_profit": round(entry * 1.01, 4),
            "evaluated_at": anchor["ts_open"],
        }

        try:
            outcome = evaluate_plan_replay_outcome(
                plan_id, series_id=series["series_id"], interval="5m", max_sessions=5,
                as_of=bars[-1]["ts_close"], persist=True, db_path=db_path,
            )
            report["outcome"] = {
                key: outcome.get(key) for key in (
                    "outcome", "entry_bar_open", "exit_bar_open", "mae_pct", "mfe_pct",
                    "r_multiple", "ambiguity_reason", "bars_observed", "sessions_observed",
                    "method_version", "observation_kind",
                )
            }
            cohort = focus_cohort_report(
                series_id=series["series_id"], interval="5m", db_path=db_path
            )
            report["cohort"] = {
                "n": cohort["overall"]["n"],
                "outcomes": cohort["overall"]["outcomes"],
                "profile": cohort["profile"],
                "promotion_rule": cohort["promotion_rule"],
            }
        except Exception as exc:
            report["errors"]["phase4"] = f"{type(exc).__name__}: {exc}"

        allowed = {"TP_FIRST", "SL_FIRST", "NEITHER", "NOT_ENTERED", "AMBIGUOUS", "INSUFFICIENT_DATA"}
        report["live_phase4_success"] = bool(
            report.get("sync") and report["sync"].get("rows_received", 0) > 0
            and report.get("outcome") and report["outcome"].get("outcome") in allowed
            and report.get("cohort") and report["cohort"].get("n") == 1
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0 if report["live_phase4_success"] and not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
