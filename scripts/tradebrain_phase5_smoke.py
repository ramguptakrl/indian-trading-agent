"""Non-blocking live smoke for Phase 5 frozen challenger mechanics.

This is NOT performance evidence. It uses recent real BSE Ltd 5-minute vendor data,
constructs a few synthetic plans solely to exercise Phase-4 strict replay, then freezes
TRAIN/VALIDATION/WALK_FORWARD windows and runs the Phase-5 challenger evaluator.
No promotion is performed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tradebrain.challenger import create_challenger, evaluate_challenger, freeze_challenger
from backend.tradebrain.focus_lab import evaluate_plan_replay_outcome
from backend.tradebrain.identity import ExchangeListing
from backend.tradebrain.market_data import sync_yahoo_history
from backend.tradebrain.market_data_store import find_series, query_bars
from backend.tradebrain.policy import TradePlan, evaluate_trade_plan
from backend.tradebrain.regime_hardening import install_phase4_regime_hardening
from backend.tradebrain.store import record_plan_evaluation, upsert_listing


def main() -> int:
    report = {
        "sync": None,
        "synthetic_plans": 0,
        "strict_outcomes": {},
        "challenger": None,
        "errors": {},
        "performance_claim": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(tmp, "tradebrain-data")
        db_path = os.path.join(tmp, "tradebrain-phase5-smoke.db")
        install_phase4_regime_hardening()
        upsert_listing(
            ExchangeListing(exchange="NSE", symbol="BSE", isin="INE118H01025"),
            listing_name="BSE Limited", security_name="BSE Limited",
            listing_status="ACTIVE", source_key="PHASE5_SMOKE_IDENTITY",
            source_timestamp=datetime.now(timezone.utc).isoformat(), db_path=db_path,
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
                    "price_mode", "interval", "rows_received", "bars_inserted",
                    "quality_issues", "snapshot_sha256",
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
        sessions: dict[str, list[dict]] = defaultdict(list)
        for bar in bars:
            sessions[bar["ts_open"][:10]].append(bar)
        session_days = sorted(sessions)
        if len(session_days) < 3:
            report["errors"]["sessions"] = f"Only {len(session_days)} sessions available"
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2

        # Use three chronologically separated sessions and two synthetic R:R variants
        # per session. These are mechanics fixtures built on real observed candles, not
        # a signal-generation or performance test.
        chosen = [session_days[0], session_days[len(session_days) // 2], session_days[-1]]
        outcome_counts: dict[str, int] = defaultdict(int)
        for day in chosen:
            anchor = sessions[day][min(2, len(sessions[day]) - 1)]
            entry = float(anchor["open"])
            for rr in (1.0, 2.0):
                plan = TradePlan(
                    ticker="BSE", exchange="NSE", mode="DAY", direction="LONG",
                    entry=entry, stop_loss=entry * 0.99,
                    take_profit=entry * (1 + 0.01 * rr),
                    crash_guard="NORMAL", broker_allows_trade=True,
                    evidence=["PHASE5_LIVE_SMOKE_SYNTHETIC_NOT_PERFORMANCE_EVIDENCE"],
                    evaluated_at_ist=datetime.fromisoformat(anchor["ts_open"]),
                )
                plan_id = record_plan_evaluation(plan, evaluate_trade_plan(plan), db_path=db_path)
                outcome = evaluate_plan_replay_outcome(
                    plan_id, series_id=series["series_id"], interval="5m",
                    as_of=bars[-1]["ts_close"], persist=True, db_path=db_path,
                )
                outcome_counts[outcome["outcome"]] += 1
                report["synthetic_plans"] += 1
        report["strict_outcomes"] = dict(sorted(outcome_counts.items()))

        # Freeze windows around the three selected session dates. Contiguous boundaries
        # are allowed; overlap is not.
        d0 = datetime.fromisoformat(chosen[0] + "T00:00:00+00:00")
        d1 = datetime.fromisoformat(chosen[1] + "T00:00:00+00:00")
        d2 = datetime.fromisoformat(chosen[2] + "T00:00:00+00:00")
        end = d2 + timedelta(days=1)
        # If midpoint selection is adjacent, boundaries remain valid because d0<d1<d2.
        experiment = create_challenger(
            name="Phase 5 live mechanics smoke",
            series_id=series["series_id"], interval="5m",
            parameter_key="day_min_reward_risk",
            incumbent_value=1.0, challenger_value=1.5,
            hypothesis="Mechanics-only challenger; no performance interpretation permitted.",
            thresholds={
                "min_eligible": 0, "min_entered": 0, "min_resolved": 0,
                "max_ambiguity_pct": 100.0, "min_coverage_pct": 0.0,
                "min_mean_r_improvement": 0.0, "max_tp_rate_drop_pp": 100.0,
                "required_validation_win_fraction": 0.0,
                "required_walk_forward_win_fraction": 0.0,
                "max_single_window_mean_r_drop": 999.0,
                "min_regime_resolved": 999,
                "max_regime_mean_r_drop": 999.0,
            },
            db_path=db_path,
        )
        frozen = freeze_challenger(
            experiment["experiment_id"],
            windows=[
                {"role": "TRAIN", "starts_at": d0.isoformat(), "ends_at": d1.isoformat()},
                {"role": "VALIDATION", "starts_at": d1.isoformat(), "ends_at": d2.isoformat()},
                {"role": "WALK_FORWARD", "starts_at": d2.isoformat(), "ends_at": end.isoformat()},
            ],
            db_path=db_path,
        )
        result = evaluate_challenger(experiment["experiment_id"], db_path=db_path)
        report["challenger"] = {
            "experiment_id": experiment["experiment_id"],
            "definition_sha256": frozen["experiment"]["definition_sha256"],
            "decision": result["decision"],
            "automatic_promotion": result["automatic_promotion"],
            "promotion_requires_explicit_human_approval": result["promotion_requires_explicit_human_approval"],
            "window_count": len(frozen["windows"]),
        }

        allowed = {"READY_FOR_REVIEW", "REJECTED", "NEEDS_MORE_DATA"}
        report["live_phase5_success"] = bool(
            report["sync"] and report["sync"].get("rows_received", 0) > 0
            and report["synthetic_plans"] >= 6
            and report["challenger"]
            and report["challenger"]["decision"] in allowed
            and len(report["challenger"]["definition_sha256"] or "") == 64
            and report["challenger"]["automatic_promotion"] is False
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0 if report["live_phase5_success"] and not report["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
