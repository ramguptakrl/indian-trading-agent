"""Run the Trade Brain Kite WebSocket market-data-only stream.

Requires KITE_API_KEY, KITE_ACCESS_TOKEN and KITE_LIVE_SUBSCRIPTIONS, for example:
    KITE_LIVE_SUBSCRIPTIONS=NSE:BSE

This process never places, modifies, or cancels orders. It only persists the latest
binary quote state; finalized replay candles continue to come from historical APIs.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from backend.tradebrain.kite_data import KiteDataOnlyClient
from backend.tradebrain.kite_stream import KiteMarketDataStream, upsert_latest_kite_quote


def _subscriptions() -> list[tuple[str, str]]:
    raw = (os.getenv("KITE_LIVE_SUBSCRIPTIONS") or "").strip()
    if not raw:
        raise ValueError("KITE_LIVE_SUBSCRIPTIONS is required, e.g. NSE:BSE")
    output: list[tuple[str, str]] = []
    for item in raw.split(","):
        value = item.strip().upper()
        if not value:
            continue
        if ":" not in value:
            raise ValueError(f"Invalid subscription {value}; expected EXCHANGE:SYMBOL")
        exchange, symbol = value.split(":", 1)
        if exchange not in {"NSE", "BSE"} or not symbol:
            raise ValueError(f"Unsupported subscription {value}")
        output.append((exchange, symbol))
    if not output:
        raise ValueError("No valid Kite live subscriptions were configured")
    return output


async def main() -> None:
    mode = (os.getenv("KITE_LIVE_MODE") or "quote").strip().lower()
    rest = KiteDataOnlyClient()
    stream = KiteMarketDataStream()
    token_map: dict[int, tuple[str, str]] = {}
    for exchange, symbol in _subscriptions():
        instrument = rest.resolve_equity_instrument(exchange, symbol)
        token_map[int(instrument["instrument_token"])] = (exchange, symbol)

    print(json.dumps({
        "status": "CONNECTING",
        "credential_role": "MARKET_DATA_ONLY",
        "mode": mode,
        "subscriptions": [f"{ex}:{sym}" for ex, sym in token_map.values()],
        "order_api_enabled": False,
    }), flush=True)

    async for tick in stream.stream(list(token_map), mode=mode):
        identity = token_map.get(int(tick["instrument_token"]))
        if identity is None:
            continue
        exchange, symbol = identity
        saved = upsert_latest_kite_quote(tick, exchange=exchange, symbol=symbol)
        print(json.dumps({
            "exchange": exchange,
            "symbol": symbol,
            "last_price": saved["last_price"],
            "exchange_timestamp": saved.get("exchange_timestamp"),
            "received_at": saved["received_at"],
            "source": "ZERODHA_KITE_WEBSOCKET_MARKET_DATA_ONLY",
        }), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
