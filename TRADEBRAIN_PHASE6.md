# Trade Brain Phase 6 — Resident Costs + Active SWING MTF Economics

Status: revised for Trade Brain **v0.13.0** on 2026-08-25.

## Product decision

Active modes:

- `INTRADAY`
- `SWING`

`SWING` is LONG-only and **Zerodha MTF-funded only** in the active product. MTF is funding,
not a third mode. Historical own-cash SWING records may remain readable for compatibility,
but they are not live permission.

## Cost layers

### Base resident equity component

`backend/tradebrain/equity_costs.py` calculates resident equity transaction/statutory
costs. It is intentionally a non-funding component and no longer advertises an own-cash
SWING funding policy.

### Zerodha MTF incremental component

`backend/tradebrain/mtf_economics.py` models the separately versioned MTF funding layer:

- funded amount and user cash contribution;
- daily interest on funded amount;
- MTF brokerage;
- pledge/unpledge charges;
- applicable RMS square-off charge scenarios;
- MTF-to-CNC eligibility review.

### Active SWING combined component

`backend/tradebrain/swing_mtf.py` combines the base resident transaction-cost component
with the MTF layer for SWING target/stop/break-even scenarios. It never exposes broker
execution.

## MTF paper ledger

`backend/tradebrain/mtf_paper_ledger.py` is the active funding-aware SWING paper-accounting
path.

It:

- requires verified MTF eligibility;
- reserves the user-side cash contribution plus a conservative cost cushion rather than
  pretending the user funds the full position notional;
- stores funded amount separately;
- requires explicit positive interest-days when closing an MTF paper position;
- realizes net P&L once;
- preserves resident transaction costs plus MTF financing costs.

The older generic paper ledger remains useful for INTRADAY and historical compatibility;
it must not be interpreted as active own-cash SWING permission.

## Public API boundary

Phase 6 exposes:

- resident base cost/profile information;
- MTF rule snapshot;
- SWING MTF cost / net-target calculations;
- INTRADAY paper-accounting routes;
- funding-aware SWING MTF paper open/close/read paths.

Generic base-equity cost/net-target routes reject active SWING use where that would omit
required MTF funding economics.

## Safety

- SWING SHORT remains blocked.
- Active SWING requires verified MTF eligibility.
- Funded amount must be explicit and below modeled entry notional.
- Holding/interest days are explicit for complete net economics.
- Base resident costs and MTF funding costs stay versioned separately for reproducibility.
- Kite credentials remain market-data-only.
- No place/modify/cancel broker-order method exists.
