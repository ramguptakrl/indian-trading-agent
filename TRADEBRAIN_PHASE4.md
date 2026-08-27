# Trade Brain Phase 4 — Outcome Engine + Focus Instrument Lab

Status: implemented in Trade Brain v0.5.0 on the additive Trade Brain branch.

## Purpose

Phase 4 converts the audited Phase-3 replay store into falsifiable outcome evidence. It does not create an autonomous trading policy and it does not enable order execution.

The primary profile is `FOCUS_INSTRUMENT_LAB`, initially intended for deep BSE Ltd study while remaining generic enough to study another exactly identified NSE/BSE listing.

## Non-negotiable boundaries

1. **Manual/real outcomes and replay outcomes are separate.**
   - Existing `tb_trade_plan_outcomes` remains the manual/real outcome store.
   - Phase 4 writes hypothetical historical reconstruction to `tb_replay_plan_outcomes` only.
   - Replay cannot overwrite a manually supplied real outcome.

2. **No intrabar ordering guesses.**
   - A plan can only begin evaluating entry from a candle whose `ts_open >= plan evaluation time`.
   - A candle already in progress when the plan was created is excluded as an entry trigger because part of its high/low range occurred before the decision existed.
   - If the entry candle also touches TP or SL, outcome = `AMBIGUOUS`.
   - If a later candle touches both TP and SL, outcome = `AMBIGUOUS`.
   - The engine never chooses the favorable or unfavorable ordering to make a backtest look cleaner.

3. **No future candle leakage.**
   - Phase-3 `ts_close <= as_of` remains the evidence boundary.
   - An unfinished candle cannot resolve TP/SL.
   - DAY replay is additionally capped at the hard 15:15 IST exit boundary.

4. **MAE/MFE is conservative at coarse resolution.**
   - The entry candle is excluded from MAE/MFE because pre-entry extremes cannot be separated from post-entry extremes without finer data.
   - Unknown post-exit extremes in the exit candle are not added to MAE/MFE.
   - For a TP resolution, MFE is at least the target distance.
   - For an SL resolution, MAE is at least the stop distance.
   - Exact intrabar hit time is unavailable, so time-to-event uses the exit-bar open as an explicit approximation.

5. **Soft learning cannot rewrite hard policy.**
   - Cohort results, level reliability, Crash Guard counterfactuals and event-category effects are research evidence.
   - Promotion requires a later challenger/walk-forward workflow.
   - Automatic live broker execution remains OFF.

## Outcome taxonomy

- `TP_FIRST` — entry occurred on an earlier candle and a later candle touched TP without touching SL.
- `SL_FIRST` — entry occurred on an earlier candle and a later candle touched SL without touching TP.
- `NEITHER` — entry occurred but neither threshold resolved inside the allowed observation window.
- `NOT_ENTERED` — no eligible future candle touched entry.
- `AMBIGUOUS` — intrabar ordering cannot be determined from the available candle resolution.
- `INSUFFICIENT_DATA` — no eligible completed candles are available for the observation window.

Every stored replay outcome is labelled `HYPOTHETICAL_REPLAY` and records the method version.

## Focus Instrument Lab cohorts

Persisted replay outcomes can be grouped by:

- DAY vs SWING_POSITION
- Crash Guard state
- audited instrument regime
- deterministic gate action
- reward/risk band
- evaluation time-of-day bucket

Reports include sample size, entered count, resolved TP/SL count, outcome counts, TP rate among resolved TP/SL samples, ambiguity rate, median R multiple, median MAE and median MFE.

Small samples are not promoted into rules automatically.

## Audited instrument regime

Phase 4 does not call the repo's live Nifty/yfinance regime function for historical BSE Focus Lab replay.

`AUDITED_INSTRUMENT_REGIME_V1` uses only completed `1d` candles from the selected Phase-3 audited market series available by `as_of`:

- `HIGH_VOL` — current 20-session realized volatility exceeds 1.5x its historical baseline.
- `TREND_UP` — close > SMA20 > SMA50.
- `TREND_DOWN` — close < SMA20 < SMA50.
- `RANGE` — directional alignment is absent.
- `UNKNOWN` — fewer than 50 completed daily candles are available.

This is a transparent research heuristic, not an exchange fact and not a hard trading rule.

## Support / resistance reliability study

`LEVEL_REACTION_REPLAY_V1` evaluates an explicitly supplied support or resistance price.

Parameters are explicit and persisted:

- tolerance percentage around the level
- required reaction percentage
- allowed break percentage
- forward horizon in bars
- timeframe and optional `as_of`

The touch candle itself never resolves reaction-vs-break order. Resolution starts from the next candle:

- `REACTION_FIRST`
- `BREAK_FIRST`
- `AMBIGUOUS` if both thresholds occur inside the same candle
- `UNRESOLVED`

Touch windows are non-overlapping so one prolonged interaction does not become many artificial samples. Results can also be grouped by the audited instrument regime at the touch time.

This is labelled `RESEARCH_HEURISTIC_NOT_POLICY`.

## Crash Guard calibration

The Focus Lab can group hypothetical LONG outcomes by the Crash Guard state that existed on the original plan.

For `SEVERE`, it reports the counterfactual outcome of plans that the deterministic gate blocked. This allows later study of questions such as:

- how often did the severe gate avoid an SL-first path?
- how often would a blocked plan later have reached TP?
- how often was the available candle resolution ambiguous?

The report cannot relax or tighten Crash Guard by itself.

## Corporate-event category relevance

Phase-3 event price effects can be aggregated by Phase-2 corporate-event category for a chosen horizon.

Only rows with a comparable return are used for return statistics. Windows rejected because of raw-price comparability boundaries are not silently included.

Metrics include:

- events observed
- comparable events
- positive-return rate
- median return
- median absolute return
- median MAE
- median MFE

Post-announcement movement is association, not proof the filing caused the move.

## Phase 4 API

Under `/api/tradebrain`:

- `POST /outcomes/{plan_id}/replay`
- `GET /outcomes/{plan_id}/replay/{series_id}`
- `POST /outcomes/backfill`
- `GET /focus-lab/stats`
- `GET /focus-lab/{series_id}/regime`
- `GET /focus-lab/{series_id}/cohorts`
- `GET /focus-lab/{series_id}/crash-guard`
- `POST /focus-lab/{series_id}/levels`
- `GET /focus-lab/{series_id}/event-relevance`
- `GET /focus-lab/doctrine`

## What Phase 4 does not claim

- It does not prove profitability.
- It does not treat Yahoo Finance as an official exchange source.
- It does not infer intrabar order from OHLC bars.
- It does not equate historical correlation with causation.
- It does not auto-tune hard rules.
- It does not place trades.

## Next intended layer

The next phase should add a challenger/promotion framework on top of these auditable outcomes:

1. freeze train/validation/walk-forward windows;
2. define candidate parameter changes before looking at validation results;
3. compare challenger vs current policy by regime and sample size;
4. reject changes with insufficient evidence or unstable out-of-sample behavior;
5. keep hard safety constraints outside automatic promotion;
6. only after this, add verified MTF financing/broker cost modeling and paper-broker execution adapters.
