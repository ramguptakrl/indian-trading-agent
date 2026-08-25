#!/usr/bin/env python3
"""Run Trade Brain's audited after-market evidence-learning cycle.

Default behavior is one cycle. Use --loop to leave a lightweight local supervisor
running; it checks the exchange-aware operating mode and executes at most once per IST
date after market close/non-trading study mode.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tradebrain.study_cycle_v2 import run_after_market_study_v2


def _reload_env() -> None:
    load_dotenv(ROOT / ".env", override=True)


def _print_result(result: dict) -> None:
    safe = dict(result)
    if safe.get("status") in {"SUCCESS", "SUCCESS_WITH_RESEARCH_WARNINGS"}:
        history = safe.get("history") or {}
        mtf_wrap = safe.get("multi_timeframe") or {}
        mtf = mtf_wrap.get("result") if mtf_wrap.get("status") == "SUCCESS" else {}
        pattern_wrap = safe.get("pattern_lab_15m") or {}
        pattern = pattern_wrap.get("result") if pattern_wrap.get("status") == "SUCCESS" else {}
        candle_shapes = pattern.get("candlestick_shapes") or {}
        print(json.dumps({
            "status": safe.get("status"),
            "method_version": safe.get("method_version"),
            "ist_date": safe.get("ist_date"),
            "bootstrap": safe.get("bootstrap"),
            "series_id": safe.get("series_id"),
            "fifteen_minute_rows": (history.get("fifteen_minute") or {}).get("rows_received"),
            "sixty_minute_rows": (history.get("sixty_minute") or {}).get("rows_received"),
            "mtf_alignment": mtf.get("alignment"),
            "opening_gap": mtf.get("opening_gap"),
            "pattern_occurrences": {name: item.get("occurrences") for name, item in candle_shapes.items()},
            "fvg": pattern.get("fair_value_gaps"),
            "research_warnings": safe.get("research_warnings") or [],
            "audit_txt": safe.get("audit_txt"),
            "order_execution_allowed": False,
        }, ensure_ascii=False, default=str))
    else:
        print(json.dumps(safe, ensure_ascii=False, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description="Trade Brain after-market Kite study/replay loop")
    parser.add_argument("--force", action="store_true", help="Run research cycle now even outside post-market study mode")
    parser.add_argument("--loop", action="store_true", help="Keep checking and run once per IST date when study mode is active")
    parser.add_argument("--poll-seconds", type=int, default=900, help="Loop check interval; minimum 60 seconds")
    parser.add_argument("--bootstrap-daily-days", type=int, default=3650)
    parser.add_argument("--bootstrap-5m-days", type=int, default=1825)
    parser.add_argument("--bootstrap-15m-days", type=int, default=1825)
    parser.add_argument("--bootstrap-60m-days", type=int, default=1825)
    parser.add_argument("--incremental-days", type=int, default=14)
    args = parser.parse_args()
    if args.poll_seconds < 60:
        parser.error("--poll-seconds must be at least 60")

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
        signature = (result.get("status"), result.get("ist_date"), result.get("error_type"))
        terminal_statuses = {"SUCCESS", "SUCCESS_WITH_RESEARCH_WARNINGS", "FAILED", "KITE_AUTH_REQUIRED", "BASE_CYCLE_NOT_READY"}
        if signature != last_console_signature or result.get("status") in terminal_statuses:
            _print_result(result)
            sys.stdout.flush()
            last_console_signature = signature

        if not args.loop:
            okay = {"SUCCESS", "SUCCESS_WITH_RESEARCH_WARNINGS", "ALREADY_COMPLETED_TODAY", "SKIPPED_NOT_STUDY_TIME"}
            return 0 if result.get("status") in okay else 1
        # --force in loop mode deliberately applies only to the first pass.
        args.force = False
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
