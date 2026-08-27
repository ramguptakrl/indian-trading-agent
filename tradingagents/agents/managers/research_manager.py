from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.horizon_policy import horizon_instruction


def create_research_manager(llm, memory, requested_trade_mode: str | None = None):
    def research_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])
        history = state["investment_debate_state"].get("history", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        investment_debate_state = state["investment_debate_state"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        horizon_context = horizon_instruction(requested_trade_mode)
        prompt = f"""As the Research Manager for Trade Brain's **BSE Ltd-only resident-Indian equity research desk**, critically evaluate this debate round for the dedicated horizon below.

{horizon_context}

Your recommendation must stay inside that dedicated horizon. Never substitute SWING for a weak INTRADAY setup, never substitute INTRADAY/SHORT for a weak SWING setup, and never invent broker/MTF facts. If the evidence does not support a defensible setup for this horizon, prefer HOLD / WAIT or NO TRADE rather than forcing a trade.

Develop a detailed research plan for the Trader:

1. **Recommendation**: Buy / Sell / Hold / No Trade, with the strongest debate arguments supporting it
2. **Rationale**: Why these arguments matter for the DEDICATED HORIZON only
3. **Entry Strategy**: Specific entry price/zone or explicit conditions for entry; use N/A when no trade is justified
4. **Stop-Loss Level**: Specific price for a proposed new trade; otherwise N/A
5. **Profit Targets**: Target 1 and Target 2 for a proposed new trade; otherwise N/A
6. **Time Horizon**: Must match the dedicated horizon above
7. **Key Risks / Invalidation**: Top risks and what would invalidate the thesis
8. **Missing / Unverified Inputs**: Explicitly identify material gaps instead of inventing them

**Indian Market Context**: Consider only supplied/traceable NIFTY context, FII/DII flows, sector momentum and upcoming events when they are actually present in the evidence. Do not fabricate missing market-context facts.

Past reflections on mistakes are hypotheses, not authority:
\"{past_memory_str}\"

{instrument_context}

Debate History:
{history}"""
        response = llm.invoke(prompt)

        new_investment_debate_state = {
            "judge_decision": response.content,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": response.content,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": response.content,
        }

    return research_manager_node
