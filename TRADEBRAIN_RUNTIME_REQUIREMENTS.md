# Trade Brain — BSE Ltd Runtime Requirements & Gap Contract

Status date: 2026-08-25
Canonical branch: `tradebrain/reframe-foundation`
Trade target: BSE Ltd (`NSE:BSE`)

This document freezes the current runtime requirements and records what is already implemented versus what still requires engineering. It is a build contract, not a claim that every item is complete.

## 1. Time and operating mode

- India market time (`Asia/Kolkata`) is the authoritative/default trading clock.
- The UI must also show host/user-local time independently.
- Market-calendar/session logic must use IST and verified exchange-calendar state, never host time.
- Operating modes remain PRE_MARKET_RESEARCH, LIVE_MARKET_RESEARCH, LIVE_MARKET_RISK_ONLY, POST_MARKET_STUDY and STUDY_REPLAY.
- Current status: IMPLEMENTED.

## 2. Open-market data utilization

- Zerodha Kite WebSocket is the preferred continuous live-price plane when configured.
- REST quote/history calls are supplemental; do not poll REST aggressively when WebSocket data is fresh.
- Add one central read-only API governor for endpoint-specific rate limits, 429 handling, backoff/jitter, retry budget, stale-data flags and provider health.
- Use material-change/event-driven recomputation so every tick can update state without producing UI/LLM noise.
- LLM analysis must not be triggered on every tick. Re-run only when a meaningful state boundary changes (setup validity, level breach, volatility/regime change, important event/news, scheduled checkpoint, or explicit user request).
- Current status: PARTIAL. WebSocket and conservative historical chunk pacing exist; a central governor/noise-control plane is still required.

## 3. Closed-market study

- After market, refresh audited BSE history, replay existing plans, update frozen prospective hypotheses, run exploratory studies and preserve sanitized audit output.
- New strategies/indicators/patterns enter research first; they cannot become live rules merely because an in-sample backtest looks good.
- Historical news/sentiment may be used only when timestamped information actually available at the historical cutoff is preserved. Current RSS/yfinance live aggregation must not be retroactively treated as historical sentiment.
- Official exchange corporate-event artifacts already support timestamped historical evidence and should be preferred where applicable.
- Current status: PARTIAL. Study cycle exists but launcher does not yet schedule/run it automatically, and generic news is not yet a durable historical point-in-time archive.

## 4. Canonical multi-timeframe technical stack

Required research hierarchy:

- `1D`: dominant trend/regime and major structure.
- `4H`: key levels / supply-demand structure. Build only from completed 60-minute bars using deterministic aggregation because Kite does not provide a native 4H interval.
- `1H`: setup qualification.
- `15m`: entry refinement and invalidation.
- Lower timeframes may be studied later only if BSE evidence demonstrates incremental value.

Current indicator set includes EMA/SMA, MACD, RSI, Bollinger, ATR, VWMA and MFI. The current TradingAgents indicator adapter calculates these mainly from daily data, so the full D→4H→1H→15m hierarchy is NOT yet implemented.

Research candidates such as FVG, volume profile, Fibonacci, candlestick patterns, gap behavior, support/resistance reactions and related structures must be implemented first as versioned exploratory features. Each must pass chronological validation/walk-forward gates before becoming a live weighting/rule. Do not enable everything simultaneously.

Current status: PARTIAL / MAJOR GAP.

## 5. External research/reference sources

- External sites may be used as research/reference sources only when terms/licensing/access permit and provenance is recorded.
- Prefer official NSE/BSE filings/data for factual exchange/company events.
- Screener-type fundamental/reference sources can be evaluated as secondary research input, not silently substituted for audited price truth.
- Web/reference research may propose hypotheses; it cannot directly mutate production rules.

## 6. Actual-trade lifecycle

