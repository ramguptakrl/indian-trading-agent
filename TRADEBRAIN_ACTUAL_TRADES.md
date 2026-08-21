# Trade Brain — Actual Manual Trade Journal

Trade Brain v0.12.1 adds a separate record of trades the human actually executed at a broker after reviewing an advisory.

## Purpose

The journal answers a different question from replay or paper trading:

```text
HYPOTHETICAL_REPLAY  = what a frozen historical rule would have done
PAPER / SIMULATION   = simulated position/account behavior
ACTUAL_MANUAL_TRADE  = what the human really executed at the broker
```

These evidence classes are intentionally not merged.

## Advisory-linked workflow

```text
Trade Brain advisory
      ↓
Human executes the trade externally at Zerodha/another broker
      ↓
I TOOK THIS TRADE
      ↓
Record actual entry price / qty / time / mode / optional broker ref
      ↓
Actual Trades dashboard
      ↓
Current market-data mark + estimated open net P&L
      ↓
Partial Close or Close Trade after the human executes the exit externally
      ↓
Permanent actual fill history + realized gross/net P&L
```

The exact persisted Trade Brain advisory snapshot is copied into a linked actual-trade record. If the actual direction differs from the advisory, the mismatch is preserved rather than rewritten.

## Supported states

- `OPEN`
- `PARTIALLY_CLOSED`
- `CLOSED`

Partial exits are separate fill records with their own quantity, price, timestamp, charges and optional broker reference.

## Actual fields

An actual trade can record:

- ticker / exchange
- `INTRADAY` or `SWING`
- LONG/SHORT where active policy permits it
- actual entry quantity
- actual entry fill price
- actual entry timestamp
- stop loss / target context
- broker order/trade reference (optional)
- notes
- one or more actual exit fills
- actual broker charge override per closed slice (optional)

## Mark-to-market

Open positions can be marked from the current Trade Brain quote path. When Kite is configured this follows the Kite-primary source hierarchy; without Kite it can use the explicitly-labelled fallback source.

The open estimate exposes:

- current price
- unrealized gross P&L
- estimated resident charges if closed at that mark
- estimated open net P&L
- realized net P&L from any already-closed slices
- combined realized + estimated-open net P&L

This is a mark/estimate, not a broker-confirmed account balance.

## Charges

Until actual broker charges are supplied, Trade Brain uses its versioned resident-equity cost model. A user may enter an `actual_charges_override` for a closed slice from the broker statement/contract note. Estimated charges must never be presented as broker-confirmed charges.

## Policy observations

The journal records reality even when the real trade did not follow Trade Brain policy. Examples:

- direction differs from the linked advisory
- INTRADAY entry after the no-fresh-entry boundary
- INTRADAY exit after 15:15 IST
- INTRADAY carried overnight

These are recorded as integrity/policy observations; the journal does not erase the real trade.

## Execution boundary

This feature is **not broker order execution**.

```text
manual_tracking_only = true
order_execution_enabled = false
```

Buttons such as `I TOOK THIS TRADE`, `Partial Close`, and `Close Trade` only update the Trade Brain journal after the user has acted externally at the broker.

No place/modify/cancel broker-order method is introduced by this feature.

A future read-only broker-reconciliation feature may verify journal entries against broker data, but it must remain separate from order execution unless the owner explicitly changes the product boundary.
