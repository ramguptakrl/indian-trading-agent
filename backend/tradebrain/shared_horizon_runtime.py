"""Shared BSE research + independent horizon decision runtime.

The paired analysis architecture intentionally pulls/researches the common BSE evidence
once, then forks into two separate downstream decision graphs:

    shared Market/Social/News/Fundamentals research
                         |
             +-----------+-----------+
             |                       |
        INTRADAY decision        SWING decision

Bull/Bear research, research management, Trader, risk debate, and Portfolio Manager are
horizon-specific. The shared pack is evidence only and never becomes a shared verdict.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from backend.db import save_analysis
from backend.stats_callback import StatsCallback
from backend.tradebrain.advisory_store import save_final_advisory
from backend.tradebrain.live_decision_context import (
    build_bse_decision_context,
    decision_context_for_prompt,
)
from backend.tradebrain.llm_failover import (
    get_capacity_fallback_config,
    is_retryable_llm_capacity_error,
    public_capacity_error,
)
from backend.tradebrain.llm_verifier import verify_material_finding
from backend.ws import manager
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import (
    GRAPH_MODE_DECISION_FROM_SHARED_RESEARCH,
    GRAPH_MODE_SHARED_RESEARCH_ONLY,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph

SHARED_RESEARCH_VERSION = "BSE_SHARED_RESEARCH_PACK_V1"
_REPORT_BY_ANALYST = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}
_SHARED_REPORT_FIELDS = tuple(_REPORT_BY_ANALYST.values())
_DOWNSTREAM_REPORT_FIELDS = (
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
)


def _capacity_attempt(
    config: dict[str, Any],
    execute: Callable[[dict[str, Any]], Any],
) -> tuple[Any, dict[str, Any], bool]:
    """Execute primary then one configured capacity fallback, if appropriate."""
    active_config = dict(config)
    try:
        return execute(active_config), active_config, False
    except Exception as primary_error:
        if not is_retryable_llm_capacity_error(primary_error):
            raise

        fallback_config = get_capacity_fallback_config(active_config)
        if fallback_config is None:
            raise RuntimeError(
                public_capacity_error(primary_error, fallback_available=False)
            ) from primary_error

        try:
            return execute(fallback_config), fallback_config, True
        except Exception as fallback_error:
            if is_retryable_llm_capacity_error(fallback_error):
                raise RuntimeError(
                    public_capacity_error(fallback_error, fallback_available=True)
                ) from fallback_error
            raise RuntimeError(
                "Automatic alternate-provider attempt could not complete the analysis: "
                f"{str(fallback_error)[:500]}"
            ) from fallback_error


def build_shared_research_pack(
    *,
    ticker: str,
    trade_date: str,
    config: dict[str, Any],
    selected_analysts: list[str],
    pack_id: str | None = None,
    on_report: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Run common BSE analyst research exactly once and freeze the resulting pack."""
    if not selected_analysts:
        raise ValueError("At least one analyst is required for shared BSE research")

    # Deterministic audited market context is built once here and injected unchanged into
    # both downstream horizon states. This prevents duplicate DB/context construction.
    context = build_bse_decision_context(trade_date)
    context_prompt = decision_context_for_prompt(context)

    shared_config = dict(config)
    shared_config["graph_mode"] = GRAPH_MODE_SHARED_RESEARCH_ONLY
    shared_config.pop("requested_trade_mode", None)

    def execute(current_config: dict[str, Any]) -> dict[str, Any]:
        ta = TradingAgentsGraph(
            selected_analysts=selected_analysts,
            debug=False,
            config=current_config,
        )
        propagator = Propagator(max_recur_limit=current_config.get("max_recur_limit", 100))
        initial_state = propagator.create_initial_state(
            ticker,
            trade_date,
            multi_timeframe_context=context_prompt,
        )
        final_state = None
        seen: dict[str, str] = {}
        for chunk in ta.graph.stream(initial_state, **propagator.get_graph_args()):
            final_state = chunk
            for field in _SHARED_REPORT_FIELDS:
                value = chunk.get(field)
                if value and value != seen.get(field):
                    seen[field] = str(value)
                    if on_report is not None:
                        on_report(field, str(value))
        if final_state is None:
            raise RuntimeError("Shared BSE research graph completed without producing a state")
        return final_state

    final_state, active_config, failover_used = _capacity_attempt(shared_config, execute)
    reports = {field: str(final_state.get(field) or "") for field in _SHARED_REPORT_FIELDS}

    missing = [
        _REPORT_BY_ANALYST[analyst]
        for analyst in selected_analysts
        if analyst in _REPORT_BY_ANALYST and not reports.get(_REPORT_BY_ANALYST[analyst])
    ]
    if missing:
        raise RuntimeError(
            "Shared BSE research did not produce required report(s): " + ", ".join(missing)
        )

    provider_config = dict(active_config)
    provider_config.pop("graph_mode", None)
    return {
        "pack_id": pack_id or f"research-{str(uuid.uuid4())[:8]}",
        "version": SHARED_RESEARCH_VERSION,
        "ticker": "BSE",
        "trade_date": trade_date,
        "analysts": list(selected_analysts),
        "reports": reports,
        "multi_timeframe_context": context_prompt,
        "context_status": context.get("status"),
        "context_as_of": context.get("as_of"),
        "context_source": context.get("source_key"),
        "candidate_evidence_complete": bool(context.get("candidate_evidence_complete")),
        "provider": str(active_config.get("llm_provider") or "unknown").lower(),
        "provider_config": provider_config,
        "llm_failover_used": failover_used,
        "shared_final_decision": False,
        "trade_authorization": False,
        "order_execution_allowed": False,
    }


