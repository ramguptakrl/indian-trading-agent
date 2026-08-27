# Trade Brain — Kite market-data plane

Trade Brain v0.12.0 treats Zerodha Kite as the preferred market-price transport when credentials are configured.

## Roles

### Kite Historical REST
Used for finalized historical candles that enter the audited Phase-3 market store and can feed replay/backtests. Long ranges are split into conservative request windows and every chunk remains separately recorded in the fetch ledger.

### Kite REST Quotes
Used for on-demand LTP/OHLC/full quote snapshots.

### Kite WebSocket
Used for continuous live market state. The binary parser supports documented LTP, quote and full packets for NSE/BSE equities/indices. Live ticks are stored only as latest live quote state and are **not** silently treated as finalized replay candles.

### Yahoo/yfinance
Remains an explicitly labelled fallback/research source. If Kite credentials are absent, or if a Kite request fails and fallback is allowed, the result states that Yahoo was used and why.

## Credential boundary

A Kite credential can belong to an NRI account and still be used as `MARKET_DATA_ONLY`. Credential account type does not change:

- modeled trader: `RESIDENT_INDIAN`
- active modes: `INTRADAY`, `SWING`
- resident transaction-cost profile
- hard policy
- order permissions

No order placement/modification/cancellation methods exist in the Trade Brain Kite adapters.

## Configuration

```env
KITE_API_KEY=
KITE_ACCESS_TOKEN=
KITE_LIVE_SUBSCRIPTIONS=NSE:BSE
KITE_LIVE_MODE=quote
```

Then the optional standalone live process is:

```bash
python scripts/tradebrain_kite_live_stream.py
```

This process resolves exact equity instrument tokens through Kite's instrument master, subscribes to the configured instruments and persists only their latest market quote state.

## API surface

- `GET /api/tradebrain/phase9/data/status`
- `POST /api/tradebrain/phase9/data/sync-preferred-history`
- `POST /api/tradebrain/phase9/kite/quote`
- `POST /api/tradebrain/phase9/kite/sync-history`
- `POST /api/tradebrain/phase9/kite/sync-history-range`
- `GET /api/tradebrain/phase9/kite/live/latest/{exchange}/{symbol}`

## Safety contract

- WebSocket text order postbacks are ignored by the market-data plane.
- Market-data ticks do not authorize trades.
- Live ticks are not finalized candles.
- Historical replay still obeys `ts_close <= as_of`.
- `trade_authorization=false`.
- `order_execution_allowed=false`.
- `order_api_enabled=false`.

## Current validation status

The binary protocol parser, heartbeat handling, malformed-frame rejection, order-postback ignoring, live-state persistence, source-selection logic, and range chunk planning are fixture/unit tested without credentials.

A real Kite live/historical success claim must wait until valid `KITE_API_KEY` and `KITE_ACCESS_TOKEN` credentials are configured.
