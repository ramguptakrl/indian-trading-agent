"""Analysis endpoints — run multi-agent analysis with WebSocket streaming.

Trade Brain hardening: the upstream multi-agent result is a research candidate, never
an order signal. Final advisory state is persisted separately with deterministic
validation metadata and an execution-disabled boundary.
"""

import asyncio
import uuid
import time
import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, BackgroundTasks
from backend.models import AnalysisRequest, AnalysisResponse
from backend.ws import manager
from backend.db import save_analysis, get_analysis, get_analysis_history, update_analysis_pnl
from backend.tradebrain.advisory_pipeline import evaluate_final_advisory, parse_agent_candidate
from backend.tradebrain.advisory_store import get_final_advisory, save_final_advisory
from pydantic import BaseModel as PydanticBaseModel
from tradingagents.utils.ticker import normalize_ticker
from tradingagents.default_config import DEFAULT_CONFIG

router = APIRouter(prefix="/api/analysis", tags=["analysis"])
IST = ZoneInfo("Asia/Kolkata")

# In-memory task state
_tasks: dict[str, dict] = {}


def _analysis_advisory(ticker: str, trade_date: str, exchange: str, final_text: str) -> dict:
    """Build a safe boundary for the general analysis endpoint.

    Historical analysis requests contain a date but no decision timestamp, so we do not
    invent an intraday clock for them. Current-date analysis is parsed and passed toward
    the final pipeline, but still fails closed until explicit Crash Guard and broker
    permission states are supplied through the Phase-10 final-advisory API.
    """
    parsed = parse_agent_candidate(final_text)
    try:
        requested_date = date.fromisoformat(trade_date)
    except ValueError:
        requested_date = None
    today = datetime.now(IST).date()
    if requested_date != today:
        return {
            "tradebrain_version": "0.11.0",
            "ticker": ticker,
            "exchange": exchange,
            "analysis_trade_date": trade_date,
            "ai_candidate": parsed,
            "final_status": "HISTORICAL_RESEARCH_NOT_LIVE_GATE",
            "reason": "Analysis supplied a historical/date-only context; no intraday decision timestamp was invented.",
            "advisory_only": True,
            "trade_authorization": False,
            "order_execution_allowed": False,
            "requires_phase10_final_gate_for_live_use": True,
        }
    return evaluate_final_advisory(
        ticker=ticker,
        exchange=exchange,
        final_trade_decision=final_text,
        evaluated_at=datetime.now(IST),
        crash_guard=None,
        broker_allows_trade=None,
        require_verified_calendar=True,
    )


