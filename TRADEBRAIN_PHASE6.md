# Trade Brain Phase 6 — Resident INTRADAY + SWING Economics / Paper Ledger

Status: implemented in Trade Brain **v0.7.0**.

## Product decision

Phase 6 removes MTF from the active architecture. There are only two user-facing trade modes:

- `INTRADAY`
- `SWING`

The modeled trader is a **resident Indian person**.

Historical Phase 0-5 persistence used the labels `DAY` and `SWING_POSITION`. Those remain readable internal aliases solely to preserve replay/audit continuity. They do not represent additional active modes.

## Data credential is not trader identity

A Zerodha/Kite API credential may later be used for:

- live quotes / WebSocket ticks;
- historical candles;
- backtest/replay data.

The credential may belong to an NRI account. That does not change the modeled trader profile.

Phase 6 explicitly records:

- trader profile: `RESIDENT_INDIAN`
- credential role: `MARKET_DATA_ONLY`
- credential account type affects policy: `false`
- credential account type affects cost profile: `false`
- order API enabled: `false`

Therefore NRI brokerage, PIS/Non-PIS rules, NRI TDS treatment and NRI product restrictions are not imported into the resident system merely because the data credential is NRI.

## Resident equity cost profile

The first versioned profile is:

`ZERODHA_RESIDENT_INDIVIDUAL_EQUITY_2026_08`

Verified on 2026-08-21 against Zerodha's public resident-individual/charges documentation.

The engine models:

- resident equity delivery brokerage;
- resident equity intraday brokerage;
- STT;
- NSE/BSE transaction charges;
- SEBI turnover fee;
- equity IPFT charge;
- GST on service/regulatory charge base;
- buy-side stamp duty;
- delivery/SWING DP charge;
- optional adverse slippage on both sides.

The profile is versioned so historical simulations do not silently change when future charges change.

BSE transaction rates can differ for special scrip groups. The standard published equity rate is the default; callers can supply a verified transaction-charge override when the security group requires it.

## Explicitly absent economics

Phase 6 contains no:

- MTF interest;
- funded amount;
- pledge/unpledge MTF fee;
- margin-funded delivery;
- overnight financing calculation.

The cost result always exposes `mtf_used=false`, `funded_amount=0`, and `financing_interest=0`.

## True net economics

Given mode, direction, exchange, quantity, entry, exit and optional slippage, the engine calculates:

- entry/exit fill after adverse slippage;
- buy/sell turnover;
- gross P&L;
- every modeled charge component;
- total charges;
- net P&L;
- net return on entry notional;
- raw exit quote required to break even after costs.

A target solver can also find the raw exit quote required for a desired **net** rupee profit.

## Paper ledger

Phase 6 adds a Trade Brain paper ledger separate from the repository's generic recommendation simulator.

Persistence:

- `tb_phase6_paper_accounts`
- `tb_phase6_paper_positions`

Paper accounts require an explicit starting cash amount; no user capital is silently assumed.

### Buying power

Paper buying power is deliberately conservative:

`CASH_NOTIONAL_CONSERVATIVE`

The ledger reserves full entry notional plus a charge cushion. It does not assume broker intraday leverage and does not use MTF.

### INTRADAY

- LONG or SHORT.
- Fill must represent an Indian cash-market session fill.
- No new paper entry from 15:10 IST.
- Expected to close by 15:15 IST on the same session date.
- A later/overnight close is allowed only so the paper ledger can recover and record the breach; it is flagged `mode_violation=true` rather than pretending the trade was valid.

### SWING

- LONG only.
- Cash/delivery economics.
- Own-cash funding only.
- DP charge included on sale.

### Closing

Closing a paper position:

1. computes the complete round-trip resident cost result;
2. stores gross P&L, total charges and net P&L;
3. releases reserved virtual cash;
4. applies realized **net** P&L exactly once;
5. records any mode violation.

No broker order is sent.

## API

Phase 6 adds `/api/tradebrain/phase6/...` endpoints for:

- doctrine/product boundary;
- resident cost profile;
- data-credential boundary;
- equity round-trip costs;
- desired-net-profit target solver;
- create/read paper accounts;
- open/read/close paper positions;
- list account positions;
- paper-ledger statistics.

There is deliberately no order-placement endpoint.

## Interpretation boundary

The cost engine is an accounting model based on a versioned verified charge snapshot, not a broker contract note. Statutory/broker rates can change and BSE group-specific transaction charges can differ. Before production use, refresh/version the profile from current official broker/exchange documentation rather than mutating historical results.

Automatic execution remains OFF.
