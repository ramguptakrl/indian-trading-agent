#!/usr/bin/env python3
"""Convert Trade Brain unittest output into a compact human-readable TXT interpretation."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-log", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    log_path = Path(args.test_log)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", text)
    tests_run = int(match.group(1)) if match else None
    duration = match.group(2) if match else None
    passed = args.exit_code == 0 and re.search(r"(?m)^OK(?:\s|$)", text) is not None
    failures = len(re.findall(r"(?m)^FAIL:", text))
    errors = len(re.findall(r"(?m)^ERROR:", text))
    status = "PASS" if passed else "FAIL"

    if passed:
        interpretation = (
            "The deterministic Trade Brain regression suite completed successfully. "
            "This supports code/contract correctness for the tested paths, but it is not evidence of trading profitability."
        )
    else:
        interpretation = (
            "At least one Trade Brain regression check failed or the unittest run did not end in OK. "
            "Treat this build as not validated until the failing test is understood and fixed."
        )

    tail = [line for line in text.splitlines() if line.strip()][-30:]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "TRADE BRAIN TEST INTERPRETATION\n"
        + "=" * 72
        + "\n"
        + f"Generated UTC: {datetime.now(timezone.utc).isoformat()}\n"
        + f"Status: {status}\n"
        + f"Exit code: {args.exit_code}\n"
        + f"Tests run: {tests_run if tests_run is not None else 'UNKNOWN'}\n"
        + f"Duration seconds: {duration if duration is not None else 'UNKNOWN'}\n"
        + f"Failures detected: {failures}\n"
        + f"Errors detected: {errors}\n"
        + "\nINTERPRETATION\n"
        + interpretation
        + "\n\nBOUNDARY\n"
        + "A passing software test suite does not prove market edge, future returns, or broker execution safety under untested live conditions.\n"
        + "No hidden chain-of-thought is stored in this report.\n"
        + "\nTEST LOG TAIL\n"
        + "-" * 72
        + "\n"
        + "\n".join(tail)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
