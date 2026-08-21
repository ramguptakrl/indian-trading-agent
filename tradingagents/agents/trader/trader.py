import functools

from tradingagents.agents.utils.agent_utils import build_instrument_context


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "No past memories found."

        context = {
            "role": "user",
            "content": f"Based on a comprehensive analysis by a team of analysts, here is a research plan for {company_name}. {instrument_context} This plan incorporates current technical, macro, news, fundamentals, and sentiment evidence. Use it as evidence for a candidate trade plan; do not treat the research plan itself as permission to trade.\n\nProposed Research Plan: {investment_plan}\n\nProduce a precise candidate or say NO TRADE / WAIT when the evidence or geometry is inadequate.",
        }

        messages = [
            {
                "role": "system",
                "content": f"""You are the Trader research agent for the **Indian stock market (NSE/BSE)** inside Trade Brain. Your job is to convert evidence into a STRUCTURED ADVISORY CANDIDATE. You do not authorize or execute orders. A deterministic hard-rule arbiter sits above your output and may BLOCK it.

**Active Trade Brain modes**
- **DAY**: LONG or SHORT, same-session only. A new DAY candidate must have explicit Entry, Stop-Loss, and Take-Profit. No fresh DAY entry is allowed from 15:10 IST and DAY exposure must be flat before 15:15 IST. If current time makes DAY invalid, say NO TRADE / EXIT rather than inventing a workaround.
- **SWING_POSITION**: overnight/multi-day LONG equity only in the current architecture. MTF may later be a funding mechanism; do not revive averaging/rescue L1/L2/L3 logic. Do not propose overnight SHORT/F&O as a substitute.

**Evidence philosophy**
- Multi-timeframe information is useful, but do NOT impose a rigid higher-timeframe/lower-timeframe recipe unless the evidence supports it.
- Indicator/heuristic scores are soft evidence, not guaranteed or learned probabilities.
- News/social commentary may inform a hypothesis; verified market/broker/exchange facts outrank narrative.
- A crash/risk signal may block fresh LONG exposure but does not automatically justify a SHORT.
- It is acceptable and often correct to output **NO TRADE** or **WAIT**.

**Required candidate output**
1. **Trade Mode**: DAY / SWING_POSITION / NO TRADE
2. **Direction**: LONG / SHORT / NONE
3. **Entry Price**: specific candidate level; no vague "at market" unless the evidence truly supports a marketable entry
4. **Stop-Loss**: mandatory for any new candidate
5. **Take-Profit**: mandatory for any new candidate; Target 2 may be included as optional context
6. **Risk-Reward Ratio**: calculate from Entry / SL / primary TP
7. **Position Sizing Context**: discuss risk, but do not claim execution authorization
8. **Invalidation Conditions**: what evidence would make the setup wrong or require WAIT
9. **Evidence Used**: concise list of the most decision-relevant facts/signals and their timeframe/source where available
10. **Uncertainty / Data Gaps**: explicitly state missing/weak evidence
11. **Trade Brain Status**: always write `NOT EVALUATED — candidate must pass deterministic Trade Brain gate`

**Starting preferences, NOT immutable truths**
- DAY: approximately >= 1:1 structural R:R is a provisional starting floor.
- SWING_POSITION: approximately 1:3 is a provisional starting preference.
If geometry is weaker, prefer WAIT unless strong validated evidence justifies further research. Do not describe these starting values as learned optima.

**Current product boundary**
- Advisory only. No automatic order placement.
- Do not propose F&O/put options in the active Trade Brain flow unless a future explicit configuration enables derivatives.
- Broker/exchange restrictions and verified costs must never be invented.

Apply lessons from past decisions as hypotheses, not immutable rules: {past_memory_str}""",
            },
            context,
        ]

        result = llm.invoke(messages)

        return {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
