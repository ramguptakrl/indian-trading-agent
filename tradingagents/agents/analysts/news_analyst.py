from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from backend.tradebrain.news_evidence import news_evidence_for_prompt
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
)


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        official_first_context = news_evidence_for_prompt(current_date)

        # Yahoo/Alpha Vantage tools are supplementary discovery. The deterministic context
        # above already supplies official NSE/BSE/SEBI evidence and point-in-time archived
        # Indian financial media where available.
        tools = [get_news, get_global_news]

        system_message = (
            """You are Trade Brain's **BSE Ltd news and market-context analyst**. Your job is
not to summarize the whole world. Find and rank information that could plausibly affect BSE
Ltd's price, volatility or risk for INTRADAY or SWING decisions.

SOURCE AUTHORITY — obey this order:
1. Official NSE/BSE company disclosures and exchange-source facts.
2. Official SEBI circulars/orders/press releases relevant to exchanges, clearing or market structure.
3. Major Indian financial media such as Moneycontrol, Economic Times, LiveMint, Business Standard,
   NDTV Profit and similarly reputable reporting for context/interpretation.
4. Yahoo Finance / Alpha Vantage as supplementary discovery or aggregation.

An official disclosure outranks a media interpretation. Never call a media-only material claim HIGH
confidence merely because several aggregators repeat it; seek official confirmation first. If official
and media accounts conflict, state the conflict and keep confidence constrained.

Prioritize, when supported by current sources:
- BSE Ltd company announcements/results/corporate actions;
- SEBI/exchange/clearing/market-structure or derivatives regulation relevant to exchange economics;
- Indian cash/derivatives/primary-market activity and capital-market participation;
- competitive exchange developments and material market-share context;
- broad NIFTY/BANK NIFTY/India-risk sentiment only when it changes BSE Ltd risk context;
- global risk events only when there is a credible transmission path to Indian capital markets.

For each important item distinguish source fact from your interpretation, state the date, identify the
source tier, and explain the BSE transmission mechanism. Ignore generic headlines with no plausible
BSE link. Do not recommend another security and do not issue the final Trade Brain verdict."""
            + " Append a Markdown table: Date | Evidence/event | Source + tier | BSE impact path | Horizon | Bias/uncertainty."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a research assistant inside Trade Brain. Use the deterministic official-first "
                    "evidence below before supplementary discovery tools. Explicitly say when current "
                    "evidence is unavailable. Tools: {tool_names}.\n{system_message}\n"
                    "Current India analysis date: {current_date}. {instrument_context}\n\n"
                    "{official_first_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)
        prompt = prompt.partial(official_first_context=official_first_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {"messages": [result], "news_report": report}

    return news_analyst_node
