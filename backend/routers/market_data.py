"""Market data endpoints — stock quotes, charts, indicators, fundamentals, news."""

from functools import lru_cache

from fastapi import APIRouter, Query
import yfinance as yf
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from tradingagents.utils.ticker import normalize_ticker

from backend.tradebrain.kite_data import KiteDataOnlyClient
from backend.tradebrain.kite_stream import latest_kite_quote
from backend.tradebrain.market_data_store import query_bars
from backend.tradebrain.market_source_policy import kite_credentials_ready, sync_preferred_history

router = APIRouter(prefix="/api/market-data", tags=["market-data"])
IST = ZoneInfo("Asia/Kolkata")


def _identity(ticker: str) -> tuple[str, str, str]:
    symbol = normalize_ticker(ticker)
    upper = symbol.upper()
    if upper.endswith(".NS"):
        return "NSE", upper[:-3], symbol
    if upper.endswith(".BO"):
        return "BSE", upper[:-3], symbol
    return "NSE", upper, symbol


def _kite_quote_payload(exchange: str, ticker: str, quote: dict, *, source: str) -> dict:
    ohlc = quote.get("ohlc") or {}
    price = float(quote.get("last_price") or 0)
    prev_close = float(ohlc.get("close") or quote.get("close") or 0)
    change = price - prev_close if prev_close else 0.0
    return {
        "ticker": f"{exchange}:{ticker}",
        "name": ticker,
        "price": round(price, 2),
        "change": round(change, 2),
        "change_percent": round(change / prev_close * 100, 2) if prev_close else 0.0,
        "volume": int(quote.get("volume") or 0),
        "high": round(float(ohlc.get("high") or quote.get("high") or 0), 2),
        "low": round(float(ohlc.get("low") or quote.get("low") or 0), 2),
        "open": round(float(ohlc.get("open") or quote.get("open") or 0), 2),
        "prev_close": round(prev_close, 2),
        "market_cap": None,
        "pe_ratio": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "price_source": source,
        "credential_role": "MARKET_DATA_ONLY",
        "order_api_enabled": False,
    }


def _yahoo_quote(exchange: str, raw_ticker: str, symbol: str, *, fallback_reason: str | None = None) -> dict:
    t = yf.Ticker(symbol)
    info = t.info
    hist = t.history(period="2d")
    if hist.empty:
        return {"error": f"No data found for {symbol}", "price_source": "YAHOO_FINANCE_VIA_YFINANCE"}
    current = hist.iloc[-1]
    prev_close = info.get("previousClose") or (hist.iloc[-2]["Close"] if len(hist) > 1 else current["Close"])
    price = current["Close"]
    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0
    return {
        "ticker": symbol,
        "name": info.get("shortName", symbol),
        "price": round(price, 2),
        "change": round(change, 2),
        "change_percent": round(change_pct, 2),
        "volume": int(current.get("Volume", 0)),
        "high": round(current["High"], 2),
        "low": round(current["Low"], 2),
        "open": round(current["Open"], 2),
        "prev_close": round(prev_close, 2),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "price_source": "YAHOO_FINANCE_VIA_YFINANCE",
        "fallback_used": True,
        "fallback_reason": fallback_reason or "KITE_CREDENTIALS_NOT_CONFIGURED",
        "order_api_enabled": False,
    }


@lru_cache(maxsize=256)
def _yahoo_nse_search(query: str) -> list:
    """Look up NSE-listed equities by name or ticker via Yahoo's search."""
    search = yf.Search(query, max_results=10)
    results, seen = [], set()
    for quote in (search.quotes or []):
        if quote.get("quoteType") != "EQUITY":
            continue
        symbol = quote.get("symbol", "")
        if quote.get("exchange") != "NSI" and not symbol.endswith(".NS"):
            continue
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        name = quote.get("longname") or quote.get("shortname") or symbol
        ticker = symbol[:-3] if symbol.endswith(".NS") else symbol
        results.append({"ticker": ticker, "name": name, "symbol": symbol, "score": 100})
    return results


