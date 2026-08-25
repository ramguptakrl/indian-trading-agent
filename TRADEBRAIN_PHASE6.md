# Trade Brain Phase 6 — Resident Costs, MTF SWING Economics and Paper Compatibility

Status: revised for Trade Brain **v0.13.0** on 2026-08-25.

## Product decision

Active modes remain:

- `INTRADAY`
- `SWING`

`SWING` is LONG-only and **MTF-funded only** in the active product. MTF is funding, not
a third mode. Historical own-cash SWING records remain readable but are not live
permission.

## Cost layers

### Base resident equity component

`backend/tradebrain/equity_costs.py` remains versioned and non-MTF. It calculates
resident equity statutory/transaction costs and preserves historical reproducibility.

### Zerodha MTF incremental component

`backend/tradebrain/mtf_economics.py` models the separately versioned MTF funding layer:
funded amount, daily interest, MTF brokerage, pledge/unpledge and applicable RMS
square-off charges.

### Active SWING combined component

`backend/tradebrain/swing_mtf.py` combines both layers for SWING target/stop/break-even
net economics. It never exposes broker execution.

## Public API boundary

Phase 6 exposes dedicated MTF rules, SWING MTF cost and SWING MTF net-target routes.

The generic base-equity cost/net-target routes reject `mode=SWING` so callers cannot
accidentally treat active SWING as zero-financing own-cash delivery.

The legacy Phase-6 paper ledger was built around full-notional cash reservation. Its
public open-position route rejects new SWING use until MTF funding fields are integrated.
Historical/direct compatibility records are not reinterpreted.

## Safety

- SWING SHORT remains blocked.
- Active SWING requires verified MTF eligibility.
- Funded amount must be explicit.
- Holding/interest days are explicit for complete net economics.
- Kite credentials remain market-data-only.
- No order placement endpoint exists.
