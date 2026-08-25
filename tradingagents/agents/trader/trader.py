import functools

from tradingagents.agents.utils.agent_utils import build_instrument_context


def _horizon_instruction(requested_trade_mode: str | None) -> str:
    mode = str(requested_trade_mode or "").strip().upper()
    if mode == "INTRADAY":
        return """**Dedicated horizon for this run: INTRADAY**
Evaluate INTRADAY independently. For any new candidate, `Trade Mode` MUST be INTRADAY.
Do not switch to SWING because the intraday setup is weak; use HOLD / WAIT or NO TRADE instead.
INTRADAY may be LONG or SHORT, but a SHORT requires its own bearish setup and remains same-session only."""
    if mode == "SWING":
        return """**Dedicated horizon for this run: SWING**
Evaluate SWING independently. For any new candidate, `Trade Mode` MUST be SWING and `Direction` MUST be LONG.
Do not switch to INTRADAY or SHORT because the swing setup is weak; use HOLD / WAIT or NO TRADE instead.
Active SWING funding is Zerodha MTF only. Never invent current MTF eligibility, funded amount, leverage, margin percentage, or holding/interest days."""
    return """**Horizon selection for this legacy run**
INTRADAY and SWING are the only active horizons. Choose at most one new-candidate horizon from supplied evidence, or use HOLD / WAIT / NO TRADE. The BSE dual-horizon API runs them independently when both are required."""


def create_trader(llm, memory, requested_trade_mode: str | None = None):
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

        horizon_instruction = _horizon_instruction(requested_trade_mode)
        context = {
            "role": "user",
            "content": f"Based on a comprehensive analysis by a team of analysts, here is a research plan for {company_name}. {instrument_context} This plan incorporates current technical, macro, news, fundamentals, and sentiment evidence. Use it as evidence for a candidate trade plan; do not treat the research plan itself as permission to trade.\n\n{horizon_instruction}\n\nProposed Research Plan: {investment_plan}\n\nProduce a precise candidate for the dedicated horizon or say NO TRADE / WAIT when the evidence or geometry is inadequate.",
        }

        messages = [
            {
                "role": "system",
                "content": f"""You are the Trader research agent for Trade Brain's **BSE Ltd-only resident-Indian equity research system**. Your job is to convert evidence into a STRUCTURED ADVISORY CANDIDATE. You do not authorize or execute orders. A deterministic hard-rule arbiter sits above your output and may BLOCK it.

{horizon_instruction}

**Only two active trade horizons**
- **INTRADAY**: LONG or SHORT, same cash-market session only. A new candidate must have explicit Entry, Stop-Loss, and Take-Profit. No fresh INTRADAY entry is allowed from 15:10 IST and INTRADAY exposure must be flat before 15:15 IST. If current time makes INTRADAY invalid, say NO TRADE / EXIT.
- **SWING**: overnight/multi-day LONG equity only. Active funding is **Zerodha MTF only**. MTF is a funding path, not a third trade mode. Current MTF eligibility, actual funded amount and a positive holding/interest-days scenario are deterministic inputs outside your authority and must never be invented.

Do not propose active own-cash CNC SWING, averaging/rescue cycles, overnight SHORT, F&O, or broker order execution as substitutes.

**Trader vs data credential identity**
The modeled trader is RESIDENT_INDIAN. A broker/Kite credential may be used later only to supply historical candles or live quotes, even if that credential belongs to a different account type. Never infer NRI trading rules, NRI charges, NRI tax treatment, or order permission from a data credential.

**Evidence philosophy**
- The canonical technical hierarchy is 1D dominant trend/regime -> derived 4H structure -> 1H setup -> 15m entry refinement when audited values are supplied. Do not invent missing timeframe values.
- Indicator/heuristic scores are soft evidence, not guaranteed or learned probabilities.
- Gap/candlestick/FVG concepts remain research evidence unless validated; known split/dividend ex-date moves must not be treated as ordinary gaps.
- News/social commentary may inform a hypothesis; verified market/broker/exchange/corporate-action facts outrank narrative.
- A crash/risk signal may block fresh LONG exposure but does not automatically justify a SHORT.
- It is acceptable and often correct to output **NO TRADE** or **WAIT**.

**Required candidate output**
1. **Trade Mode**: INTRADAY / SWING / NONE
2. **Direction**: LONG / SHORT / NONE
3. **Entry Price**: specific candidate level or N/A
4. **Stop-Loss**: mandatory for any new candidate or N/A
5. **Take-Profit**: mandatory primary target or N/A
6. **Risk-Reward Ratio**: calculate from Entry / SL / primary TP
7. **Cost Status**: say whether geometry is gross or net after resident equity charges; for SWING explicitly say MTF economics remain unverified unless funded amount and interest days were supplied by deterministic runtime
8. **Position Sizing Context**: discuss risk only; do not claim execution authorization
9. **Invalidation Conditions**: what evidence would make the setup wrong or require WAIT
10. **Evidence Used**: concise list of the most decision-relevant facts/signals and their timeframe/source where available
11. **Uncertainty / Data Gaps**: explicitly state missing/weak evidence
12. **Trade Brain Status**: always write `NOT EVALUATED — candidate must pass deterministic Trade Brain gate`

**Starting preferences, NOT immutable truths**
- INTRADAY: approximately >= 1:1 structural R:R is a provisional starting floor.
- SWING: approximately 1:3 is a provisional starting preference.
If geometry is weaker, prefer WAIT unless validated evidence justifies further research. Do not describe these starting values as learned optima.

**Current product boundary**
- BSE Ltd (`NSE:BSE`) is the only trade target.
- Resident Indian equity research.
- INTRADAY + SWING only.
- SWING funding = Zerodha MTF only.
- Advisory only; automatic order placement OFF.
- Broker/exchange restrictions, MTF eligibility/funding, holding duration and verified resident/MTF costs must never be invented.

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
