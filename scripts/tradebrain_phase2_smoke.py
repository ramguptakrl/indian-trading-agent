"""Non-blocking live smoke for Phase 2 exchange transport.

Used by CI only as observational evidence. Unit tests remain the deterministic gate;
exchange anti-bot/network behavior must not make core CI flaky.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Running `python scripts/...py` otherwise places only `scripts/` on sys.path.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.tradebrain.corporate_event_store import list_events
from backend.tradebrain.corporate_events import (
    collect_bse_corporate_events,
    collect_nse_corporate_events,
)
from backend.tradebrain.documents import ingest_event_attachment

IST = ZoneInfo("Asia/Kolkata")


def main() -> int:
    report: dict = {"collectors": {}, "attachment": None, "errors": {}}
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TRADEBRAIN_DATA_DIR"] = os.path.join(tmp, "tradebrain-data")
        db_path = os.path.join(tmp, "tradebrain-smoke.db")

        try:
            report["collectors"]["NSE"] = collect_nse_corporate_events(timeout=20, db_path=db_path)
        except Exception as exc:
            report["errors"]["NSE"] = f"{type(exc).__name__}: {exc}"

        try:
            today = datetime.now(IST).date()
            report["collectors"]["BSE"] = collect_bse_corporate_events(
                from_date=today - timedelta(days=3),
                to_date=today,
                max_pages=2,
                timeout=20,
                db_path=db_path,
            )
        except Exception as exc:
            report["errors"]["BSE"] = f"{type(exc).__name__}: {exc}"

        # Prefer BSE because its API provides direct AttachLive URLs; fall back to NSE.
        candidates = list_events(status=None, exchange="BSE", limit=50, db_path=db_path)
        candidates += list_events(status=None, exchange="NSE", limit=50, db_path=db_path)
        for event in candidates:
            if not event.get("attachment_url"):
                continue
            try:
                result = ingest_event_attachment(event["event_id"], timeout=20, db_path=db_path)
                report["attachment"] = {
                    "event_id": event["event_id"],
                    "exchange": event["exchange"],
                    "document_id": result["document_id"],
                    "sha256": result["sha256"],
                    "document_type": result["document_type"],
                    "extraction_status": result["extraction_status"],
                    "size_bytes": result["size_bytes"],
                }
                break
            except Exception as exc:
                report["errors"][f"ATTACHMENT:{event['event_id']}"] = f"{type(exc).__name__}: {exc}"

        report["live_collector_success"] = bool(report["collectors"])
        report["live_attachment_downloaded"] = report["attachment"] is not None
        print(json.dumps(report, indent=2, sort_keys=True, default=str))

    # The workflow step itself is continue-on-error. A non-zero exit is useful because
    # GitHub visibly distinguishes "transport unavailable" from a fully successful smoke.
    return 0 if report["live_collector_success"] and report["live_attachment_downloaded"] else 2


if __name__ == "__main__":
    sys.exit(main())
