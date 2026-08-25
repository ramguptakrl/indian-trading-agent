from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction, get_news


def create_social_media_analyst(llm):
    """Optional experimental BSE public-sentiment analyst.

    This agent is deliberately not part of the default BSE team. It remains available while
    Trade Brain measures whether its evidence adds value beyond the dedicated news/context
    analyst. No sentiment score is treated as calibrated probability.
    """

    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        tools = [get_news]

        system_message = (
            """You are an **optional experimental sentiment analyst for BSE Ltd only**.
Search for recent public discussion/company-specific sentiment evidence when the tool can
provide it. Do not claim to have sampled social platforms the tool did not actually return.
Do not transform anecdotal sentiment into a probability or a trade signal.

Your report must state:
- what sources/evidence were actually available;
- whether sentiment is materially distinct from the News/Context evidence;
- possible BSE Ltd implication, if any;
- uncertainty, selection bias and missing data;
- INTRADAY/SWING relevance.

If there is no reliable incremental sentiment evidence, explicitly conclude that this agent
adds no material evidence for the current BSE analysis. Do not issue the final verdict and do
not recommend another security."""
            + " Append a Markdown table: Evidence | Source type | BSE relevance | Reliability limitation."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an experimental research assistant inside Trade Brain. Use only evidence "
                    "returned by the tool and do not invent social coverage. Tools: {tool_names}.\n"
                    "{system_message}\nCurrent India analysis date: {current_date}. {instrument_context}",
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

        return {"messages": [result], "sentiment_report": report}

    return social_media_analyst_node