- Human can report a real BSE trade; software stores it separately from hypothetical replay.
- Once OPEN, it remains tracked until fully CLOSED; partial closes preserve remaining quantity.
- Live marking should use current market data and estimated/actual charges.
- Add a dedicated open-position risk watcher that combines price/structure, market correction/crash state, relevant news/corporate events, time cutoffs and plan invalidation.
- Risk watcher output is advisory only, e.g. `HOLD`, `REVIEW_TIGHTEN`, `EARLY_EXIT_REVIEW`, `HARD_EXIT_REQUIRED_BY_INTRADAY_POLICY`; it never sends a broker order.
- Current status: PARTIAL. Journal/current marking exist; proactive news/event/regime early-exit watcher is missing.

## 7. Market corrections / crash awareness

- Existing regime classification and Severe Crash Guard remain safety inputs.
- Add live/broader-market correction monitoring and connect it to both new-entry gating and OPEN-trade risk review.
- A crash signal may block/reduce LONG conviction but does not automatically create an intraday SHORT.
- Current status: PARTIAL.

## 8. Intraday doctrine

- INTRADAY may be LONG or SHORT cash equity.
- Fresh entries stop at the Trade Brain safety boundary (currently 15:10 IST); intraday exposure is intended flat by the stricter Trade Brain hard-exit boundary (currently 15:15 IST), even if broker RMS acts later.
- SHORT is intraday-exit-only. Never carry an uncovered cash-equity short overnight and never convert it into CNC merely to avoid a loss.
- A LONG intraday position may be reviewed for conversion to CNC only when the user explicitly has sufficient holdings/funds and broker rules allow the conversion. Conversion is a risk/funding decision, not an automatic loss-avoidance mechanism.
- Multiple entries are permitted only under an explicitly validated pyramiding/add-on policy with a total risk cap; confidence language alone is insufficient.
- Current status: same-day LONG/SHORT hard timing exists; conversion/add-on policy is NOT yet modeled.

## 9. Swing / MTF doctrine — revised 2026-08-25

- SWING is LONG-only.
- Funding is a separate dimension from trade mode: a SWING LONG may be `CNC_OWN_CASH` or `MTF` depending on available capital, eligibility and economics.
- Do not model MTF as mandatory if full cash is available; do not model CNC as available when capital is insufficient.
- MTF requires broker eligibility, approved security and account prerequisites to be verified at decision time.
- MTF-to-CNC conversion must obey current broker rules. At Zerodha, same-day MTF→CNC conversion is not allowed; conversion is available from T+1 onward with sufficient funds. Requests before 4 PM are processed that day, subject to broker restrictions/events.
- MTF costs require a NEW versioned economics profile including funded amount, daily interest, MTF brokerage, pledge/unpledge and RMS-square-off risks. Do not rewrite historical own-cash cost records.
- Current status: NOT IMPLEMENTED. Current runtime explicitly has MTF disabled and own-cash-only swing economics.

## 10. Broker, regulation and fees

- Broker/exchange/regulatory restrictions are hard inputs and outrank model opinion.
- Fee/rule snapshots must be versioned with verification timestamp/source; future changes create a new version rather than silently rewriting old evidence.
- Existing resident-equity CNC/MIS cost engine is versioned. MTF requires its own new profile.
- Kite credential remains MARKET_DATA_ONLY in Trade Brain. Broker execution stays disabled unless a future explicit product decision changes that boundary.

## 11. Reward:risk learning

- Every candidate requires defensible Entry/SL/Primary Target geometry.
- R:R preference is soft/learnable and may change only through frozen chronological evidence plus explicit human-approved promotion.
- “Higher confidence” cannot by itself loosen risk, widen a stop, increase capital, or change R:R. Evidence must demonstrate the change out of sample.
- Existing soft-parameter registry already supports versioned/human-approved R:R preferences.
- Current status: IMPLEMENTED for basic R:R soft-versioning; richer mode/setup-specific R:R research remains future work.

## 12. LLM roles — revised 2026-08-25

Desired architecture:

- Groq becomes primary BSE research/synthesis provider when configured, using the approved OpenAI-compatible model available through Groq.
- Google Gemini becomes a verifier/challenger for material findings when quota is available, rather than being the default primary provider.
- Verification must compare structured evidence/claims and flag disagreement; it must not create an order authorization.
- If Google free-tier quota is exhausted, label verification unavailable and continue according to the deterministic evidence/safety boundary rather than repeatedly hammering the API.
- Provider-specific rate/quota/cooldown handling must be centralized and observable without exposing keys.
- Current status: NOT IMPLEMENTED. Runtime currently defaults Google primary and uses Groq only as a capacity fallback.

## 13. Local research memory / lineage

- Audited market data, raw source artifacts, corporate events, plans, outcomes, evidence baselines and challenger experiments remain local/persistent.
- Never destructively replace prior reasoning/method versions. New logic gets a new method/version record and links to what it supersedes.
- Preserve enough rationale/evidence/provenance to revisit an older hypothesis without storing hidden chain-of-thought.
- Current status: STRONG FOUNDATION. Existing `tb_*` SQLite stores, SHA-addressed artifacts, versioned evidence and frozen challenger definitions satisfy much of this; explicit supersedes/superseded-by lineage can be strengthened.

## 14. Promotion rule for any new technical concept

For candlestick patterns, FVG, Fibonacci, volume profile, indicator combinations, time windows or any new setup:

1. define the feature mathematically and without look-ahead;
2. calculate it from audited completed bars;
3. run descriptive/exploratory study;
4. freeze hypothesis and train/validation/walk-forward windows;
5. evaluate after realistic resident/MTF costs where applicable;
6. test incremental value versus the simpler incumbent, not just standalone win rate;
7. require human approval before live soft promotion;
8. retain the old version and evidence trail.

This prevents Trade Brain from becoming an indicator collection instead of a BSE-specific decision engine.

## 15. Exchange microstructure and abnormal-event guards — added 2026-08-25

These are mandatory live safety inputs, not optional indicators.

### 15.1 Price bands / upper-lower circuit awareness

- Trade Brain must know the exchange-applicable price band or dynamic operating range for `NSE:BSE` for the current session and must not assume a fixed 5%, 10% or 20% circuit.
- NSE states that securities on which derivative products are available do not have a normal static daily price band; a 10% dynamic/dummy operating range is used for erroneous-order protection and can be flexed by the Exchange. BSE Ltd is a derivatives-eligible underlying, so runtime must treat the current exchange range/status as dynamic data rather than a hardcoded stock circuit percentage.
- Track distance to current upper/lower permissible range and label states such as `NORMAL`, `NEAR_UPPER_RANGE`, `NEAR_LOWER_RANGE`, `AT_RANGE`, `RANGE_FLEX_PENDING/UNKNOWN` when evidence permits.
- Near a band/range, reduce confidence in market-order-style execution assumptions, model slippage/liquidity risk, and do not assume a stop can fill at its exact trigger price.
- For an OPEN position, hitting/approaching a lower range is an immediate Position Guardian risk event; hitting an upper range may affect exit liquidity and should not be treated as guaranteed realizable profit.
- Historical backtests must use the price-band/range regime that applied at that date when such data is available; otherwise explicitly mark the limitation.
- Current status: NOT IMPLEMENTED as a live guard.

### 15.2 Market-wide circuit breaker / coordinated halt awareness

- Monitor NIFTY 50 and BSE SENSEX market-wide circuit-breaker state. Current SEBI/NSE framework uses 10%, 15% and 20% moves in either direction, triggered by whichever of NIFTY 50 or SENSEX breaches first, with halt duration depending on trigger level and time of day.
- When a market-wide circuit breaker is triggered, immediately enter `MARKET_HALTED` / risk-only state: no fresh-trade advisory, freeze normal setup timers, preserve OPEN trades, and show that execution is unavailable until the official reopen/pre-open process permits trading.
- After reopening, require fresh market structure/liquidity confirmation before reactivating an old entry thesis; do not blindly continue a pre-halt signal.
- A 20% market-wide breaker means remainder-of-day halt under the current framework.
- Current status: NOT IMPLEMENTED as a live state machine.