@router.get("/search")
def search_stocks(q: str = Query("", description="Search query — ticker or company name")):
    """Typeahead search. Price truth is handled separately by Trade Brain."""
    query = q.strip()
    if not query:
        return []
    try:
        results = _yahoo_nse_search(query)
        if results:
            return results
    except Exception:
        pass
    from backend.stock_list import search_stocks as _search
    return _search(query)


@router.get("/quote/{ticker}")
def get_quote(ticker: str):
    """Get a live quote: persisted Kite WebSocket -> Kite REST -> Yahoo fallback."""
    exchange, raw_ticker, symbol = _identity(ticker)
    if kite_credentials_ready():
        try:
            live = latest_kite_quote(exchange, raw_ticker)
            if live and live.get("received_at"):
                received = datetime.fromisoformat(live["received_at"])
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - received.astimezone(timezone.utc)).total_seconds() <= 15:
                    payload = _kite_quote_payload(exchange, raw_ticker, live, source="ZERODHA_KITE_WEBSOCKET_MARKET_DATA_ONLY")
                    payload["fallback_used"] = False
                    return payload
            key = f"{exchange}:{raw_ticker}"
            data = KiteDataOnlyClient().quote([key], kind="full")
            quote = data.get(key)
            if not isinstance(quote, dict):
                raise ValueError(f"Kite full quote missing {key}")
            payload = _kite_quote_payload(exchange, raw_ticker, quote, source="ZERODHA_KITE_CONNECT_MARKET_DATA_ONLY")
            payload["fallback_used"] = False
            return payload
        except Exception as exc:
            return _yahoo_quote(exchange, raw_ticker, symbol, fallback_reason=f"KITE_FAILED: {type(exc).__name__}: {exc}")
    return _yahoo_quote(exchange, raw_ticker, symbol)


@router.get("/chart/{ticker}")
def get_chart_data(
    ticker: str,
    period: str = Query("3mo", description="1d, 5d, 1mo, 3mo, 6mo, 1y, 2y"),
    interval: str = Query("1d", description="1m, 5m, 15m, 1h, 1d, 1wk"),
):
    """Get OHLCV chart data through Trade Brain when the interval is supported."""
    exchange, raw_ticker, symbol = _identity(ticker)
    period_days = {"1d": 1, "5d": 5, "1mo": 31, "3mo": 93, "6mo": 186, "1y": 366, "2y": 732}
    days = period_days.get(period)
    if days is None:
        return {"error": f"Unsupported period {period}", "data": []}

    if interval != "1wk":
        try:
            end = datetime.now(IST) + timedelta(days=1)
            start = datetime.now(IST) - timedelta(days=days)
            result = sync_preferred_history(
                exchange=exchange,
                symbol=raw_ticker,
                interval=interval,
                from_time=start,
                to_time=end,
                allow_yahoo_fallback=True,
            )
            series_id = result.get("series_id")
            stored_interval = result.get("interval") or interval
            if series_id:
                rows = query_bars(series_id, stored_interval, limit=500000)
                data = []
                for row in rows:
                    opened = datetime.fromisoformat(row["ts_open"])
                    if opened.tzinfo is None:
                        opened = opened.replace(tzinfo=timezone.utc)
                    local = opened.astimezone(IST)
                    if local < start or local > end:
                        continue
                    ts = local.date().isoformat() if interval == "1d" else local.isoformat()
                    data.append({
                        "time": ts,
                        "open": round(float(row["open"]), 2),
                        "high": round(float(row["high"]), 2),
                        "low": round(float(row["low"]), 2),
                        "close": round(float(row["close"]), 2),
                        "volume": int(float(row.get("volume") or 0)),
                    })
                if data:
                    return {
                        "ticker": f"{exchange}:{raw_ticker}",
                        "period": period,
                        "interval": interval,
                        "data": data,
                        "price_source": result.get("source_key"),
                        "fallback_used": bool(result.get("fallback_used")),
                        "fallback_reason": result.get("fallback_reason"),
                    }
        except Exception:
            pass

    # Weekly is still a presentation helper from Yahoo; it is explicitly labelled.
    t = yf.Ticker(symbol)
    hist = t.history(period=period, interval=interval)
    if hist.empty:
        return {"error": f"No data for {symbol}", "data": []}
    data = []
    for idx, row in hist.iterrows():
        ts = idx.strftime("%Y-%m-%d") if interval in ("1d", "1wk", "1mo") else idx.isoformat()
        data.append({
            "time": ts,
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
        })
    return {
        "ticker": symbol,
        "period": period,
        "interval": interval,
        "data": data,
        "price_source": "YAHOO_FINANCE_VIA_YFINANCE",
        "fallback_used": True,
        "fallback_reason": "UNSUPPORTED_TRADEBRAIN_PRESENTATION_INTERVAL" if interval == "1wk" else "TRADEBRAIN_CHART_FALLBACK",
    }


