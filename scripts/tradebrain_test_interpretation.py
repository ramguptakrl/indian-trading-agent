#!/usr/bin/env python3
"""Convert Trade Brain pytest/unittest output into a compact human-readable TXT interpretation."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path


def _summary(text: str) -> tuple[int | None, str | None, int, int, int]:
    """Return tests_run, duration, passed_count, failures, errors for pytest or unittest."""
    unittest_match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", text)
    if unittest_match:
        total = int(unittest_match.group(1))
        duration = unittest_match.group(2)
        failures = len(re.findall(r"(?m)^FAIL:", text))
        errors = len(re.findall(r"(?m)^ERROR:", text))
        passed_count = max(0, total - failures - errors)
        return total, duration, passed_count, failures, errors

    # Typical pytest tail: "235 passed in 8.12s" or
    # "2 failed, 233 passed, 1 error in 9.01s".
    tail_matches = re.findall(r"(?m)^=+\s*(.+?)\s+in\s+([0-9.]+)s\s*=+$", text)
    if not tail_matches:
        tail_matches = re.findall(r"(?m)^(.+?)\s+in\s+([0-9.]+)s\s*$", text)
    if tail_matches:
        summary, duration = tail_matches[-1]
        passed_count = int(re.search(r"(\d+)\s+passed", summary).group(1)) if re.search(r"(\d+)\s+passed", summary) else 0
        failures = int(re.search(r"(\d+)\s+failed", summary).group(1)) if re.search(r"(\d+)\s+failed", summary) else 0
        errors = int(re.search(r"(\d+)\s+errors?", summary).group(1)) if re.search(r"(\d+)\s+errors?", summary) else 0
        skipped = int(re.search(r"(\d+)\s+skipped", summary).group(1)) if re.search(r"(\d+)\s+skipped", summary) else 0
        xfailed = int(re.search(r"(\d+)\s+xfailed", summary).group(1)) if re.search(r"(\d+)\s+xfailed", summary) else 0
        xpassed = int(re.search(r"(\d+)\s+xpassed", summary).group(1)) if re.search(r"(\d+)\s+xpassed", summary) else 0
        total = passed_count + failures + errors + skipped + xfailed + xpassed
        return total or None, duration, passed_count, failures, errors

    return None, None, 0, 0, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-log", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    log_path = Path(args.test_log)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    tests_run, duration, passed_count, failures, errors = _summary(text)
    unittest_ok = re.search(r"(?m)^OK(?:\s|$)", text) is not None
    pytest_ok = passed_count > 0 and failures == 0 and errors == 0
    passed = args.exit_code == 0 and (unittest_ok or pytest_ok)
    status = "PASS" if passed else "FAIL"

    if passed:
        interpretation = (
            "The Trade Brain regression suite completed successfully across the configured test runner. "
            "This supports code/contract correctness for the tested paths, but it is not evidence of trading profitability."
        )
    else:
        interpretation = (
            "At least one Trade Brain regression check failed or the test run did not end in a recognized successful summary. "
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
        + f"Passed detected: {passed_count}\n"
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
