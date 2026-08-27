#!/usr/bin/env python3
"""Run Trade Brain v0.14 BSE ML research against the local audited market store."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

from backend.tradebrain.kite_data import KITE_SOURCE_KEY
from backend.tradebrain.ml_supervisor import TASK_ORDER, run_ml_research_cycle
from backend.tradebrain.market_data_store import find_series


def _bse_series_id() -> str:
    series = find_series("NSE", "BSE", source_key=KITE_SOURCE_KEY)
    if not series:
        raise RuntimeError("No audited Kite NSE:BSE market-data series exists locally. Run the Kite history bootstrap first.")
    return str(series["series_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Trade Brain v0.14 BSE-only ML optimizer")
    parser.add_argument("--deep", action="store_true", help="Run the broader controlled feature/hyperparameter search")
    parser.add_argument("--task", choices=TASK_ORDER, action="append", help="Limit to one or more ML tasks; default is all three")
    parser.add_argument("--as-of", default=None, help="Point-in-time cutoff (ISO timestamp); default is now")
    parser.add_argument("--code-version", default=os.getenv("TRADEBRAIN_CODE_VERSION") or "LOCAL_MANUAL")
    args = parser.parse_args()
    try:
        result = run_ml_research_cycle(
            _bse_series_id(),
            as_of=args.as_of,
            tasks=tuple(args.task or TASK_ORDER),
            deep_search=bool(args.deep),
            force=True,
            code_version=args.code_version,
        )
    except Exception as exc:
        print(json.dumps({
            "status": "FAILED_SAFE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:800],
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("status") in {"SUCCESS", "SUCCESS_WITH_RESEARCH_WARNINGS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