@router.get("/indicators/{ticker}")
def get_indicators(
    ticker: str,
    indicators: str = Query("rsi,macd,boll_ub,boll_lb,close_10_ema,close_50_sma,atr,vwma"),
    lookback_days: int = Query(60),
):
    """Get technical indicators from the configured Trade Brain price source."""
    from tradingagents.dataflows.interface import route_to_vendor

    symbol = normalize_ticker(ticker)
    end_date = datetime.now().strftime("%Y-%m-%d")
    results = {}
    for indicator in indicators.split(","):
        indicator = indicator.strip()
        try:
            results[indicator] = route_to_vendor("get_indicators", symbol, indicator, end_date, lookback_days)
        except Exception as e:
            results[indicator] = f"Error: {str(e)}"
    return {"ticker": symbol, "indicators": results}


@router.get("/fundamentals/{ticker}")
def get_fundamentals(ticker: str):
    """Get company fundamentals (not a Kite data class)."""
    symbol = normalize_ticker(ticker)
    t = yf.Ticker(symbol)
    info = t.info
    return {
        "ticker": symbol,
        "name": info.get("shortName", symbol),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "pb_ratio": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "eps": info.get("trailingEps"),
        "roe": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "revenue": info.get("totalRevenue"),
        "profit_margin": info.get("profitMargins"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "avg_volume": info.get("averageVolume"),
        "beta": info.get("beta"),
        "data_source": "YAHOO_FINANCE_FUNDAMENTALS",
    }


@router.get("/news/{ticker}")
def get_news(ticker: str, count: int = Query(10)):
    """Get latest news for a ticker (not a Kite data class)."""
    symbol = normalize_ticker(ticker)
    t = yf.Ticker(symbol)
    news = t.get_news(count=count)
    articles = []
    for article in (news or []):
        if "content" in article:
            content = article["content"]
            articles.append({
                "title": content.get("title", ""),
                "summary": content.get("summary", ""),
                "publisher": content.get("provider", {}).get("displayName", "Unknown"),
                "url": (content.get("canonicalUrl") or content.get("clickThroughUrl") or {}).get("url", ""),
                "published_at": content.get("pubDate", ""),
            })
        else:
            articles.append({
                "title": article.get("title", ""),
                "summary": "",
                "publisher": article.get("publisher", "Unknown"),
                "url": article.get("link", ""),
                "published_at": "",
            })
    return {"ticker": symbol, "news": articles, "data_source": "YAHOO_FINANCE_NEWS"}


@router.get("/market-status")
def get_market_status():
    """Get current Indian market status (index context remains a separate helper)."""
    from tradingagents.utils.market_calendar import get_market_session, is_trading_day

    nifty = yf.Ticker("^NSEI")
    banknifty = yf.Ticker("^NSEBANK")
    nifty_hist = nifty.history(period="2d")
    banknifty_hist = banknifty.history(period="2d")

    def extract_quote(hist):
        if hist.empty:
            return {"price": 0, "change": 0, "change_percent": 0}
        current = hist.iloc[-1]
        prev = hist.iloc[-2]["Close"] if len(hist) > 1 else current["Close"]
        price = current["Close"]
        change = price - prev
        return {
            "price": round(price, 2),
            "change": round(change, 2),
            "change_percent": round(change / prev * 100, 2) if prev else 0,
        }

    return {
        "session": get_market_session(),
        "is_trading_day": is_trading_day(),
        "nifty": extract_quote(nifty_hist),
        "banknifty": extract_quote(banknifty_hist),
        "index_context_source": "YAHOO_FINANCE_HELPER",
    }
