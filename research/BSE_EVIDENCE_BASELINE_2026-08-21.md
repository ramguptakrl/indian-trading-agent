# BSE Ltd Evidence Baseline — 2026-08-21

Status: **EXPLORATORY / DESCRIPTIVE — NOT STRATEGY VALIDATION**

Trade Brain version: `0.11.1`  
Evidence method: `BSE_DESCRIPTIVE_EVIDENCE_BASELINE_V1`  
Opening-gap method: `BSE_OPENING_GAP_EXPLORATION_V1`  
Instrument identity: `NSE:BSE` / ISIN `INE118H01025`  
Market-data source: `YAHOO_FINANCE_VIA_YFINANCE` / `BSE.NS`  
Source official: **false**  
Price mode: `RAW_UNADJUSTED`

This note freezes the first research baseline after the framework build. It does **not** claim a profitable edge, win rate, trade authorization, or execution permission.

## Audited coverage

Latest evidence run: GitHub Actions `#222` (`32528764144`).

- Daily: **2,361** completed bars, 2017-02-03 through 2026-08-20.
- 1-hour: **3,280** bars from the vendor's rolling intraday window.
- 5-minute: **2,847** bars, 2026-06-29 through 2026-08-20.
- Recent 5-minute sessions seen: **39**.
- Strict full regular 09:15–15:30 sessions: **25**.
- Incomplete/special/vendor-short sessions: **14**; these are not silently filled.
- Raw-price comparability eras: **3**.
- Cross-era daily return/gap transitions excluded: **2**.
- Vendor corporate-action observations in full daily pull: **15**.
- Current unresolved quality flags in combined baseline: **5** (`NON_NUMERIC_OHLC`: 1 ERROR; `INTRADAY_GAP`: 4 WARNING).

Evidence report SHA-256:

`ce75a7614a5f247b1951f19a566b5844f9c9886d2d83e8fc0338b8e6d9f4078c`

Daily source snapshot SHA-256:

`6d5d8b958807ccfaab64e45dd191eff1c1918557bedb49417b60b8e0c8d530a8`

1-hour source snapshot SHA-256:

`b1d8ccd4d8738589629ef3a7244d66ea80a3644c3de5288a28f84c403d83b434`

5-minute source snapshot SHA-256:

`3456062a66dc1b639ee6ab9c44912d1548cefb3c0ec26460881b4ed944991108`

Workflow evidence artifact ZIP SHA-256:

`e990c877513b52b0caccbe02797b204d1a136a8132143d6c2c75cb9c6cfd09d6`

## Long-history daily behavior

Across comparable daily observations:

- Median close-to-close return: **-0.060695%**.
- Median opening gap: **+0.277452%**.
- Median absolute opening gap: **0.440284%**.
- 75th percentile absolute opening gap: **0.802189%**.
- 90th percentile absolute opening gap: **1.410213%**.
- Median open-to-close return: **-0.342143%**.
- Positive open-to-close sessions: **40.576%**.
- Negative open-to-close sessions: **59.085%**.
- Median session range: **2.758199% of open**.
- 90th percentile session range: **6.161973% of open**.
- Median true range: **2.858793% of previous close**.

These are unconditional descriptive statistics, not a trading rule.

## Recent 5-minute descriptive behavior

Only **25 strict full regular sessions** are available in the current 55-day 5-minute vendor window, so the baseline is descriptive-ready but deliberately **not yet marked walk-forward intraday-ready**; the configured readiness threshold is 30 full sessions.

For those 25 full sessions:

- Median session open-to-close return: **-0.541112%**.
- Median session range: **2.483917% of open**.
- Median long MFE from session open: **0.677653%**.
- Median long MAE from session open: **1.029151%**.

Recent time-of-day 5-minute median bar ranges:

- 09:15–10:00: **0.393022%**.
- 10:00–12:00: **0.207892%**.
- 12:00–14:00: **0.167392%**.
- 14:00–15:15: **0.165879%**.
- 15:15–15:30: **0.167881%**.

The opening period is therefore materially more volatile in this recent sample, but no entry rule is inferred from that observation.

## Regime at evidence cutoff

Classifier: `AUDITED_INSTRUMENT_REGIME_V2_RECENT_WINDOW`

- Regime: **TREND_DOWN**.
- Close: **₹3,291.1001**.
- SMA20: **₹3,492.145**.
- SMA50: **₹3,702.324**.
- 20-session annualized volatility: **31.5294%**.
- Volatility baseline: **36.1826%**.
- Reason: `close < SMA20 < SMA50`.

## Opening-gap exploration

This study uses the already-visible full daily history, so it is **hypothesis generation only**.

### Absolute gap >= 0.5%

- GAP_UP: N=791, fill anytime **64.096%**, close reversal **58.281%**, close continuation **41.719%**.
- GAP_DOWN: N=243, fill anytime **58.436%**, close reversal **54.321%**, close continuation **45.267%**.

### Absolute gap >= 1.0%

- GAP_UP: N=277, fill anytime **45.848%**, close reversal **55.596%**, close continuation **44.404%**.
- GAP_DOWN: N=129, fill anytime **46.512%**, close reversal **55.039%**, close continuation **44.961%**.

### Absolute gap >= 1.5%

- GAP_UP: N=132, fill anytime **34.091%**, close reversal **55.303%**, close continuation **44.697%**.
- GAP_DOWN: N=81, fill anytime **43.210%**, close reversal **61.728%**, close continuation **38.272%**.

## Why we are not turning that into a gap-fade rule

The yearly cohorts are visibly non-stationary. For example, >=1.0% GAP_UP close-continuation was **50.0% in 2024**, **47.059% in 2025**, but **73.913% in 2026** through the evidence cutoff (N=23 in 2026). At >=1.5%, 2026 GAP_UP continuation was **83.333%** on only N=12.

So the full-history aggregate can easily hide regime/time variation. Using the same sample to discover a threshold and then calling its historical frequency a validated edge would be data snooping.

## Research conclusion

The first evidence pack supports three conservative conclusions:

1. BSE Ltd has enough daily history for serious chronological research and swing studies.
2. Recent 5-minute data confirms the opening hour carries substantially larger bar ranges than later periods, but the strict full-session sample is still below the 30-session walk-forward readiness threshold.
3. Opening-gap behavior is not stable enough across years to justify a blind fixed gap-fade or gap-continuation rule from this exploratory sample alone.

## Next evidence protocol

The next hypothesis must be frozen **after** this evidence timestamp and evaluated only on future/untouched observations. The preferred first hypothesis is not "gap up means buy" or "gap up means fade". It is whether **first-hour confirmation improves a fixed gap-direction benchmark after resident transaction costs**.

No historical record in this note is eligible for direct Phase-5 promotion.

Execution boundary remains:

- `advisory_only=true`
- `trade_authorization=false`
- `order_execution_allowed=false`