def _run_analysis_sync(task_id: str, ticker: str, trade_date: str, config: dict, selected_analysts: list[str] = None):
    """Run the trading agent analysis in a background thread."""
    import asyncio
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.graph.propagation import Propagator
    from backend.stats_callback import StatsCallback

    if selected_analysts is None:
        selected_analysts = ["market", "social", "news", "fundamentals"]

    loop = asyncio.new_event_loop()
    start_time = time.time()
    _tasks[task_id]["status"] = "running"
    stats = StatsCallback()

    try:
        ta = TradingAgentsGraph(
            selected_analysts=selected_analysts,
            debug=False,
            config=config,
            callbacks=[stats],
        )

        propagator = Propagator(max_recur_limit=config.get("max_recur_limit", 100))
        init_state = propagator.create_initial_state(ticker, trade_date)
        stream_args = propagator.get_graph_args()

        prev_reports = {}
        chunk_count = 0

        for chunk in ta.graph.stream(init_state, **stream_args):
            chunk_count += 1
            last_message = ""
            if chunk.get("messages"):
                msg = chunk["messages"][-1]
                msg_type = type(msg).__name__
                content_preview = ""
                if hasattr(msg, "content") and msg.content:
                    content_preview = str(msg.content)[:80] if isinstance(msg.content, str) else "tool result"
                tool_calls = ""
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_calls = f" (calling: {msg.tool_calls[0].get('name', '?')})"
                last_message = f"{msg_type}{tool_calls}: {content_preview}"
            print(f"[Analysis {task_id}] Chunk #{chunk_count} — {last_message}", flush=True)

            loop.run_until_complete(manager.send_event(task_id, {
                "type": "heartbeat",
                "chunk": chunk_count,
                "last_activity": last_message[:120],
            }))

            for field in ["market_report", "sentiment_report", "news_report",
                          "fundamentals_report", "investment_plan",
                          "trader_investment_plan", "final_trade_decision"]:
                val = chunk.get(field)
                if val and val != prev_reports.get(field):
                    prev_reports[field] = val
                    print(f"[Analysis {task_id}] Report completed: {field}", flush=True)
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "report",
                        "section": field,
                        "content": val,
                    }))

            invest_state = chunk.get("investment_debate_state")
            if invest_state:
                bull = invest_state.get("bull_history", "")
                bear = invest_state.get("bear_history", "")
                if bull and bull != prev_reports.get("bull_history"):
                    prev_reports["bull_history"] = bull
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "debate", "side": "bull", "content": bull,
                    }))
                if bear and bear != prev_reports.get("bear_history"):
                    prev_reports["bear_history"] = bear
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "debate", "side": "bear", "content": bear,
                    }))
                judge = invest_state.get("judge_decision", "")
                if judge and judge != prev_reports.get("judge_decision"):
                    prev_reports["judge_decision"] = judge
                    loop.run_until_complete(manager.send_event(task_id, {
                        "type": "report", "section": "investment_plan", "content": judge,
                    }))

            risk_state = chunk.get("risk_debate_state")
            if risk_state:
                for side in ["aggressive", "conservative", "neutral"]:
                    key = f"{side}_history"
                    val = risk_state.get(key, "")
                    if val and val != prev_reports.get(f"risk_{key}"):
                        prev_reports[f"risk_{key}"] = val
                        loop.run_until_complete(manager.send_event(task_id, {
                            "type": "risk_debate", "side": side, "content": val,
                        }))

        final_state = chunk
        final_text = final_state.get("final_trade_decision", "")
        research_label = ta.process_signal(final_text)
        exchange = str(config.get("default_exchange") or "NSE").upper()
        tradebrain_advisory = _analysis_advisory(ticker, trade_date, exchange, final_text)

        duration = time.time() - start_time
        stats_summary = stats.summary()

        # Keep the legacy event type for frontend compatibility, but the value is now a
        # non-authorizing research label and the explicit safety metadata travels with it.
        loop.run_until_complete(manager.send_event(task_id, {
            "type": "signal",
            "decision": research_label,
            "research_label": research_label,
            "ticker": ticker,
            "trade_authorization": False,
            "requires_tradebrain_gate": True,
            "tradebrain_advisory": tradebrain_advisory,
        }))
        loop.run_until_complete(manager.send_event(task_id, {
            "type": "stats", **stats_summary,
        }))
        loop.run_until_complete(manager.send_event(task_id, {
            "type": "complete",
            "duration_seconds": round(duration, 1),
            "stats": stats_summary,
            "trade_authorization": False,
        }))

        invest_state = final_state.get("investment_debate_state", {})
        risk_state = final_state.get("risk_debate_state", {})

        result_data = {
            "ticker": ticker,
            "trade_date": trade_date,
            "signal": research_label,
            "research_label": research_label,
            "trade_authorization": False,
            "order_execution_allowed": False,
            "requires_tradebrain_gate": True,
            "tradebrain_advisory": tradebrain_advisory,
            "market_report": final_state.get("market_report"),
            "sentiment_report": final_state.get("sentiment_report"),
            "news_report": final_state.get("news_report"),
            "fundamentals_report": final_state.get("fundamentals_report"),
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
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["result"] = result_data

    except Exception as e:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["error"] = str(e)
        loop.run_until_complete(manager.send_event(task_id, {
            "type": "error", "message": str(e),
        }))
    finally:
        loop.close()


@router.post("/run")
def run_analysis(req: AnalysisRequest):
    """Start a new analysis. Returns task_id for WebSocket streaming."""
    task_id = str(uuid.uuid4())[:8]
    ticker = normalize_ticker(req.ticker)

    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = req.max_debate_rounds
    config["max_risk_discuss_rounds"] = req.max_risk_discuss_rounds
    config["output_language"] = req.output_language

    _tasks[task_id] = {
        "status": "pending",
        "ticker": ticker,
        "trade_date": req.trade_date,
        "analysts": req.analysts,
    }

    thread = threading.Thread(
        target=_run_analysis_sync,
        args=(task_id, ticker, req.trade_date, config, req.analysts),
        daemon=True,
    )
    thread.start()

    return AnalysisResponse(
        task_id=task_id,
        status="started",
        ticker=ticker,
        trade_date=req.trade_date,
    )


@router.websocket("/ws/{task_id}")
async def analysis_websocket(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for streaming analysis progress."""
    await manager.connect(websocket, task_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)


@router.get("/{task_id}")
def get_analysis_result(task_id: str):
    """Get a completed analysis result with its persisted Trade Brain boundary."""
    if task_id in _tasks:
        task = _tasks[task_id]
        if task["status"] == "completed":
            return task.get("result", {})
        return {"task_id": task_id, "status": task["status"]}

    result = get_analysis(task_id)
    if result:
        persisted = get_final_advisory(task_id)
        result["research_label"] = result.get("signal") or "NO_TRADE"
        result["trade_authorization"] = False
        result["order_execution_allowed"] = False
        result["requires_tradebrain_gate"] = True
        result["tradebrain_advisory"] = persisted.get("advisory") if persisted else None
        return result
    return {"error": "Analysis not found"}


class PnLUpdate(PydanticBaseModel):
    entry_price: float
    exit_price: float | None = None
    reflect: bool = False


@router.put("/{task_id}/pnl")
def update_pnl(task_id: str, data: PnLUpdate):
    """Update manually observed P&L for a completed research analysis.

    This legacy feedback path does not authorize execution and is separate from the
    Phase-6 net-cost paper ledger and Phase-4 strict replay outcomes.
    """
    analysis = get_analysis(task_id)
    if not analysis:
        return {"error": "Analysis not found"}

    if data.exit_price is None:
        update_analysis_pnl(task_id, data.entry_price, None, None, None, "open")
        return {
            "status": "updated",
            "pnl_status": "open",
            "trade_authorization": False,
            "message": "Research outcome marked open. This is not an execution record.",
        }

    pnl_amount = data.exit_price - data.entry_price
    pnl_pct = round((pnl_amount / data.entry_price) * 100, 2)
    pnl_status = "win" if pnl_amount > 0 else ("loss" if pnl_amount < 0 else "breakeven")

    research_label = (analysis.get("signal") or "").upper()
    if research_label == "SHORT_CANDIDATE":
        pnl_amount = -pnl_amount
        pnl_pct = -pnl_pct
        pnl_status = "win" if pnl_amount > 0 else ("loss" if pnl_amount < 0 else "breakeven")

    update_analysis_pnl(task_id, data.entry_price, data.exit_price, round(pnl_amount, 2), pnl_pct, pnl_status)

    reflection_result = None
    if data.reflect:
        reflection_result = _reflect_on_analysis(analysis, pnl_amount)

    return {
        "status": "updated",
        "pnl_pct": pnl_pct,
        "pnl_amount": round(pnl_amount, 2),
        "pnl_status": pnl_status,
        "trade_authorization": False,
        "reflection": reflection_result,
    }


def _reflect_on_analysis(analysis: dict, pnl_amount: float) -> dict:
    """Run reflection on a past analysis and save to agent memories."""
    try:
        from tradingagents.graph.reflection import Reflector
        from tradingagents.agents.utils.memory import FinancialSituationMemory
        from tradingagents.llm_clients import create_llm_client

        state = {
            "market_report": analysis.get("market_report", ""),
            "sentiment_report": analysis.get("sentiment_report", ""),
            "news_report": analysis.get("news_report", ""),
            "fundamentals_report": analysis.get("fundamentals_report", ""),
            "investment_debate_state": {
                "bull_history": analysis.get("bull_history", ""),
                "bear_history": analysis.get("bear_history", ""),
                "judge_decision": analysis.get("investment_plan", ""),
            },
            "trader_investment_plan": analysis.get("trader_investment_plan", ""),
            "risk_debate_state": {
                "judge_decision": analysis.get("final_trade_decision", ""),
            },
        }

        if not state["market_report"] and not state["news_report"]:
            return {"error": "No reports available for reflection"}

        quick_client = create_llm_client(
            provider=DEFAULT_CONFIG["llm_provider"],
            model=DEFAULT_CONFIG["quick_think_llm"],
        )
        quick_llm = quick_client.get_llm()
        reflector = Reflector(quick_llm)

        bull_mem = FinancialSituationMemory("bull_memory", DEFAULT_CONFIG)
        bear_mem = FinancialSituationMemory("bear_memory", DEFAULT_CONFIG)
        trader_mem = FinancialSituationMemory("trader_memory", DEFAULT_CONFIG)
        judge_mem = FinancialSituationMemory("invest_judge_memory", DEFAULT_CONFIG)
        pm_mem = FinancialSituationMemory("portfolio_manager_memory", DEFAULT_CONFIG)

        reflector.reflect_bull_researcher(state, pnl_amount, bull_mem)
        reflector.reflect_bear_researcher(state, pnl_amount, bear_mem)
        reflector.reflect_trader(state, pnl_amount, trader_mem)
        reflector.reflect_invest_judge(state, pnl_amount, judge_mem)
        reflector.reflect_portfolio_manager(state, pnl_amount, pm_mem)

        return {
            "ok": True,
            "memories_updated": {
                "bull": bull_mem.count(),
                "bear": bear_mem.count(),
                "trader": trader_mem.count(),
                "judge": judge_mem.count(),
                "portfolio_manager": pm_mem.count(),
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/memory/stats")
def get_memory_stats():
    """Get count of stored memories per agent."""
    try:
        from tradingagents.agents.utils.memory import FinancialSituationMemory
        memories = {
            "bull_memory": FinancialSituationMemory("bull_memory", DEFAULT_CONFIG).count(),
            "bear_memory": FinancialSituationMemory("bear_memory", DEFAULT_CONFIG).count(),
            "trader_memory": FinancialSituationMemory("trader_memory", DEFAULT_CONFIG).count(),
            "invest_judge_memory": FinancialSituationMemory("invest_judge_memory", DEFAULT_CONFIG).count(),
            "portfolio_manager_memory": FinancialSituationMemory("portfolio_manager_memory", DEFAULT_CONFIG).count(),
        }
        return {
            "memories": memories,
            "total": sum(memories.values()),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/history/list")
def list_analysis_history(limit: int = 50, offset: int = 0):
    """List past analyses. `signal` is a non-authorizing research label in Trade Brain."""
    rows = get_analysis_history(limit, offset)
    for row in rows:
        row["research_label"] = row.get("signal") or "NO_TRADE"
        row["trade_authorization"] = False
    return rows
