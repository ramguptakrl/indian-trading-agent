#!/usr/bin/env python3
"""Run Trade Brain after-market evidence refresh plus bounded v0.14 ML research.

The normal BSE study is authoritative. ML research is additive and fail-safe: a skipped,
insufficient, or failed ML cycle never converts a successful audited BSE study into failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

from backend.tradebrain.kite_data import KITE_SOURCE_KEY
from backend.tradebrain.market_data_store import find_series
from backend.tradebrain.ml_supervisor import run_ml_research_cycle
from backend.tradebrain.study_cycle_v2 import run_after_market_study_v2
from scripts.tradebrain_after_market_study import _acquire_supervisor_lock, _print_result, _reload_env


def _attach_ml(result: dict, *, deep: bool, cadence_days: int, disabled: bool) -> dict:
    if disabled:
        result["ml_research"] = {"status": "DISABLED_BY_OPERATOR", "order_execution_allowed": False}
        return result
    if result.get("status") not in {"SUCCESS", "SUCCESS_WITH_RESEARCH_WARNINGS", "ALREADY_COMPLETED_TODAY"}:
        return result
    series_id = result.get("series_id")
    if not series_id:
        series = find_series("NSE", "BSE", source_key=KITE_SOURCE_KEY)
        series_id = (series or {}).get("series_id")
    if not series_id:
        result["ml_research"] = {
            "status": "SKIPPED_NO_AUDITED_BSE_SERIES",
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
        return result
    try:
        ml = run_ml_research_cycle(
            str(series_id),
            as_of=result.get("now_ist"),
            deep_search=bool(deep),
            cadence_days=max(1, int(cadence_days)),
            force=False,
            code_version=os.getenv("TRADEBRAIN_CODE_VERSION") or "LOCAL_AFTER_MARKET",
        )
    except Exception as exc:
        ml = {
            "status": "FAILED_SAFE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:800],
            "automatic_policy_change": False,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    result["ml_research"] = ml
    return result


def _print_combined(result: dict) -> None:
    _print_result(result)
    ml = result.get("ml_research")
    if ml:
        print(json.dumps({
            "ml_status": ml.get("status"),
            "ml_run_id": ml.get("run_id"),
            "ml_deep_search": ml.get("deep_search"),
            "ml_tasks": ml.get("tasks"),
            "ml_order_execution_allowed": False,
        }, ensure_ascii=False, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description="Trade Brain after-market BSE study + ML research loop")
    parser.add_argument("--force", action="store_true", help="Force the base evidence study now; ML remains schedule-safe unless run via the dedicated optimizer script")
    parser.add_argument("--loop", action="store_true", help="Keep checking and run at most once per IST study date")
    parser.add_argument("--poll-seconds", type=int, default=900, help="Loop check interval; minimum 60 seconds")
    parser.add_argument("--bootstrap-daily-days", type=int, default=3650)
    parser.add_argument("--bootstrap-5m-days", type=int, default=1825)
    parser.add_argument("--bootstrap-15m-days", type=int, default=1825)
    parser.add_argument("--bootstrap-60m-days", type=int, default=1825)
    parser.add_argument("--incremental-days", type=int, default=14)
    parser.add_argument("--ml-deep", action="store_true", help="Use the broader controlled ML search when the cadence is due")
    parser.add_argument("--ml-cadence-days", type=int, default=7, help="Minimum days between automatic ML research runs")
    parser.add_argument("--skip-ml", action="store_true", help="Run evidence study without the ML research supervisor")
    args = parser.parse_args()
    if args.poll_seconds < 60:
        parser.error("--poll-seconds must be at least 60")
    if args.ml_cadence_days < 1:
        parser.error("--ml-cadence-days must be at least 1")

    if args.loop:
        acquired, existing_pid, lock_path = _acquire_supervisor_lock()
        if not acquired:
            print(json.dumps({
                "status": "SUPERVISOR_ALREADY_RUNNING",
                "existing_pid": existing_pid,
                "lock_path": str(lock_path),
                "order_execution_allowed": False,
            }))
            return 0
        print(json.dumps({
            "status": "SUPERVISOR_STARTED",
            "pid": os.getpid(),
            "lock_path": str(lock_path),
            "poll_seconds": args.poll_seconds,
            "ml_cadence_days": args.ml_cadence_days,
            "order_execution_allowed": False,
        }))
        sys.stdout.flush()

    last_console_signature = None
    while True:
        _reload_env()
        result = run_after_market_study_v2(
            force=args.force,
            bootstrap_daily_days=args.bootstrap_daily_days,
            bootstrap_5m_days=args.bootstrap_5m_days,
            bootstrap_15m_days=args.bootstrap_15m_days,
            bootstrap_60m_days=args.bootstrap_60m_days,
            incremental_days=args.incremental_days,
        )
        result = _attach_ml(
            result,
            deep=args.ml_deep,
            cadence_days=args.ml_cadence_days,
            disabled=args.skip_ml,
        )
        ml_status = (result.get("ml_research") or {}).get("status")
        signature = (result.get("status"), result.get("ist_date"), result.get("error_type"), ml_status)
        terminal = {"SUCCESS", "SUCCESS_WITH_RESEARCH_WARNINGS", "FAILED", "KITE_AUTH_REQUIRED", "BASE_CYCLE_NOT_READY"}
        if signature != last_console_signature or result.get("status") in terminal:
            _print_combined(result)
            sys.stdout.flush()
            last_console_signature = signature
        if not args.loop:
            okay = {"SUCCESS", "SUCCESS_WITH_RESEARCH_WARNINGS", "ALREADY_COMPLETED_TODAY", "SKIPPED_NOT_STUDY_TIME"}
            return 0 if result.get("status") in okay else 1
        args.force = False
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
