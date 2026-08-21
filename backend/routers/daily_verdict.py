"""Daily Verdict API — market context, not trade authorization."""

from fastapi import APIRouter
from backend.daily_verdict import compute_daily_verdict
from backend.tradebrain.soft_evidence import annotate_daily_verdict

router = APIRouter(prefix="/api/daily-verdict", tags=["daily-verdict"])


@router.get("/")
def get_verdict():
    """Synthesize market filters into a soft GREEN/YELLOW/RED context verdict.

    Side effects (best-effort, never raises):
    - Snapshots today's verdict to verdict_history if not already done.
    - Backfills forward Nifty returns + outcomes for ripe past snapshots.

    The result never authorizes a trade. Structured plans must pass the Trade Brain
    deterministic policy endpoint before they are treated as valid advisory setups.
    """
    result = compute_daily_verdict()
    try:
        from backend.verdict_calibration import snapshot_today, backfill_outcomes
        snapshot_today()
        backfill_outcomes()
    except Exception as e:
        print(f"[Daily Verdict] calibration hook failed: {e}", flush=True)
    return annotate_daily_verdict(result)