### 15.3 Instrument/exchange halt, suspension and feed-outage distinction

- Distinguish at least: `MARKET_CLOSED`, `MARKET_WIDE_HALT`, `INSTRUMENT_SUSPENDED/HALTED`, `EXCHANGE_OUTAGE`, `DATA_FEED_STALE`, and `LOCAL_NETWORK/API_FAILURE`.
- Missing ticks alone must never be interpreted as a market halt. Confirm using exchange/session status or an independent permitted source when possible.
- If status cannot be verified, fail closed for new advisories and label the reason `MARKET_STATUS_UNVERIFIED` rather than guessing.
- Resume only after official/verified session state and fresh data are restored.
- Current status: PARTIAL for stale-data handling; full halt/outage classification is missing.

### 15.4 Freak-trade / abnormal-tick protection

- A single abnormal print must not be allowed to create a new setup, trip an early-exit recommendation, move a stop/target model, or teach the research engine without confirmation.
- Use Kite `full` WebSocket mode for BSE when practical because it includes LTP, quantities, timestamps and 5x5 market depth; these fields can support anomaly validation without REST polling.
- Build a deterministic `FREAK_TICK_SUSPECT` detector using a combination of: deviation from stable recent price, spread/depth inconsistency, abnormal jump relative to short-horizon volatility/ATR, tiny or anomalous traded quantity, timestamp/order-book consistency, and rapid snap-back/confirmation ticks.
- Thresholds must be empirically calibrated for BSE Ltd; do not hardcode a generic percentage as the definition of a freak trade.
- On suspicion, quarantine the tick from decision-state changes for a short confirmation window while retaining it in a raw audit stream. Confirm with subsequent ticks/depth and, when necessary and rate limits allow, a read-only quote check or independent permitted source.
- If confirmed genuine, release the event immediately as a real volatility/price-break event. If rejected as anomalous, preserve the evidence and exclusion reason for research audit.
- Do not rewrite historical raw market data. Store a separate quality/anomaly label so future research can revisit the decision.
- Current status: DATA SUPPORT EXISTS (Kite full-mode depth parser); detector is NOT IMPLEMENTED.

### 15.5 Opening gap-up / gap-down operationalization

- Trade Brain already has a versioned BSE opening-gap exploratory study using previous close versus session open and measuring gap fill, reversal, continuation and close-through behavior at 0.5%, 1.0% and 1.5% thresholds.
- Promote gap state into the live opening context only after a valid current-session open/price is confirmed: `GAP_UP`, `GAP_DOWN`, `FLAT/IMMATERIAL`, magnitude %, previous close, open, gap-fill level and whether the gap conflicts with the 1D/4H trend.
- A gap is context, not an automatic trade signal. Entry still requires 1H/15m setup evidence and live liquidity/market-state validation.
- Study BSE-specific behavior by gap magnitude, direction, regime, news/event presence, volume, first-15m behavior and eventual fill/continuation. Freeze any live threshold before promotion.
- Gap logic must be corporate-action/price-era aware so splits/bonuses or non-comparable price eras do not create fake gaps.
- Current status: EXPLORATORY GAP STUDY IMPLEMENTED; LIVE GAP GUARD/FEATURE NOT YET IMPLEMENTED.

### 15.6 Priority ordering

When signals conflict, exchange/microstructure safety outranks technical conviction:

`MARKET/INSTRUMENT HALT` > `PRICE-RANGE/CIRCUIT CONSTRAINT` > `DATA QUALITY / FREAK-TICK GUARD` > `OPEN-POSITION RISK` > `BROKER/REGULATORY/FUNDING RULES` > `TECHNICAL SETUP` > `LLM OPINION`.

No LLM, indicator, confidence score or historical win rate may override a verified halt, exchange constraint, invalid/stale data state or broker/regulatory hard rule.
