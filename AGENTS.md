# Trade Brain — Repository Guardrails

## PROJECT ISOLATION

This repository is **Indian Trading Agent Trial / Trade Brain / BSE Engine**.
**Kronos-BSE is a separate project.** Never import, infer, copy, merge, or reuse its
code/state unless the owner explicitly requests a cross-project migration.

For continuation work, use this priority:

1. current code on `tradebrain/reframe-foundation`
2. `PROJECT_STATE.md`
3. this file
4. canonical `TRADEBRAIN_*.md` documents
5. current PR/CI state
6. conversation memory only when it does not conflict

## Non-negotiable product boundary

- Modeled trader: `RESIDENT_INDIAN`.
- Trade target: initially BSE Ltd (`NSE:BSE`).
- Active trade modes only: `INTRADAY` and `SWING`.
- `INTRADAY`: LONG or SHORT cash equity, same-session only; no fresh entry from
  15:10 IST; intended flat by 15:15 IST; no overnight short.
- `SWING`: LONG-only, multi-day, **Zerodha MTF-funded**.
- `MTF` is a SWING funding mechanism, not a third trade mode.
- Active SWING must not PASS as `CNC_OWN_CASH`.
- Historical `CNC_OWN_CASH` labels may remain readable for audit/replay only.
- Active SWING requires verified MTF eligibility and a positive funded amount.
- Net SWING economics must combine normal resident equity transaction costs with the
  versioned Zerodha MTF profile (interest, MTF brokerage, pledge/unpledge and applicable
  broker square-off charges).
- Automatic broker order execution remains disabled.
- No Trade Brain class/router may expose place/modify/cancel order methods without a
  new explicit owner decision.

## AI boundary

Multi-agent/LLM output is research/candidate generation, not authority. Safe labels are:

- `LONG_CANDIDATE`
- `SHORT_CANDIDATE`
- `EXIT_CANDIDATE`
- `WAIT`
- `NO_TRADE`

Do not infer a trade from free-form bullish/bearish prose. Every new-entry candidate
must pass the deterministic Trade Brain gate.

## Deterministic control order

1. strict labelled candidate parse
2. verified exchange calendar/session
3. explicit Crash Guard state
4. explicit broker/exchange permission
5. deterministic hard-rule gate
6. for SWING: MTF-only funding/eligibility/funded-amount gate
7. approved/default soft preference
8. resident transaction-cost scenario; for SWING add MTF costs
9. advisory-only output

Fail closed when required deterministic state is unknown.

## Learning boundary

- Hard rules never self-optimize.
- Challenger definitions/windows are frozen before evaluation.
- Validation/walk-forward evidence drives review readiness.
- Soft parameters affect runtime only after explicit human approval.
- Prospective hypotheses never backfill pre-freeze observations as untouched evidence.

## Actual-trade boundary

`ACTUAL_MANUAL_TRADE` records what the human actually executed externally.

- Keep it separate from replay/paper evidence.
- Preserve linked advisory snapshots and direction mismatches.
- Preserve partial exits.
- Estimated charges must be labelled estimates until actual broker charges are supplied.
- For SWING, MTF financing must eventually be represented explicitly; never silently
  estimate an MTF trade using own-cash delivery economics and call it complete.
- UI journal actions never send broker orders.

## Data / Kite boundary

- Preserve raw source evidence, provenance and historical cutoffs.
- Kite is `MARKET_DATA_ONLY`: instruments, historical candles, REST quotes,
  WebSocket live state, replay/backtest input.
- Yahoo/yfinance is an explicitly labelled fallback/research source.
- A Kite credential's account type does not redefine the modeled resident trader.
- No Kite order mutation methods.

## Frontend wording

Always expose:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

Historical BUY/SELL/HOLD records are compatibility data only, never live permission.

## Validation

Before declaring a change complete:

- run Trade Brain Python tests;
- compile changed control-plane modules;
- build the frontend when the API/UI contract changes;
- keep live-source smokes observational/non-performance-claiming;
- never claim authenticated Kite success without real authenticated validation.
