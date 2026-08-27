# Trade Brain v0.14 — Historical Market Replay Addendum

Date: 2026-08-26

## Purpose

Trade Brain can replay historical BSE Ltd market data in the same conceptual way that a trader uses TradingView candle replay: move forward through time, expose only information available at that historical moment, record a model prediction, reveal the outcome later, and allow the matured outcome to become research evidence only after it genuinely exists.

This is a **prequential / walk-forward replay layer**, not a replacement for the frozen chronological optimizer.

## Two different proofs remain required

1. **Frozen chronological optimizer**
   - discovery/training: 2017–2022
   - validation: 2023–2024
   - OOS: 2025
   - historical holdout: 2026 freeze window
   - model/feature/threshold selection never uses OOS or holdout.

2. **Historical market replay**
   - advances through historical sessions in order;
   - scores only point-in-time completed features;
   - labels are not trainable until `label_end` has matured;
   - intraday models remain frozen for the entire trading session;
   - after-market model refits are explicit research events, not automatic live-policy changes.

Agreement between both forms of evidence is stronger than either one alone.

## No-cheating boundary

At historical decision time **T**, the replay may use only information that was provably available by **T**.

Forbidden examples include:
- future candles or the final high/low of an unfinished candle;
- outcomes whose stop/target/time-exit has not yet occurred;
- a later daily candle while replaying an earlier intraday candle;
- news published or first available after T;
- later article edits when the original historical text/timestamp cannot be reconstructed;
- future NIFTY/context bars;
- future corporate-action knowledge backfilled into an earlier raw-price decision.

Missing or unverifiable evidence is excluded rather than guessed.

## News policy

News is **disabled by default** in the V1 ML replay feature matrix.

A future news challenger must carry, at minimum:
- `published_at`
- `available_at`
- `timestamp_verified`
- source/provenance

Both `published_at` and `available_at` must be at-or-before the historical decision time. Unverified or missing timestamps are excluded. A later repost does not make the story available earlier.

The technical/context-only model remains the baseline. News earns inclusion only by improving leakage-safe out-of-sample and prospective evidence after costs.

## Retraining policy

Historical replay occurs **day by day**, but this does **not** mean the production model is blindly rebuilt every day.

Default replay behavior:
- fit from matured historical evidence at the replay start;
- freeze the model through each intraday session;
- mature labels as history advances;
- score calibration/drift after market;
- run challenger/retraining work only on an explicit cadence or research trigger;
- never self-promote a refitted model into advisory weighting.

`retrain_every_sessions=1` is therefore an explicit research-only experiment and requires an opt-in flag. This prevents the system from treating model churn as intelligence.

## Horizon-specific replay clocks

### Intraday Long / Intraday Short

- model training cutoff is the market-session start;
- no same-day labels are used to refit the model during the session;
- each completed 15-minute feature row is scored by the same session-frozen model;
- no fresh entry from 15:10 IST;
- hard exit before/at the existing 15:15 safety boundary;
- no overnight short.

### Swing Long MTF

- model may be updated only after market using already matured labels;
- a swing example does not enter training until its target/stop/time-exit is actually resolved;
- Zerodha resident-equity costs, MTF brokerage/pledge/interest and slippage remain part of the label economics;
- MTF eligibility/funding permission is still verified independently at advisory time.

## Authority boundary

Historical replay is research evidence only:

- `advisory_only = true`
- `trade_authorization = false`
- `order_execution_allowed = false`
- no model promotion without the existing human review ladder
- no weakening of BSE identity, session, MTF, cost, market-data, or hard-risk gates

The replay engine is allowed to prove that a model is unstable. A negative replay result is a successful safety outcome, not a reason to relax the rules.
