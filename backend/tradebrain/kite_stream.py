"""Read-only Zerodha Kite WebSocket market-data plane.

This module parses Kite's documented binary quote protocol and can maintain the latest
live quote state for exact NSE/BSE equity instruments. It deliberately ignores order
postbacks and exposes no order/position/margin mutation capability.

Historical/replay candles remain the responsibility of the Kite historical REST
adapter; live WebSocket ticks are not silently promoted into finalized candles.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlencode

from backend.db import DB_PATH

KITE_WS_URL = "wss://ws.kite.trade"
KITE_LIVE_SOURCE_KEY = "ZERODHA_KITE_WEBSOCKET_MARKET_DATA_ONLY"
SUPPORTED_MODES = {"ltp", "quote", "full"}


def kite_stream_boundary() -> dict[str, Any]:
    return {
        "credential_role": "MARKET_DATA_ONLY",
        "trader_profile": "RESIDENT_INDIAN",
        "live_transport": "KITE_WEBSOCKET",
        "historical_transport": "KITE_REST_HISTORICAL",
        "live_ticks_are_finalized_candles": False,
        "order_updates_consumed": False,
        "order_api_enabled": False,
        "place_order_method_present": False,
        "modify_order_method_present": False,
        "cancel_order_method_present": False,
    }


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _i32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">i", data, offset)[0]


def _price(data: bytes, offset: int) -> float:
    # This adapter is intentionally restricted to NSE/BSE equities/indices, whose
    # documented price divisor is 100. Currency packet scaling is out of scope.
    return _i32(data, offset) / 100.0


def _unix_iso(value: int) -> str | None:
    if value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _parse_packet(packet: bytes) -> dict[str, Any]:
    size = len(packet)
    if size not in {8, 28, 32, 44, 184}:
        raise ValueError(f"Unsupported Kite binary packet length: {size}")

    token = _u32(packet, 0)
    if size == 8:
        return {
            "instrument_token": token,
            "mode": "ltp",
            "last_price": _price(packet, 4),
            "packet_length": size,
        }

    if size in {28, 32}:  # index packet
        item = {
            "instrument_token": token,
            "mode": "full" if size == 32 else "quote",
            "instrument_kind": "INDEX",
            "last_price": _price(packet, 4),
            "high": _price(packet, 8),
            "low": _price(packet, 12),
            "open": _price(packet, 16),
            "close": _price(packet, 20),
            "change": _price(packet, 24),
            "packet_length": size,
        }
        if size == 32:
            item["exchange_timestamp"] = _unix_iso(_u32(packet, 28))
        return item

    item: dict[str, Any] = {
        "instrument_token": token,
        "mode": "full" if size == 184 else "quote",
        "instrument_kind": "TRADEABLE",
        "last_price": _price(packet, 4),
        "last_traded_quantity": _u32(packet, 8),
        "average_traded_price": _price(packet, 12),
        "volume": _u32(packet, 16),
        "total_buy_quantity": _u32(packet, 20),
        "total_sell_quantity": _u32(packet, 24),
        "open": _price(packet, 28),
        "high": _price(packet, 32),
        "low": _price(packet, 36),
        "close": _price(packet, 40),
        "packet_length": size,
    }
    if size == 184:
        item.update(
            {
                "last_trade_timestamp": _unix_iso(_u32(packet, 44)),
                "open_interest": _u32(packet, 48),
                "open_interest_day_high": _u32(packet, 52),
                "open_interest_day_low": _u32(packet, 56),
                "exchange_timestamp": _unix_iso(_u32(packet, 60)),
            }
        )
        depth = []
        for idx in range(10):
            offset = 64 + idx * 12
            depth.append(
                {
                    "side": "BUY" if idx < 5 else "SELL",
                    "quantity": _u32(packet, offset),
                    "price": _price(packet, offset + 4),
                    "orders": _u16(packet, offset + 8),
                }
            )
        item["depth"] = depth
    return item


def parse_kite_binary_frame(data: bytes) -> list[dict[str, Any]]:
    """Parse one documented Kite binary WebSocket frame.

    A single-byte frame is a heartbeat and returns an empty list. Malformed/truncated
    frames fail closed rather than producing partial quote state.
    """
    if len(data) == 1:
        return []
    if len(data) < 2:
        raise ValueError("Kite binary frame is too short")
    packet_count = _u16(data, 0)
    cursor = 2
    output: list[dict[str, Any]] = []
    for _ in range(packet_count):
        if cursor + 2 > len(data):
            raise ValueError("Kite binary frame truncated before packet length")
        packet_length = _u16(data, cursor)
        cursor += 2
        end = cursor + packet_length
        if end > len(data):
            raise ValueError("Kite binary frame truncated inside packet")
        packet = data[cursor:end]
        item = _parse_packet(packet)
        item["packet_sha256"] = hashlib.sha256(packet).hexdigest()
        output.append(item)
        cursor = end
    if cursor != len(data):
        raise ValueError("Kite binary frame contains trailing bytes")
    return output


def classify_kite_text_message(message: str) -> dict[str, Any]:
    """Classify non-market-data text without consuming order postbacks."""
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return {"type": "UNKNOWN_TEXT", "ignored": True}
    if not isinstance(payload, dict):
        return {"type": "UNKNOWN_TEXT", "ignored": True}
    kind = str(payload.get("type") or "UNKNOWN").upper()
    if kind == "ERROR":
        return {"type": "ERROR", "error": payload.get("data"), "ignored": False}
    # Kite may send order postbacks on the same socket. Trade Brain explicitly does
    # not ingest them into the market-data plane.
    return {"type": kind, "ignored": True}


@contextmanager
def _connect(db_path: str | None = None):
    path = db_path or DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_kite_live_schema(db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tb_kite_live_quotes (
                instrument_token INTEGER PRIMARY KEY,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                mode TEXT NOT NULL,
                last_price REAL NOT NULL,
                exchange_timestamp TEXT,
                received_at TEXT NOT NULL,
                packet_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source_key TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tb_kite_live_symbol
              ON tb_kite_live_quotes(exchange, symbol);
            """
        )


