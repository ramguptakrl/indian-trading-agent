# BSE Prospective Hypothesis 001 — First-Hour Confirmation on >=1% Gaps

Status: **FROZEN FOR FUTURE OBSERVATION — NOT PROMOTED**

Frozen after evidence run `#222` on 2026-08-21.  
Instrument: `NSE:BSE` / BSE Ltd / ISIN `INE118H01025`.  
Mode: **INTRADAY only**.  
Trader model: `RESIDENT_INDIAN`.  
Execution: **disabled**.

## Why this hypothesis exists

The exploratory full-history gap study showed that >=1% opening gaps were close to a 55/45 reversal/continuation split overall, but yearly behavior varied materially. The same sample therefore cannot validate either blind continuation or blind fade.

The prospective question is narrower:

> On future BSE Ltd sessions with an absolute opening gap >=1.0%, does waiting for the completed first 45 minutes and requiring continuation confirmation improve net outcome quality versus a fixed blind gap-direction benchmark?

This is a prospective research protocol. No result before the freeze timestamp can count toward validation.

## Eligibility

A session is eligible only when all are true:

1. verified regular NSE cash-market session;
2. BSE Ltd opening price and previous comparable close are available from the audited store;
3. raw-price era is unchanged from the previous comparable session;
4. `abs(open / previous_close - 1) >= 1.0%`;
5. complete 5-minute bars are available from 09:15 through 10:00 IST;
6. the candidate can be evaluated using only information closed by the decision timestamp;
7. resident cost schedule is available.

If any condition is missing, the session is **NOT EVALUABLE**, not a loss or win.

## Fixed benchmark — BLIND_GAP_DIRECTION

Decision timestamp: **10:00 IST**.

- GAP_UP -> LONG candidate.
- GAP_DOWN -> SHORT candidate.
- Entry: first eligible 5-minute bar open at or after 10:00 IST.
- Initial stop:
  - LONG: first-45-minute low (09:15–10:00 completed evidence window).
  - SHORT: first-45-minute high.
- Target: **1.0R gross price geometry** from entry using the stop distance.
- Hard exit: **15:15 IST** if neither threshold resolves earlier.
- Same-bar TP+SL or entry+exit ambiguity remains `AMBIGUOUS` under the strict replay engine.

This benchmark is fixed for comparison only; it is not an incumbent production strategy.

## Challenger — CONFIRMED_GAP_DIRECTION

Same decision timestamp, entry mechanics, stop, target and hard exit as the benchmark, but a candidate is allowed only if the first 45 minutes confirm the original gap direction:

### GAP_UP confirmation

At 10:00 IST:

- the final completed first-window close is **above the session open**, and
- the previous close has **not been touched or crossed** during the first 45 minutes.

Otherwise challenger action = `NO_TRADE`.

### GAP_DOWN confirmation

At 10:00 IST:

- the final completed first-window close is **below the session open**, and
- the previous close has **not been touched or crossed** during the first 45 minutes.

Otherwise challenger action = `NO_TRADE`.

## Outcome accounting

For both benchmark and challenger, record:

- TP_FIRST / SL_FIRST / NEITHER / AMBIGUOUS / NOT_ENTERED / INSUFFICIENT_DATA;
- gross R multiple;
- MAE / MFE;
- time to TP / SL;
- resident transaction costs;
- net rupee P&L using a fixed **₹100,000 notional-equivalent** for comparability, with quantity rounded down to whole shares;
- session regime known at decision time;
- gap size and direction;
- whether the opening gap filled before 10:00;
- data-quality flags.

No leverage or MTF is used.

## Success criteria — predeclared

The challenger is **not** considered review-ready until at least:

- **30 eligible future gap sessions**, and
- **20 actual challenger entries**, and
- ambiguity rate <= **10%** among entered challenger observations.

At that point it may be considered for a formal frozen Phase-5-style comparison only if all are true:

1. challenger mean net P&L per **eligible session** is greater than the benchmark;
2. challenger median net R among cleanly resolved entries is not worse than the benchmark;
3. challenger downside is not worse: median MAE does not deteriorate by more than 10% relative;
4. improvement is not confined to a single sufficiently sampled regime;
5. no unresolved severe data-quality issue materially affects the comparison.

These criteria are deliberately conservative and can yield `NEEDS_MORE_DATA` or `REJECTED`.

## Validation start boundary

Only sessions whose market open occurs **strictly after the freeze commit containing this document** may count.

Historical data through 2026-08-21 is contaminated for this hypothesis because it informed the hypothesis. It can be used for debugging mechanics only, never for validation statistics.

## Governance

- exploratory historical evidence cannot auto-promote this hypothesis;
- this document is immutable in meaning once future observations start; material rule changes require a new hypothesis ID;
- human approval remains mandatory for any runtime soft-rule adoption;
- hard safety policy is outside this experiment;
- no order placement is permitted.
