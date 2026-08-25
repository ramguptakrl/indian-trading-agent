# TradingAgents/graph/propagation.py

from typing import Dict, Any, List, Optional
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)


def _runtime_multi_timeframe_context(company_name: str, trade_date: str) -> str:
    """Build BSE audited context lazily so non-BSE legacy imports stay lightweight."""
    if str(company_name or "").strip().upper() not in {"BSE", "NSE:BSE", "BSE.NS", "BSE LTD", "BSE LIMITED"}:
        return ""
    try:
        from backend.tradebrain.live_decision_context import (
            build_bse_decision_context,
            decision_context_for_prompt,
        )

        context = build_bse_decision_context(str(trade_date))
        return decision_context_for_prompt(context)
    except Exception as exc:
        # Fail closed at the evidence boundary: an unavailable context is visible to the
        # models and may never be replaced by invented timeframe values.
        return (
            "Audited multi-timeframe context status: CONTEXT_BUILD_FAILED\n"
            f"Reason: {type(exc).__name__}: {str(exc)[:240]}\n"
            "Candidate evidence complete: False\n"
            "Do not invent 1D/4H/1H/15m values; use WAIT / NO TRADE when these are material."
        )


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        company_name: str,
        trade_date: str,
        *,
        multi_timeframe_context: str = "",
    ) -> Dict[str, Any]:
        """Create initial state with deterministic audited BSE timeframe evidence.

        Callers may supply a prebuilt context for deterministic tests. Otherwise every BSE
        graph run automatically builds the same look-ahead-safe D→4H→1H→15m snapshot.
        """
        audited_context = str(multi_timeframe_context or "").strip()
        if not audited_context:
            audited_context = _runtime_multi_timeframe_context(company_name, trade_date)

        return {
            "messages": [("human", company_name)],
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "multi_timeframe_context": audited_context,
            "investment_debate_state": InvestDebateState(
                {
                    "bull_history": "",
                    "bear_history": "",
                    "history": "",
                    "current_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "aggressive_history": "",
                    "conservative_history": "",
                    "neutral_history": "",
                    "history": "",
                    "latest_speaker": "",
                    "current_aggressive_response": "",
                    "current_conservative_response": "",
                    "current_neutral_response": "",
                    "judge_decision": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
        }

    def get_graph_args(self, callbacks: Optional[List] = None) -> Dict[str, Any]:
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
