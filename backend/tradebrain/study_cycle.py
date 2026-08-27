"""Automatic after-market evidence/study cycle for Trade Brain.

This is deliberately a research/evidence loop, not autonomous trading and not LLM
fine-tuning. It refreshes audited Zerodha Kite historical candles, replays already
recorded BSE plans, updates the frozen prospective BSE hypothesis, and writes a
human-readable sanitized audit summary.

Protected rules are never changed here. No broker order endpoint is available or
called by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.audit_txt import audit_learning
from backend.tradebrain.exploratory_studies import opening_gap_exploration
from backend.tradebrain.focus_lab import evaluate_plan_replay_outcome
from backend.tradebrain.focus_lab_store import list_plans
from backend.tradebrain.kite_data import KiteDataOnlyClient
from backend.tradebrain.kite_history_range import sync_kite_history_range
from backend.tradebrain.prospective_gap import collect_prospective_gap_observations
from backend.tradebrain.schedule import get_operating_mode
from backend.tradebrain.security_master import collect_nse_security_master
from backend.tradebrain.security_store import get_exchange_listing

IST = ZoneInfo("Asia/Kolkata")
ALLOWED_STUDY_MODES = {"POST_MARKET_STUDY", "STUDY_REPLAY"}
DEFAULT_BOOTSTRAP_DAILY_DAYS = 3650
DEFAULT_BOOTSTRAP_5M_DAYS = 1825
DEFAULT_INCREMENTAL_DAYS = 14
METHOD_VERSION = "AFTER_MARKET_STUDY_V1"


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


def default_state_path() -> Path:
    root = _data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "after_market_study_state.json"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _token_fingerprint() -> str | None:
    """One-way local change detector; never return or persist the token itself."""
    token = (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _ensure_bse_phase1_identity(*, db_path: str | None = None) -> dict[str, Any]:
    """Ensure NSE:BSE exists in the audited Phase-1 identity store.

    Fresh Windows installs can have valid Kite credentials but an empty local Phase-1
    database. Historical market-data ingestion must not bypass the identity boundary, so
    the study cycle self-bootstraps from the official NSE equity master only when the
    exact NSE:BSE listing is absent.
    """
    listing = get_exchange_listing("NSE", "BSE", db_path=db_path)
    if listing is not None:
        return {
            "status": "ALREADY_PRESENT",
            "exchange": "NSE",
            "symbol": "BSE",
            "isin": listing.get("isin"),
            "source": "PHASE1_LOCAL_IDENTITY_STORE",
        }

    refresh = collect_nse_security_master(db_path=db_path)
    listing = get_exchange_listing("NSE", "BSE", db_path=db_path)
    if listing is None:
        raise ValueError(
            "Phase 1 NSE security master refreshed successfully but NSE:BSE is still unknown; "
            "audited market-data creation remains blocked"
        )

    return {
        "status": "REFRESHED",
        "exchange": "NSE",
        "symbol": "BSE",
        "isin": listing.get("isin"),
        "source": "NSE_EQUITY_SECURITY_MASTER",
        "collector_status": refresh.get("status"),
        "rows_valid": refresh.get("rows_valid"),
        "rows_rejected": refresh.get("rows_rejected"),
    }


def _history_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "interval": result.get("interval"),
        "kite_interval": result.get("kite_interval"),
        "range_start": result.get("range_start"),
        "range_end": result.get("range_end"),
        "chunks": result.get("chunks"),
        "rows_received": result.get("rows_received"),
        "bars_inserted": result.get("bars_inserted"),
        "bars_updated": result.get("bars_updated"),
        "quality_issues_reported_across_chunks": result.get("quality_issues_reported_across_chunks"),
        "source_key": result.get("source_key"),
        "credential_role": result.get("credential_role"),
        "order_api_enabled": result.get("order_api_enabled"),
    }


def _prospective_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "hypothesis_id": result.get("hypothesis_id"),
        "freeze_date": result.get("freeze_date"),
        "eligible_observations": result.get("eligible_observations"),
        "skipped": result.get("skipped") or {},
        "summary": result.get("summary") or {},
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def _exploration_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "method_version": result.get("method_version"),
        "daily_bars": result.get("daily_bars"),
        "eligible_directional_gap_observations": result.get("eligible_directional_gap_observations"),
        "cross_price_era_transitions_excluded": result.get("cross_price_era_transitions_excluded"),
        "thresholds_pct": result.get("thresholds_pct"),
        "cohorts": result.get("cohorts") or {},
        "exploratory_only": True,
        "eligible_for_direct_phase5_promotion": False,
    }


def _replay_existing_bse_plans(
    *,
    series_id: str,
    as_of: str,
    db_path: str | None,
    limit: int = 5000,
) -> dict[str, Any]:
    plans = list_plans(exchange="NSE", ticker="BSE", limit=limit, db_path=db_path)
    counts: dict[str, int] = {}
    failures: list[dict[str, str]] = []
    for plan in plans:
        plan_id = str(plan.get("plan_id") or "")
        if not plan_id:
            continue
        try:
            outcome = evaluate_plan_replay_outcome(
                plan_id,
                series_id=series_id,
                interval="5m",
                max_sessions=10,
                as_of=as_of,
                persist=True,
                db_path=db_path,
            )
            key = str(outcome.get("outcome") or "UNKNOWN")
            counts[key] = counts.get(key, 0) + 1
        except Exception as exc:
            failures.append({"plan_id": plan_id, "error_type": type(exc).__name__, "error": str(exc)[:240]})
    return {
        "plans_seen": len(plans),
        "outcomes": dict(sorted(counts.items())),
        "failures": failures[:50],
        "failure_count": len(failures),
        "observation_kind": "HYPOTHETICAL_REPLAY",
        "automatic_policy_change": False,
    }


def run_after_market_study(
    *,
    now: datetime | None = None,
    force: bool = False,
    bootstrap_daily_days: int = DEFAULT_BOOTSTRAP_DAILY_DAYS,
    bootstrap_5m_days: int = DEFAULT_BOOTSTRAP_5M_DAYS,
    incremental_days: int = DEFAULT_INCREMENTAL_DAYS,
    state_path: str | Path | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run one idempotent evidence-learning cycle for NSE:BSE."""
    if min(bootstrap_daily_days, bootstrap_5m_days, incremental_days) <= 0:
        raise ValueError("Study lookback days must be positive")

    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    else:
        current = current.astimezone(IST)
    as_of = current.isoformat()
    session_key = current.date().isoformat()
    operating = get_operating_mode(current, exchange="NSE", db_path=db_path, require_verified_calendar=False)

    path = Path(state_path).expanduser() if state_path else default_state_path()
    state = _load_state(path)
    if not force and operating.get("mode") not in ALLOWED_STUDY_MODES:
        return {
            "status": "SKIPPED_NOT_STUDY_TIME",
            "method_version": METHOD_VERSION,
            "operating_mode": operating,
            "advisory_only": True,
            "order_execution_allowed": False,
        }
    if not force and state.get("last_success_ist_date") == session_key:
        return {
            "status": "ALREADY_COMPLETED_TODAY",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "state_path": str(path),
            "advisory_only": True,
            "order_execution_allowed": False,
        }

    api_key = (os.getenv("KITE_API_KEY") or "").strip()
    access_token = (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
    if not api_key or not access_token:
        result = {
            "status": "KITE_AUTH_REQUIRED",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "reason": "KITE_API_KEY and KITE_ACCESS_TOKEN are required locally",
            "advisory_only": True,
            "order_execution_allowed": False,
        }
        audit_learning(
            "AFTER_MARKET_STUDY_AUTH_REQUIRED",
            result,
            interpretation="Study cycle did not run because local Kite market-data credentials were unavailable. No order path exists.",
        )
        return result

    bootstrap = not bool(state.get("bootstrap_completed"))
    daily_days = bootstrap_daily_days if bootstrap else incremental_days
    intraday_days = bootstrap_5m_days if bootstrap else incremental_days
    client = KiteDataOnlyClient(api_key=api_key, access_token=access_token)
    token_fingerprint = _token_fingerprint()

    try:
        phase1_identity = _ensure_bse_phase1_identity(db_path=db_path)
        instrument = client.resolve_equity_instrument("NSE", "BSE")
        instrument_token = int(instrument["instrument_token"])
        daily_result = sync_kite_history_range(
            exchange="NSE",
            symbol="BSE",
            interval="day",
            from_time=current - timedelta(days=daily_days),
            to_time=current,
            instrument_token=instrument_token,
            client=client,
            db_path=db_path,
        )
        five_result = sync_kite_history_range(
            exchange="NSE",
            symbol="BSE",
            interval="5minute",
            from_time=current - timedelta(days=intraday_days),
            to_time=current,
            instrument_token=instrument_token,
            client=client,
            db_path=db_path,
        )
        series_id = str(five_result.get("series_id") or daily_result.get("series_id") or "")
        if not series_id:
            raise RuntimeError("Kite history sync returned no audited series_id")

        exploration = opening_gap_exploration(series_id, as_of=as_of, db_path=db_path)
        replays = _replay_existing_bse_plans(series_id=series_id, as_of=as_of, db_path=db_path)

        prospective_error = None
        try:
            prospective = collect_prospective_gap_observations(
                series_id,
                as_of=as_of,
                require_verified_calendar=True,
                persist=True,
                db_path=db_path,
            )
            prospective_summary = _prospective_summary(prospective)
        except Exception as exc:
            prospective_error = {"error_type": type(exc).__name__, "error": str(exc)[:500]}
            prospective_summary = {
                "status": "NOT_UPDATED",
                "reason": prospective_error,
                "automatic_promotion": False,
            }

        result = {
            "status": "SUCCESS",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "now_ist": as_of,
            "operating_mode": operating.get("mode"),
            "bootstrap": bootstrap,
            "phase1_identity": phase1_identity,
            "series_id": series_id,
            "history": {
                "daily": _history_summary(daily_result),
                "five_minute": _history_summary(five_result),
            },
            "exploration": _exploration_summary(exploration),
            "replay": replays,
            "prospective_hypothesis": prospective_summary,
            "prospective_error": prospective_error,
            "learning_boundary": {
                "llm_weights_modified": False,
                "hard_rules_modified": False,
                "soft_parameters_auto_promoted": False,
                "research_evidence_updated": True,
                "human_review_required_for_promotion": True,
            },
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
        audit_path = audit_learning(
            "AFTER_MARKET_STUDY_COMPLETED",
            result,
            interpretation=(
                "Phase-1 identity was verified, Kite history was refreshed, and audited research/replay evidence was updated. "
                "This is evidence learning only: no LLM weights, protected rules, broker orders, or automatic promotion changed."
            ),
        )
        result["audit_txt"] = audit_path
        _save_state(
            path,
            {
                **state,
                "method_version": METHOD_VERSION,
                "bootstrap_completed": True,
                "last_success_ist_date": session_key,
                "last_success_at_ist": as_of,
                "last_status": "SUCCESS",
                "last_access_token_fingerprint": token_fingerprint,
                "series_id": series_id,
            },
        )
        return result
    except Exception as exc:
        result = {
            "status": "FAILED",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "now_ist": as_of,
            "operating_mode": operating.get("mode"),
            "bootstrap": bootstrap,
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
        audit_path = audit_learning(
            "AFTER_MARKET_STUDY_FAILED",
            result,
            interpretation="The evidence-study cycle stopped safely. No policy was changed and no broker order endpoint exists in this path.",
        )
        result["audit_txt"] = audit_path
        _save_state(
            path,
            {
                **state,
                "method_version": METHOD_VERSION,
                "last_attempt_ist_date": session_key,
                "last_attempt_at_ist": as_of,
                "last_status": "FAILED",
                "last_error_type": type(exc).__name__,
                "last_access_token_fingerprint": token_fingerprint,
            },
        )
        return result
