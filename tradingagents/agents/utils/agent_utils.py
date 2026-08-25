from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Return the fixed BSE Ltd research scope shared by all LLM agents.

    The Trade Brain branch is single-instrument. The graph still carries the yfinance-style
    alias ``BSE.NS`` internally for compatible data tools, while Kite and the product UI use
    the canonical market-data identity ``NSE:BSE``.
    """
    normalized = str(ticker or "").strip().upper()
    return (
        "TRADE BRAIN PRODUCT SCOPE: The only tradable company in this application is "
        "BSE Ltd (Bombay Stock Exchange Ltd), NSE-listed symbol `BSE`, canonical Kite "
        "identity `NSE:BSE`, yfinance-compatible alias `BSE.NS`, ISIN `INE118H01025`. "
        f"The graph supplied instrument alias is `{normalized}`. "
        "Use that supplied alias for company-specific tool calls when the tool expects a "
        "Yahoo-style ticker. Never turn NIFTY, BANK NIFTY, SENSEX, India VIX, sectors, "
        "FII/DII, global indices or another stock into a trade recommendation; those are "
        "context inputs only for judging BSE Ltd. The only active trade modes are "
        "INTRADAY and SWING."
    )


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for provider compatibility."""
        messages = state["messages"]

        removal_operations = [RemoveMessage(id=m.id) for m in messages]
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages
