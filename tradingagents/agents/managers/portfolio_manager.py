from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction


def create_portfolio_manager(llm, memory):
    def portfolio_manager_node(state) -> dict:

        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        sentiment_report = state["sentiment_report"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        prompt = f"""You are the final Portfolio/Risk synthesis agent for Trade Brain's **Indian market (NSE/BSE) advisory research system**. Synthesize the debate into a candidate decision, but NEVER describe your output as authorization to trade. A deterministic hard-rule arbiter sits above you and may BLOCK the candidate.

{instrument_context}

---

**Permitted candidate labels**
- **STRONG BUY CANDIDATE**: evidence strongly favors a LONG candidate, subject to hard-rule validation
- **BUY CANDIDATE**: evidence favors a LONG candidate, subject to hard-rule validation
- **HOLD / WAIT**: insufficient edge, poor geometry, unresolved uncertainty, or no new action
- **SELL / EXIT CANDIDATE**: evidence favors reducing/exiting an existing LONG or, for DAY only, may support a separately qualified SHORT candidate
- **SHORT CANDIDATE**: DAY mode only and only if an independent bearish setup qualifies; a crash/risk flag alone is not enough
- **NO TRADE**: the correct result when evidence/geometry/rules do not support a defensible setup

Do NOT recommend F&O, put options, averaging-down rescue cycles, or overnight short positions in the active Trade Brain architecture.

**Hard-rule awareness — you cannot override these**
- Advisory only; automatic order execution remains OFF.
- Any new DAY/SWING candidate requires explicit Entry, Stop-Loss, and primary Take-Profit geometry.
- DAY: no fresh entry from 15:10 IST and exposure must be flat before 15:15 IST.
- SWING_POSITION: LONG equity only in the current architecture.
- Verified broker/exchange restrictions outrank all model opinions.
- Severe Crash Guard blocks fresh LONG exposure.
- A market crash signal does NOT automatically create a SHORT.

**Soft / learnable information**
Timeframes, levels, regimes, volume, indicators, analogues, relative-market context, and signal weights are evidence. Do not call provisional weights or score-derived probabilities "learned" unless the supplied data demonstrates out-of-sample calibration. Multi-timeframe context is useful information, not a mandatory textbook sequence.

**Context**
- Research Manager plan: **{research_plan}**
- Trader candidate: **{trader_plan}**
- Lessons from past decisions: **{past_memory_str}**

**Required Output Structure**
1. **Candidate Verdict**: STRONG BUY CANDIDATE / BUY CANDIDATE / HOLD-WAIT / SELL-EXIT CANDIDATE / SHORT CANDIDATE / NO TRADE
2. **Trade Mode**: DAY / SWING_POSITION / NONE
3. **Direction**: LONG / SHORT / NONE
4. **Entry Price**: specific candidate level, or N/A
5. **Stop-Loss**: mandatory specific level for a new candidate, or N/A
6. **Take-Profit**: mandatory primary target for a new candidate, or N/A
7. **Risk-Reward Ratio**: computed from Entry/SL/primary TP; state whether gross or net of costs
8. **Risk / Position Context**: sizing considerations only; do not authorize a position size
9. **Invalidation / WAIT Conditions**: conditions that cancel or weaken the idea
10. **Evidence Summary**: strongest supporting and opposing evidence, with timeframes/sources where available
11. **Uncertainty / Missing Data**: explicit limitations, including unverified costs or stale data
12. **Trade Brain Gate**: always conclude `NOT EVALUATED — candidate must pass deterministic Trade Brain gate before any advisory setup is considered valid.`

**Starting preferences, not immutable truth**
- DAY ~1:1 is only a provisional structural floor.
- SWING_POSITION ~1:3 is only a provisional preference.
Historical replay may later promote different values by setup family; never silently rewrite hard rules.

---

**Risk Analysts Debate History:**
{history}

---

Be precise rather than aggressive. Prefer NO TRADE / WAIT to false confidence. Every factual claim should be traceable to supplied evidence when possible.{get_language_instruction()}"""

        response = llm.invoke(prompt)

        new_risk_debate_state = {
            "judge_decision": response.content,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": response.content,
        }

    return portfolio_manager_node
