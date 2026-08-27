# BSE Trade Brain — Project Memory

> **Purpose:** This Wiki is the durable project memory for the BSE Ltd Trade Brain. It records what is implemented, what is verified, what is only experimental, what remains, and the exact safety doctrine. It should be updated whenever a meaningful architecture, research, data, test, checkpoint, or roadmap decision changes.

**Active development branch:** `tradebrain/reframe-foundation`

**Current branch head at Wiki bootstrap:** `a33c6769e0e7fb664f0337e65260004c71414282`

**Last fully certified statistical-governance boundary:** `5700f2e8282583ef7f9acb87a5641a4ccf23d379`

**Status rule:** A newer commit is **not** called green merely because an older boundary passed CI. New code must receive exact-head certification.

## Navigation

- [Current Status](Current-Status)
- [Architecture and Product Doctrine](Architecture-and-Doctrine)
- [ML Research Plan](ML-Research-Plan)
- [Roadmap and Next Steps](Roadmap-and-Next-Steps)
- [Checkpoints and Recovery](Checkpoints-and-Recovery)
- [Wiki Maintenance Policy](Wiki-Maintenance-Policy)

## One-sentence state

Trade Brain is a **BSE Ltd-only, advisory-only research/trading-decision system** with deterministic risk rules, audited chronological ML research, multiple-testing controls, model registry/shadow infrastructure, and no broker order authority; the statistical-governance core is certified, while the newest structural-break, meta-label, kill-criteria, and causal sequence challengers require exact-head CI before they can be called green.

## Non-negotiable boundaries

- Canonical instrument: `NSE:BSE`
- ISIN: `INE118H01025`
- Equity only; no F&O.
- Intraday supports LONG and SHORT research/advisory, same-session only.
- No fresh intraday entry after 15:10 IST; flat before 15:15 IST.
- Swing is LONG-only and modeled as Zerodha MTF.
- Kite credentials are **market-data-only**.
- Broker execution is OFF.
- Every ML/research artifact must preserve:
  - `advisory_only=true`
  - `trade_authorization=false`
  - `order_execution_allowed=false`
- Hard deterministic rules outrank ML.
- Missing, stale, conflicting, or unverifiable critical evidence fails closed.
- Holdout data must not be used to discover, tune, rank, or choose hypotheses.

## What this Wiki is for

This is not marketing documentation and it is not a performance claim. It exists so future development can answer, without relying on chat memory:

1. What did we already build?
2. What has actually passed tests?
3. Which ideas are only challengers?
4. What statistical safeguards are mandatory?
5. Which checkpoints must never move?
6. What is the next exact work item?

## Current research philosophy

The project treats **researcher overfitting** as a first-class risk. A pretty backtest is insufficient. Candidate evidence must survive chronology, modeled costs, stress, multiple-testing correction, confidence intervals, purged validation, and prospective/shadow evidence before it can influence the advisory system.

No model is automatically promoted to champion. No research code may place orders.
