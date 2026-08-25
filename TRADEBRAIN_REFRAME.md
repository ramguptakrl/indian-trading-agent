# Trade Brain Reframe — Canonical Product Architecture

Status: **v0.13.0 product doctrine**  
Branch: `tradebrain/reframe-foundation`

## 1. Product identity

Trade Brain is a BSE Ltd (`NSE:BSE`) focused Indian-equity research, replay, validation
and advisory system. It uses the upstream multi-agent research stack but adds an audited,
deterministic control/evidence plane.

LLMs interpret and synthesize. They are not the source of truth for identity, prices,
exchange sessions, broker permission, funding eligibility, costs, hard risk rules or
execution.

## 2. Active trade modes

### INTRADAY

- resident cash equity;
- LONG or SHORT;
- same session only;
- explicit Entry / Stop-Loss / Take-Profit;
- no fresh entry from 15:10 IST;
- intended flat before 15:15 IST.

### SWING

- resident multi-day equity;
- LONG only;
- explicit Entry / Stop-Loss / Take-Profit;
- **Zerodha MTF-funded only in the active product**;
- current MTF eligibility must be verified;
- positive funded amount required;
- financing/holding-days scenario required for complete net-cost advice;
- CNC own-cash may remain readable in historical records but is not an active SWING
  funding option.

MTF is a funding dimension of SWING, not a separate trade mode. Overnight cash-equity
SHORT remains outside the product.

## 3. Trader identity vs data credential identity

Modeled trader: `RESIDENT_INDIAN`.

A Kite credential may be used strictly as `MARKET_DATA_ONLY`, even if the credential
belongs to another account type. Credential identity must not silently rewrite resident
policy/economics.

Allowed Kite uses: instruments, quotes, historical candles, WebSocket live state and
replay/backtest inputs. No order route exists.

## 4. Architecture

```text
OFFICIAL / REFERENCE DATA          MARKET DATA
identity, filings, calendar         Kite-primary + audited fallback
            |                              |
            +--------------+---------------+
                           |
                IDENTITY + PROVENANCE
                           |
                 MULTI-AGENT RESEARCH
                           |
                 STRICT STRUCTURED PARSE
                           |
                AUDITED HISTORY / REPLAY
                           |
                 BSE FOCUS / STRUCTURE LABS
                           |
              FROZEN CHALLENGER VALIDATION
                           |
              HUMAN-APPROVED SOFT REGISTRY
                           |
            VERIFIED SESSION / MARKET GUARDS
                           |
             EXPLICIT BROKER/FUNDING STATE
                           |
                DETERMINISTIC HARD GATE
                           |
       INTRADAY COSTS / SWING EQUITY+MTF COSTS
                           |
                      ADVISORY
                           |
              TRADE AUTHORIZATION = FALSE
                 ORDER EXECUTION = OFF
```

## 5. Hard rules above AI and learning

Protected boundaries include:

- advisory only / no automatic orders;
- active modes only INTRADAY and SWING;
- explicit Entry / SL / TP geometry;
- INTRADAY 15:10 no-fresh-entry and 15:15 hard-exit boundary;
- no overnight cash-equity short;
- SWING LONG only;
- active SWING MTF only;
- verified MTF eligibility outranks model opinion;
- positive funded amount required for MTF SWING;
- Severe Crash Guard can block fresh LONG exposure;
- verified exchange/broker/funding restrictions outrank AI;
- unknown critical state fails closed;
- raw agent BUY/SELL prose is not trade permission.

## 6. Cost architecture

`equity_costs.py` remains the versioned resident-equity transaction-cost component.

`mtf_economics.py` remains the versioned Zerodha incremental MTF funding profile.

`swing_mtf.py` combines them for active SWING so target, stop and break-even calculations
can include both statutory/transaction costs and MTF financing costs without rewriting
historical base-equity records.

## 7. Learning governance

Soft parameters may learn only through frozen chronological evidence, out-of-sample /
walk-forward validation and explicit human approval. Hard policy fields are never read
from the soft registry.

## 8. BSE research profile

BSE Ltd is the only trade target. Broader Indian-market data is context, not a generic
multi-stock trading surface.

Research includes multi-timeframe structure, regime, volume, events, opening gaps,
patterns, false breaks, level reliability, time-to-target and historical analogues.
Exploratory findings remain research-only until validated.

## 9. Trustworthy result

A trustworthy result exposes:

1. source/timestamped evidence;
2. structured AI candidate/parser status;
3. verified calendar/session and market state;
4. explicit Crash Guard and broker permission;
5. explicit SWING MTF state when applicable;
6. deterministic PASS / WAIT / BLOCK / HARD_EXIT;
7. Entry / TP / SL / gross R:R;
8. resident net costs and, for SWING, MTF funding costs;
9. advisory-only/no-order boundary.

## 10. Execution boundary

Trade Brain may observe broker market data and may record what the human did externally.
It does not place, modify or cancel broker orders.

Any future decision to add broker execution requires a new explicit owner decision and a
separate safety/design review. It is not implied by MTF modeling.
