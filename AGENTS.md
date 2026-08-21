# Trade Brain — Repository Guardrails

This repository is a reframed fork of `pradeepsiddappa/indian-trading-agent`.
The governing architecture is the Trade Brain control plane documented in:

- `TRADEBRAIN_REFRAME.md`
- `TRADEBRAIN_PHASE4.md`
- `TRADEBRAIN_PHASE5.md`
- `TRADEBRAIN_PHASE6.md`
- `TRADEBRAIN_PHASE7_TO_10.md`

## Non-negotiable product boundary

- Modeled trader: `RESIDENT_INDIAN`.
- Active equity modes only: `INTRADAY` and `SWING`.
- `INTRADAY`: LONG/SHORT, same-session only; no fresh entry from 15:10 IST; flat by 15:15 IST.
- `SWING`: LONG-only cash/delivery using own cash.
- MTF is removed from the active architecture.
- Automatic order execution is disabled.
- No Trade Brain code may add or expose place/modify/cancel broker-order methods unless the product decision is explicitly changed by the owner.

## AI boundary

Multi-agent/LLM output is research evidence and a candidate generator, not an authority.
The only safe current research labels are:

- `LONG_CANDIDATE`
- `SHORT_CANDIDATE`
- `EXIT_CANDIDATE`
- `WAIT`
- `NO_TRADE`

Do not reintroduce a final raw `BUY` / `SELL` / `HOLD` execution signal.
Free-form bullish/bearish prose must never be inferred into a trade.
A new-entry candidate must pass the deterministic Trade Brain gate.

## Deterministic control order

For live-use validation, preserve the sequence:

1. strict labelled candidate parse
2. verified exchange calendar/session
3. explicit Crash Guard state
4. explicit broker/exchange permission
5. deterministic hard-rule gate
6. approved/default soft preference
7. resident transaction-cost scenario

Fail closed when required deterministic state is unknown.

## Learning / optimization boundary

- Hard rules are protected and never auto-optimized.
- Phase-5 challenger definitions and windows are frozen before evaluation.
- TRAIN is diagnostic only; validation/walk-forward evidence drives review readiness.
- Soft parameters affect runtime only after explicit human approval and activation.
- Legacy recommender scores/probabilities remain heuristic/non-authorizing evidence.

## Data boundary

- Preserve raw source evidence, SHA-256 provenance and source identity.
- Avoid future leakage: historical replay must respect `ts_close <= as_of` and event-publication cutoffs.
- Do not silently rewrite raw traded prices into adjusted history.
- NSE/BSE calendar evidence must be exchange-aware; do not assume BSE shares NSE special sessions without verified evidence.

## Zerodha Kite boundary

Kite is `MARKET_DATA_ONLY` in this project.
Allowed uses: instrument master, quotes, historical candles, replay/backtest input.
A Kite credential may belong to an NRI account, but that credential type must not alter the modeled resident trader, resident cost profile or policy.

## Frontend wording

User-facing Deep Analysis must say research/candidate/advisory, not guaranteed decision/order.
Always expose that:

- `advisory_only=true`
- `trade_authorization=false`
- `order_execution_allowed=false`

Historical upstream `BUY/SELL/HOLD` records may be rendered for compatibility but must be clearly treated as legacy/non-authorizing.

## Validation

Before declaring a Trade Brain change complete:

- run Python Trade Brain tests;
- compile changed backend/control-plane modules;
- build the Next.js frontend when the advisory contract/UI changes;
- keep observational live-source smokes non-performance-claiming;
- never call an unverified/blocked/empty external response a successful source validation.

Preserve useful upstream scanners, UI, data abstractions and multi-agent research where they do not violate these boundaries.
