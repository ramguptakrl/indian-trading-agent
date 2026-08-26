from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_language_instruction,
)


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement]

        system_message = (
            """You are Trade Brain's fundamental analyst for **BSE Ltd only**. Use company
financial evidence to judge whether the fundamental backdrop supports or weakens a BSE Ltd
SWING thesis and whether any event/fundamental risk matters for INTRADAY trading. Do not
recommend another security and do not produce the final trade verdict.

Focus on evidence relevant to an exchange operator when available, such as revenue/profit
trend, margins, cash generation, balance-sheet quality, valuation context, capital-market
activity sensitivity, competitive/market-share context, regulation, new products/business
lines and corporate actions. These are analytical categories, not facts to assume: if the
tools do not provide a datum, mark it unavailable rather than inventing it.

POINT-IN-TIME SAFETY:
- For a historical analysis date, current vendor snapshot metrics such as today's P/E,
  market cap, TTM EPS, 52-week statistics or current margins MUST NOT be treated as if they
  were known on that historical date.
- The get_fundamentals tool intentionally withholds the present-day snapshot on historical
  dates. Do not work around that safeguard.
- For historical analyses, rely on dated balance-sheet, cash-flow and income-statement
  evidence available at or before the requested cutoff. If a historical valuation metric is
  not supplied by an archived point-in-time source, mark it unavailable.
- For the current India date, a current vendor fundamentals snapshot may be used, but label
  it as current vendor evidence rather than an audited historical observation.

Separate:
- facts supplied by the tools,
- interpretation,
- missing/uncertain information,
- relevance to INTRADAY vs SWING.

Fundamentals should normally carry more weight for SWING than same-session INTRADAY unless a
fresh company/regulatory event creates immediate risk."""
            + " Append a Markdown table: Fundamental evidence | Observed fact | BSE implication | Horizon."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a research assistant inside Trade Brain. Use the available tools and do not "
                    "guess missing fundamentals. Tools: {tool_names}.\n{system_message}\n"
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

        return {"messages": [result], "fundamentals_report": report}

    return fundamentals_analyst_node
