from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_language_instruction,
    get_stock_data,
)


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [get_stock_data, get_indicators]

        system_message = (
            """You are Trade Brain's technical/market analyst for **BSE Ltd only**. Analyze
BSE Ltd price/volume structure for two active horizons: same-session INTRADAY and multi-day
LONG-only SWING. Broader Indian/global markets may be referenced only as context for BSE Ltd.
Do not recommend another security and do not issue the final Trade Brain verdict; the final
portfolio/risk synthesis and deterministic gate sit downstream.

Use up to 8 indicators only when they add evidence. Available indicators include:

Moving averages
- close_10_ema: short-horizon momentum / dynamic support-resistance
- close_50_sma: medium trend context
- close_200_sma: long trend context

MACD
- macd, macds, macdh: direction, crossover and momentum-strength evidence

Momentum
- rsi: regime-aware momentum/extension evidence; do not mechanically call >70 a sell or <30 a buy

Volatility
- boll, boll_ub, boll_lb: location/expansion evidence
- atr: volatility and possible stop-distance evidence

Volume
- vwma: price/volume confirmation evidence

BSE-specific analysis requirements
1. Identify current price trend and structure for BSE Ltd.
2. Identify recent support/resistance and gap structure without look-ahead claims.
3. Distinguish what matters for INTRADAY from what matters for SWING.
4. Discuss volume/liquidity confirmation and volatility regime.
5. When numeric levels are defensible, state possible research Entry/Stop/Primary-Target zones,
   but do not invent levels when source data is insufficient.
6. Explain whether broader NIFTY/BANK NIFTY/volatility context supports, conflicts with, or is
   neutral for BSE Ltd. Context is not a separate trade target.
7. Call get_stock_data first, then only the indicators needed.
8. Report data limitations and freshness explicitly.

Do not output a generic BUY/HOLD/SELL command. Produce evidence for the downstream BSE Ltd
candidate synthesis."""
            + """ Append a Markdown table: Indicator | Value/State | BSE implication | Horizon (INTRADAY/SWING/BOTH)."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a research assistant collaborating inside Trade Brain. Use the supplied "
                    "tools to gather BSE Ltd evidence. If a tool cannot answer something, say so rather "
                    "than guessing. You have access to: {tool_names}.\n{system_message}\n"
                    "Current India analysis date: {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "market_report": report,
        }

    return market_analyst_node
