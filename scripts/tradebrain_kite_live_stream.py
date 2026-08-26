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

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from backend.tradebrain.kite_data import KiteDataOnlyClient
from backend.tradebrain.kite_stream import KiteMarketDataStream, upsert_latest_kite_quote


AUTH_REFRESH_COMMAND = r".\venv\Scripts\python.exe .\scripts\tradebrain_kite_auth.py"


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


def _is_auth_rejection(exc: BaseException) -> bool:
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status in {401, 403}:
            return True
    text = str(exc).lower()
    return (
        "http 401" in text
        or "http 403" in text
        or "tokenexception" in text
        or "invalid or expired token" in text
        or "invalid session" in text
    )


def _emit_failure(exc: BaseException) -> int:
    if _is_auth_rejection(exc):
        payload = {
            "status": "KITE_AUTH_REQUIRED",
            "credential_role": "MARKET_DATA_ONLY",
            "reason": "ZERODHA_SESSION_REJECTED",
            "message": "The current Kite access token was rejected. Refresh the daily Kite session, then restart Trade Brain.",
            "refresh_command": AUTH_REFRESH_COMMAND,
            "order_api_enabled": False,
        }
        print(json.dumps(payload), file=sys.stderr, flush=True)
        return 2

    payload = {
        "status": "KITE_STREAM_FAILED",
        "credential_role": "MARKET_DATA_ONLY",
        "error_type": type(exc).__name__,
        "message": str(exc),
        "order_api_enabled": False,
    }
    print(json.dumps(payload), file=sys.stderr, flush=True)
    return 1


async def main() -> None:
    mode = (os.getenv("KITE_LIVE_MODE") or "quote").strip().lower()
    subscriptions = _subscriptions()
    instruments = [f"{exchange}:{symbol}" for exchange, symbol in subscriptions]

    rest = KiteDataOnlyClient()
    # Validate the same session against a read-only authenticated REST endpoint before
    # attempting the WebSocket handshake. This turns an expired daily token into a
    # clear KITE_AUTH_REQUIRED state instead of an opaque WebSocket HTTP 403 traceback.
    rest.quote(instruments, kind="ltp")

    stream = KiteMarketDataStream()
    token_map: dict[int, tuple[str, str]] = {}
    for exchange, symbol in subscriptions:
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


def run() -> int:
    try:
        asyncio.run(main())
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        return _emit_failure(exc)


if __name__ == "__main__":
    raise SystemExit(run())