def run_horizon_from_shared_pack(
    *,
    task_id: str,
    ticker: str,
    trade_date: str,
    mode: str,
    selected_analysts: list[str],
    shared_pack: dict[str, Any],
    tasks: dict[str, dict],
    analysis_advisory: Callable[[str, str, str, str], dict[str, Any]],
) -> None:
    """Run one horizon-specific decision graph using a frozen shared research pack."""
    loop = asyncio.new_event_loop()
    start_time = time.time()
    tasks[task_id]["status"] = "running"
    tasks[task_id]["stage"] = "horizon_decision"
    stats = StatsCallback()

    base_config = dict(shared_pack["provider_config"])
    base_config["requested_trade_mode"] = mode
    base_config["graph_mode"] = GRAPH_MODE_DECISION_FROM_SHARED_RESEARCH

    def send(payload: dict[str, Any]) -> None:
        loop.run_until_complete(manager.send_event(task_id, payload))

    def execute(current_config: dict[str, Any]):
        ta = TradingAgentsGraph(
            selected_analysts=selected_analysts,
            debug=False,
            config=current_config,
            callbacks=[stats],
        )
        propagator = Propagator(max_recur_limit=current_config.get("max_recur_limit", 100))
        initial_state = propagator.create_initial_state(
            ticker,
            trade_date,
            multi_timeframe_context=str(shared_pack["multi_timeframe_context"]),
        )
        initial_state.update(shared_pack["reports"])

        # Surface the exact same analyst reports in both UI trails. They were generated
        # once; these are re-used events, not second analyst calls or second data pulls.
        for field, value in shared_pack["reports"].items():
            if value:
                send({
                    "type": "report",
                    "section": field,
                    "content": value,
                    "shared_research": True,
                    "shared_research_pack_id": shared_pack["pack_id"],
                })

        previous: dict[str, str] = dict(shared_pack["reports"])
        final_state = None
        chunk_count = 0
        for chunk in ta.graph.stream(initial_state, **propagator.get_graph_args()):
            final_state = chunk
            chunk_count += 1
            last_activity = ""
            if chunk.get("messages"):
                msg = chunk["messages"][-1]
                content = getattr(msg, "content", "")
                preview = str(content)[:80] if isinstance(content, str) else "tool result"
                last_activity = f"{type(msg).__name__}: {preview}"
            send({
                "type": "heartbeat",
                "chunk": chunk_count,
                "last_activity": last_activity[:120],
                "shared_research_pack_id": shared_pack["pack_id"],
            })

            for field in _DOWNSTREAM_REPORT_FIELDS:
                value = chunk.get(field)
                if value and value != previous.get(field):
                    previous[field] = str(value)
                    send({"type": "report", "section": field, "content": value})

            invest_state = chunk.get("investment_debate_state") or {}
            bull = invest_state.get("bull_history", "")
            bear = invest_state.get("bear_history", "")
            if bull and bull != previous.get("bull_history"):
                previous["bull_history"] = bull
                send({"type": "debate", "side": "bull", "content": bull})
            if bear and bear != previous.get("bear_history"):
                previous["bear_history"] = bear
                send({"type": "debate", "side": "bear", "content": bear})
            judge = invest_state.get("judge_decision", "")
            if judge and judge != previous.get("judge_decision"):
                previous["judge_decision"] = judge
                send({"type": "report", "section": "investment_plan", "content": judge})

            risk_state = chunk.get("risk_debate_state") or {}
            for side in ("aggressive", "conservative", "neutral"):
                key = f"{side}_history"
                value = risk_state.get(key, "")
                cache_key = f"risk_{key}"
                if value and value != previous.get(cache_key):
                    previous[cache_key] = value
                    send({"type": "risk_debate", "side": side, "content": value})

        if final_state is None:
            raise RuntimeError("Horizon decision graph completed without producing a state")
        return ta, final_state

    try:
        (ta, final_state), active_config, decision_failover_used = _capacity_attempt(
            base_config,
            execute,
        )
        final_text = str(final_state.get("final_trade_decision") or "")
        research_label = ta.process_signal(final_text)
        active_provider = str(active_config.get("llm_provider") or "unknown").lower()

        material_verifier = verify_material_finding(
            research_label=research_label,
            final_trade_decision=final_text,
            market_report=shared_pack["reports"].get("market_report"),
            news_report=shared_pack["reports"].get("news_report"),
            fundamentals_report=shared_pack["reports"].get("fundamentals_report"),
            config=active_config,
        )
        exchange = str(active_config.get("default_exchange") or "NSE").upper()
        tradebrain_advisory = analysis_advisory(ticker, trade_date, exchange, final_text)

        duration = time.time() - start_time
        stats_summary = stats.summary()
        stats_summary["material_verifier"] = material_verifier
        stats_summary["shared_research"] = {
            "pack_id": shared_pack["pack_id"],
            "version": shared_pack["version"],
            "provider": shared_pack["provider"],
            "llm_failover_used": shared_pack["llm_failover_used"],
            "context_as_of": shared_pack["context_as_of"],
        }

        if material_verifier.get("status") not in {
            "SKIPPED_NOT_MATERIAL",
            "UNAVAILABLE_NOT_CONFIGURED",
        }:
            send({
                "type": "verification",
                "verification": material_verifier,
                "trade_authorization": False,
            })

        combined_failover = bool(shared_pack["llm_failover_used"] or decision_failover_used)
        send({
            "type": "signal",
            "decision": research_label,
            "research_label": research_label,
            "ticker": ticker,
            "trade_authorization": False,
            "requires_tradebrain_gate": True,
            "tradebrain_advisory": tradebrain_advisory,
            "llm_provider": active_provider,
            "llm_failover_used": combined_failover,
            "shared_research_pack_id": shared_pack["pack_id"],
            "material_verifier": material_verifier,
        })
        send({"type": "stats", **stats_summary})
        send({
            "type": "complete",
            "duration_seconds": round(duration, 1),
            "stats": stats_summary,
            "trade_authorization": False,
            "llm_provider": active_provider,
            "llm_failover_used": combined_failover,
            "shared_research_pack_id": shared_pack["pack_id"],
            "material_verifier": material_verifier,
        })

        invest_state = final_state.get("investment_debate_state") or {}
        risk_state = final_state.get("risk_debate_state") or {}
        result_data = {
            "ticker": ticker,
            "trade_date": trade_date,
            "requested_trade_mode": mode,
            "signal": research_label,
            "research_label": research_label,
            "trade_authorization": False,
            "order_execution_allowed": False,
            "requires_tradebrain_gate": True,
            "tradebrain_advisory": tradebrain_advisory,
            "llm_provider": active_provider,
            "llm_failover_used": combined_failover,
            "shared_research_reused": True,
            "shared_research_pack_id": shared_pack["pack_id"],
            "shared_research_version": shared_pack["version"],
            "shared_research_provider": shared_pack["provider"],
            "shared_research_llm_failover_used": shared_pack["llm_failover_used"],
            "shared_context_as_of": shared_pack["context_as_of"],
            "shared_context_status": shared_pack["context_status"],
            "material_verifier": material_verifier,
            "market_report": shared_pack["reports"].get("market_report"),
            "sentiment_report": shared_pack["reports"].get("sentiment_report"),
            "news_report": shared_pack["reports"].get("news_report"),
            "fundamentals_report": shared_pack["reports"].get("fundamentals_report"),
            "investment_plan": final_state.get("investment_plan"),
            "trader_investment_plan": final_state.get("trader_investment_plan"),
            "final_trade_decision": final_text,
            "bull_history": invest_state.get("bull_history"),
            "bear_history": invest_state.get("bear_history"),
            "risk_aggressive_history": risk_state.get("aggressive_history"),
            "risk_conservative_history": risk_state.get("conservative_history"),
            "risk_neutral_history": risk_state.get("neutral_history"),
            "stats": stats_summary,
            "duration_seconds": round(duration, 1),
        }

        save_analysis(task_id, result_data)
        save_final_advisory(task_id, tradebrain_advisory, research_label=research_label)
        tasks[task_id]["status"] = "completed"
        tasks[task_id]["stage"] = "completed"
        tasks[task_id]["result"] = result_data
    except Exception as exc:
        message = str(exc)
        if is_retryable_llm_capacity_error(exc):
            message = public_capacity_error(
                exc,
                fallback_available=get_capacity_fallback_config(base_config) is not None,
            )
        tasks[task_id]["status"] = "error"
        tasks[task_id]["stage"] = "error"
        tasks[task_id]["error"] = message
        send({"type": "error", "message": message})
    finally:
        loop.close()
