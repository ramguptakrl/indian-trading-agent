# Trade Brain — Actual Manual Trade Journal + Position Guardian

Status: Trade Brain **v0.13.0**.

## Purpose

The journal keeps human-executed evidence separate from replay and paper research:

```text
HYPOTHETICAL_REPLAY  = what a frozen historical rule would have done
PAPER / SIMULATION   = simulated position/account behavior
ACTUAL_MANUAL_TRADE  = what the human actually executed externally at the broker
```

These evidence classes are intentionally not merged.

## Advisory-linked workflow

```text
Trade Brain advisory
      ↓
Human executes externally at broker
      ↓
I TOOK THIS TRADE
      ↓
Record actual entry / qty / time / funding context
      ↓
Actual Trades dashboard + read-only Position Guardian
      ↓
Human executes partial/full exit externally
      ↓
Record actual exit slice(s)
      ↓
Permanent actual fill + outcome evidence
```

The persisted advisory snapshot may be copied into the linked actual-trade record. If the
human direction differs from the advisory, the mismatch is preserved rather than rewritten.

## Supported states

- `OPEN`
- `PARTIALLY_CLOSED`
- `CLOSED`

Partial exits are separate fill records with their own quantity, price, timestamp, charges
and optional broker reference.

## Active fields

An actual trade can record:

- BSE Ltd / NSE identity
- `INTRADAY` or `SWING`
- actual direction where policy permits it
- actual entry quantity / price / timestamp
- stop-loss / primary target context
- optional broker order/trade reference
- notes
- one or more exit fills
- actual broker-charge override for a closed slice

For active `SWING`:

- LONG only
- funding must be `MTF`
- current MTF eligibility verification is recorded
- funded amount is stored separately from user cash contribution
- explicit MTF interest-days are required for fully modeled mark/close economics

## Mark-to-market

Journal mark calculations are estimates, not broker-confirmed balances.

For SWING MTF, estimates include resident transaction costs plus MTF financing when the
required funding fields are present. Partial closes allocate the modeled position costs
proportionally to the closed slice.

Actual broker charges may override an estimate for a closed slice without rewriting the
recorded fills.

## Position Guardian

Position Guardian is read-only risk interpretation layered on the journal. It does not
replace the journal's recorded fills or place orders.

Guardian consumes:

- open/partially-closed BSE trade state;
- **fresh persisted Kite BSE quote data**;
- market/data-integrity guard state;
- permanent corporate-action memory;
- local BSE event/news risk;
- audited BSE regime context;
- optional audited NIFTY 50 broader-market correction context.

Guardian fails closed when the persisted Kite quote is missing, malformed or stale. A
stale quote is not allowed to trigger stop/target/HOLD interpretation.

Guardian priority protects:

- INTRADAY 15:15 hard exit;
- confirmed market halt;
- suspicious/freak tick confirmation;
- stock-split position reconciliation;
- dividend ex-date economic review;
- recorded stop breach;
- primary-target review;
- adverse position + high-impact event/correction review.

A stock-split ex-date outranks raw stop/P&L interpretation so a mechanical price reset
cannot be mistaken for an ordinary loss before quantity/cost-basis reconciliation.

## Policy observations

The journal records reality even when the human trade violates Trade Brain policy, for
example:

- direction differs from linked advisory;
- INTRADAY entry after the no-fresh-entry boundary;
- INTRADAY exit after 15:15 IST;
- INTRADAY carried overnight.

These observations do not erase the real trade.

## Execution boundary

This feature is **not broker order execution**.

```text
manual_tracking_only = true
trade_authorization = false
order_execution_allowed = false
```

Buttons such as `I TOOK THIS TRADE`, `Partial Close`, and `Close Trade` update the local
Trade Brain journal only after the human has acted externally.

No place/modify/cancel broker-order method is introduced by this feature.
