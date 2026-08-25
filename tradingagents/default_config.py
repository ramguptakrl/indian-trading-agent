import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    # LLM settings. Trade Brain defaults to Google Gemini; Anthropic is optional.
    # Gemini 3.6 Flash is the stable primary model for the agent loop, while
    # Gemini 3.1 Pro Preview is available for deeper reasoning when selected.
    "llm_provider": "google",
    "deep_think_llm": "gemini-3.1-pro-preview",
    "quick_think_llm": "gemini-3.6-flash",
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    "output_language": "English",
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration. Price + price-derived indicators route through Trade
    # Brain: Kite when configured, explicitly-labelled Yahoo fallback otherwise.
    # Fundamentals/news stay on providers that actually supply those data classes.
    "data_vendors": {
        "core_stock_apis": "tradebrain",
        "technical_indicators": "tradebrain",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
        "indian_market_data": "nse",
    },
    "tool_vendors": {},
    # === Indian Market Settings ===
    "market": "india",
    "default_exchange": "NSE",
    "ticker_suffix": ".NS",
    "market_timezone": "Asia/Kolkata",
    "market_open": "09:15",
    "market_close": "15:30",
    "currency": "INR",
    "trading_style": "short_term",
    "default_lookback_days": 15,
    "global_news_queries": [
        "Indian stock market Sensex Nifty",
        "RBI monetary policy interest rates India",
        "India GDP inflation economic outlook",
        "FII DII activity Indian markets",
        "India rupee forex exchange rate",
    ],
    # === Trade Brain active product boundary ===
    "trader_profile": "RESIDENT_INDIAN",
    "active_trade_modes": ["INTRADAY", "SWING"],
    "mtf_enabled": False,
    "funded_amount_modeled": False,
    "derivatives_enabled": False,
    "swing_funding": "OWN_CASH_ONLY",
    "advisory_only": True,
    "order_execution_enabled": False,
    "dry_run": True,
    "intraday_no_fresh_entry": "15:10",
    "intraday_hard_exit": "15:15",
    # Legacy keys retained for compatibility with existing UI/code paths.
    "day_no_fresh_entry": "15:10",
    "day_hard_exit": "15:15",
    "swing_position_long_only": True,
    "require_structured_tp_sl": True,
    "heuristic_probability_is_learned": False,
    # === Kite / broker credentials: DATA ONLY unless a future explicit product decision changes this ===
    # The configured credential may belong to an NRI account; that does NOT make the
    # modeled trader NRI and must not import NRI trading/cost/tax restrictions.
    "market_data_credential_role": "MARKET_DATA_ONLY",
    "market_data_primary_when_configured": "ZERODHA_KITE",
    "market_data_fallback": "YAHOO_RESEARCH_FALLBACK",
    "kite_api_key": None,
    "kite_api_secret": None,
    "kite_access_token": None,
    "kite_live_mode": "quote",
    "kite_order_api_enabled": False,
    # === Paper/accounting safety ===
    "paper_buying_power_mode": "CASH_NOTIONAL_CONSERVATIVE",
    "max_position_value": 100000,
    "max_loss_per_trade": 5000,
    "max_daily_loss": 20000,
    "max_open_positions": 5,
    "require_stop_loss": True,
    "allowed_exchanges": ["NSE", "BSE"],
    "allowed_products": ["MIS", "CNC"],
}