def upsert_latest_kite_quote(
    quote: dict[str, Any], *, exchange: str, symbol: str, db_path: str | None = None
) -> dict[str, Any]:
    token = int(quote["instrument_token"])
    received_at = datetime.now(timezone.utc).isoformat()
    payload = {**quote, "exchange": exchange.upper(), "symbol": symbol.upper(), "received_at": received_at}
    ensure_kite_live_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tb_kite_live_quotes(
              instrument_token, exchange, symbol, mode, last_price,
              exchange_timestamp, received_at, packet_sha256, payload_json, source_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(instrument_token) DO UPDATE SET
              exchange=excluded.exchange, symbol=excluded.symbol, mode=excluded.mode,
              last_price=excluded.last_price, exchange_timestamp=excluded.exchange_timestamp,
              received_at=excluded.received_at, packet_sha256=excluded.packet_sha256,
              payload_json=excluded.payload_json, source_key=excluded.source_key
            """,
            (
                token, exchange.upper(), symbol.upper(), str(quote.get("mode") or "unknown"),
                float(quote["last_price"]), quote.get("exchange_timestamp"), received_at,
                str(quote.get("packet_sha256") or ""), json.dumps(payload, sort_keys=True),
                KITE_LIVE_SOURCE_KEY,
            ),
        )
    return payload


def latest_kite_quote(exchange: str, symbol: str, *, db_path: str | None = None) -> dict[str, Any] | None:
    ensure_kite_live_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM tb_kite_live_quotes WHERE exchange=? AND symbol=? ORDER BY received_at DESC LIMIT 1",
            (exchange.upper(), symbol.upper()),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


class KiteMarketDataStream:
    """Async read-only Kite WebSocket client yielding market-data ticks only."""

    def __init__(self, api_key: str | None = None, access_token: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("KITE_API_KEY") or "").strip()
        self.access_token = (access_token or os.getenv("KITE_ACCESS_TOKEN") or "").strip()
        if not self.api_key or not self.access_token:
            raise ValueError("Kite live market data requires KITE_API_KEY and KITE_ACCESS_TOKEN")

    @property
    def boundary(self) -> dict[str, Any]:
        return kite_stream_boundary()

    def websocket_url(self) -> str:
        return f"{KITE_WS_URL}?{urlencode({'api_key': self.api_key, 'access_token': self.access_token})}"

    async def stream(self, instrument_tokens: list[int], *, mode: str = "quote") -> AsyncIterator[dict[str, Any]]:
        if not instrument_tokens:
            raise ValueError("At least one instrument token is required")
        if len(instrument_tokens) > 3000:
            raise ValueError("Kite WebSocket supports at most 3000 subscribed instruments per connection")
        if mode not in SUPPORTED_MODES:
            raise ValueError("mode must be ltp, quote or full")
        tokens = [int(token) for token in instrument_tokens]

        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("websockets package is required for Kite live streaming") from exc

        async with websockets.connect(self.websocket_url(), ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({"a": "subscribe", "v": tokens}))
            await ws.send(json.dumps({"a": "mode", "v": [mode, tokens]}))
            async for message in ws:
                if isinstance(message, bytes):
                    for tick in parse_kite_binary_frame(message):
                        yield tick
                    continue
                classified = classify_kite_text_message(str(message))
                if classified["type"] == "ERROR":
                    raise RuntimeError(f"Kite WebSocket error: {classified.get('error')}")
                # All non-market-data text, including order postbacks, is ignored.
