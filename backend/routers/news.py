"""BSE Ltd news/context API.

The aggregate feed remains available for broader Indian-market context, but the ticker-specific
route is BSE Ltd-only on the Trade Brain branch.
"""

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from backend.news_sources import (
    fetch_all_news,
    fetch_ticker_news,
    get_news_sources_config,
    save_news_sources_config,
)
from backend.tradebrain.bse_scope import BSE_SCOPE, require_bse_trade_target

router = APIRouter(prefix="/api/news", tags=["bse-context"])


class NewsSourcesUpdate(BaseModel):
    rss_feeds: dict | None = None
    yf_queries: list[str] | None = None


@router.get("/")
def get_news(max_per_source: int = Query(10)):
    """Get broader market/context news. Returned items are context, not trade targets."""
    return {
        "articles": fetch_all_news(max_per_source),
        "role": "BSE_CONTEXT_ONLY",
        "trade_target": BSE_SCOPE.kite_symbol,
        "trade_authorization": False,
    }


@router.get("/ticker/{ticker}")
def get_news_for_ticker(ticker: str, max_items: int = Query(15)):
    """Get company-specific news for BSE Ltd only."""
    try:
        require_bse_trade_target(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ticker": BSE_SCOPE.ticker,
        "exchange": BSE_SCOPE.exchange,
        "kite_symbol": BSE_SCOPE.kite_symbol,
        "articles": fetch_ticker_news(BSE_SCOPE.ticker, max_items),
        "trade_authorization": False,
    }


@router.get("/sources")
def get_sources():
    """Legacy source configuration endpoint retained during staged BSE conversion."""
    return get_news_sources_config()


@router.put("/sources")
def update_sources(data: NewsSourcesUpdate):
    """Legacy source configuration endpoint retained during staged BSE conversion."""
    save_news_sources_config(rss_feeds=data.rss_feeds, yf_queries=data.yf_queries)
    return {"status": "saved", "config": get_news_sources_config()}
