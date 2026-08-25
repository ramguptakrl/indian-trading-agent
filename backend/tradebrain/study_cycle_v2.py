"""Trade Brain after-market study V2.

V2 preserves the tested V1 daily/5m bootstrap/replay/prospective cycle, then adds:
- audited 15m history
- audited 60m history
- D -> derived 4H -> 1H -> 15m research snapshot
- research-only candlestick/FVG studies
- research-only Fibonacci and candle-volume-at-price proxy features
- point-in-time BSE/India news memory from first observation forward
- audited Kite NIFTY 50 daily context for broader-market correction awareness

Nothing in this module can modify hard policy, promote a soft parameter automatically,
or place/modify/cancel a broker order.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.tradebrain.api_governor import KITE_API_GOVERNOR
from backend.tradebrain.audit_txt import audit_learning
from backend.tradebrain.context_index import nifty50_correction_context, sync_kite_nifty50_daily
from backend.tradebrain.kite_data import KiteDataOnlyClient
from backend.tradebrain.kite_history_range import sync_kite_history_range
from backend.tradebrain.multi_timeframe import multi_timeframe_snapshot
from backend.tradebrain.news_archive import archive_current_bse_context_news
from backend.tradebrain.pattern_lab import pattern_lab_study
from backend.tradebrain.schedule import get_operating_mode
from backend.tradebrain.structure_lab import structure_lab_snapshot
from backend.tradebrain.study_cycle import (
    ALLOWED_STUDY_MODES,
    DEFAULT_BOOTSTRAP_5M_DAYS,
    DEFAULT_BOOTSTRAP_DAILY_DAYS,
    DEFAULT_INCREMENTAL_DAYS,
    run_after_market_study,
)

IST = ZoneInfo("Asia/Kolkata")
METHOD_VERSION = "AFTER_MARKET_STUDY_V2_MTF_PATTERN_CONTEXT"
DEFAULT_BOOTSTRAP_15M_DAYS = DEFAULT_BOOTSTRAP_5M_DAYS
DEFAULT_BOOTSTRAP_60M_DAYS = DEFAULT_BOOTSTRAP_5M_DAYS


def _data_root() -> Path:
    configured = os.getenv("TRADEBRAIN_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "tradebrain"


def default_v2_state_path() -> Path:
    root = _data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "after_market_study_v2_state.json"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


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
        "order_api_enabled": False,
    }


def _safe_research(callable_obj, *args, **kwargs) -> dict[str, Any]:
    try:
        return {"status": "SUCCESS", "result": callable_obj(*args, **kwargs)}
    except Exception as exc:
        return {
            "status": "RESEARCH_WARNING",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "trade_authorization": False,
            "order_execution_allowed": False,
        }


def run_after_market_study_v2(
    *,
    now: datetime | None = None,
    force: bool = False,
    bootstrap_daily_days: int = DEFAULT_BOOTSTRAP_DAILY_DAYS,
    bootstrap_5m_days: int = DEFAULT_BOOTSTRAP_5M_DAYS,
    bootstrap_15m_days: int = DEFAULT_BOOTSTRAP_15M_DAYS,
    bootstrap_60m_days: int = DEFAULT_BOOTSTRAP_60M_DAYS,
    incremental_days: int = DEFAULT_INCREMENTAL_DAYS,
    state_path: str | Path | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    if min(bootstrap_daily_days, bootstrap_5m_days, bootstrap_15m_days, bootstrap_60m_days, incremental_days) <= 0:
        raise ValueError("Study lookback days must be positive")

    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=IST)
    else:
        current = current.astimezone(IST)
    session_key = current.date().isoformat()
    operating = get_operating_mode(current, exchange="NSE", db_path=db_path, require_verified_calendar=False)
    path = Path(state_path).expanduser() if state_path else default_v2_state_path()
    state = _load(path)

    if not force and operating.get("mode") not in ALLOWED_STUDY_MODES:
        return {
            "status": "SKIPPED_NOT_STUDY_TIME",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "operating_mode": operating,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
    if not force and state.get("last_success_ist_date") == session_key:
        return {
            "status": "ALREADY_COMPLETED_TODAY",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "state_path": str(path),
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    base = run_after_market_study(
        now=current,
        force=force,
        bootstrap_daily_days=bootstrap_daily_days,
        bootstrap_5m_days=bootstrap_5m_days,
        incremental_days=incremental_days,
        db_path=db_path,
    )
    if base.get("status") not in {"SUCCESS", "ALREADY_COMPLETED_TODAY"}:
        return {
            "status": "BASE_CYCLE_NOT_READY",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "base": base,
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    api_key = (os.getenv("KITE_API_KEY") or "").strip()
    access_token = (os.getenv("KITE_ACCESS_TOKEN") or "").strip()
    if not api_key or not access_token:
        return {
            "status": "KITE_AUTH_REQUIRED",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "reason": "KITE_API_KEY and KITE_ACCESS_TOKEN are required locally",
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }

    bootstrap = not bool(state.get("bootstrap_completed"))
    days_15m = bootstrap_15m_days if bootstrap else incremental_days
    days_60m = bootstrap_60m_days if bootstrap else incremental_days
    days_nifty = bootstrap_daily_days if bootstrap else incremental_days
    client = KiteDataOnlyClient(api_key=api_key, access_token=access_token)

    try:
        instrument = client.resolve_equity_instrument("NSE", "BSE")
        token = int(instrument["instrument_token"])
        history_15m = sync_kite_history_range(
            exchange="NSE", symbol="BSE", interval="15minute",
            from_time=current - timedelta(days=days_15m), to_time=current,
            instrument_token=token, client=client, db_path=db_path,
        )
        history_60m = sync_kite_history_range(
            exchange="NSE", symbol="BSE", interval="60minute",
            from_time=current - timedelta(days=days_60m), to_time=current,
            instrument_token=token, client=client, db_path=db_path,
        )
        series_id = history_15m.get("series_id") or history_60m.get("series_id") or base.get("series_id")
        if not series_id:
            raise ValueError("V2 study could not resolve the audited NSE:BSE market series")

        nifty_sync = _safe_research(
            sync_kite_nifty50_daily,
            from_time=current - timedelta(days=days_nifty),
            to_time=current,
            client=client,
            db_path=db_path,
        )

        as_of = current.isoformat()
        mtf = _safe_research(multi_timeframe_snapshot, series_id, as_of=as_of, db_path=db_path)
        patterns_15m = _safe_research(pattern_lab_study, series_id, as_of=as_of, db_path=db_path, interval="15m")
        patterns_daily = _safe_research(pattern_lab_study, series_id, as_of=as_of, db_path=db_path, interval="1d")
        structure = _safe_research(structure_lab_snapshot, series_id, as_of=as_of, db_path=db_path)
        news_memory = _safe_research(
            archive_current_bse_context_news,
            max_per_source=4,
            observed_at=current,
            db_path=db_path,
        )
        broader_market = _safe_research(nifty50_correction_context, as_of=current, db_path=db_path)

        named_research = (
            ("multi_timeframe", mtf),
            ("patterns_15m", patterns_15m),
            ("patterns_daily", patterns_daily),
            ("structure_lab", structure),
            ("news_memory", news_memory),
            ("nifty50_context_sync", nifty_sync),
            ("broader_market_context", broader_market),
        )
        warnings = [name for name, item in named_research if item.get("status") != "SUCCESS"]
        if broader_market.get("status") == "SUCCESS" and (broader_market.get("result") or {}).get("status") != "AUDITED_NIFTY_DAILY_CONTEXT":
            warnings.append("broader_market_context_incomplete")
        final_status = "SUCCESS" if not warnings else "SUCCESS_WITH_RESEARCH_WARNINGS"
        result = {
            "status": final_status,
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "now_ist": current.isoformat(),
            "operating_mode": operating.get("mode"),
            "bootstrap": bootstrap,
            "series_id": series_id,
            "base_cycle": {
                "status": base.get("status"),
                "method_version": base.get("method_version"),
                "audit_txt": base.get("audit_txt"),
            },
            "history": {
                "fifteen_minute": _history_summary(history_15m),
                "sixty_minute": _history_summary(history_60m),
                "nifty50_daily": nifty_sync,
            },
            "multi_timeframe": mtf,
            "pattern_lab_15m": patterns_15m,
            "pattern_lab_daily": patterns_daily,
            "structure_lab": structure,
            "news_memory": news_memory,
            "broader_market_context": broader_market,
            "research_warnings": sorted(set(warnings)),
            "api_governor": KITE_API_GOVERNOR.snapshot(),
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
            "AFTER_MARKET_STUDY_V2",
            result,
            interpretation=(
                "V2 preserved the V1 replay/prospective study and added audited 15m/60m history, "
                "D-4H-1H-15m context, candlestick/FVG research, Fibonacci/candle-volume structure "
                "research, point-in-time news memory, and context-only audited Kite NIFTY 50 daily "
                "evidence. No live policy or broker authority changed."
            ),
        )
        result["audit_txt"] = audit_path
        _save(
            path,
            {
                "method_version": METHOD_VERSION,
                "bootstrap_completed": True,
                "last_success_ist_date": session_key,
                "last_success_at_ist": current.isoformat(),
                "series_id": series_id,
                "last_status": final_status,
            },
        )
        return result
    except Exception as exc:
        failed = {
            "status": "FAILED",
            "method_version": METHOD_VERSION,
            "ist_date": session_key,
            "now_ist": current.isoformat(),
            "operating_mode": operating.get("mode"),
            "bootstrap": bootstrap,
            "error_type": type(exc).__name__,
            "error": str(exc)[:800],
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
        }
        failed["audit_txt"] = audit_learning(
            "AFTER_MARKET_STUDY_V2_FAILED",
            failed,
            interpretation="V2 research extension failed safely. No broker order path or automatic policy mutation exists.",
        )
        return failed
