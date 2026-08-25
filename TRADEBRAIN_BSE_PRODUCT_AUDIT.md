# Trade Brain — BSE Ltd Product Conversion Audit

Canonical branch: `tradebrain/reframe-foundation`  
Control/baseline branch: `main` (original ITA; keep untouched)  
Target tradable instrument: **BSE Ltd (`NSE:BSE`, ISIN `INE118H01025`)**

## Product decision

Trade Brain is no longer a generic multi-stock Indian trading application on this branch.
It is a BSE Ltd decision-support and evidence system.

Only BSE Ltd may be a trade target. Broader Indian/global market information may remain
only when it is useful context for a BSE Ltd decision.

The user-facing question is:

> What is the current BSE Ltd posture for INTRADAY and SWING, at what entry, stop and
> primary target, under what evidence/risk conditions, and why?

Trade Brain remains advisory-only. No broker order endpoint is permitted.

## Canonical BSE output contract

Every actionable research candidate must expose explicit structured geometry rather than
only a generic BUY/SELL label:

- instrument: BSE Ltd / `NSE:BSE`
- India market date and evaluation timestamp in IST
- trade mode: `INTRADAY` or `SWING`
- direction: `LONG` or `SHORT` (SWING remains LONG-only)
- final status: candidate / wait / blocked / exit
- entry price (or future explicitly modeled entry zone)
- stop-loss
- primary take-profit
- gross reward/risk
- net-of-modeled-cost scenario when quantity is known
- evidence/provenance and blocking reasons
- data freshness/source
- advisory-only / no-order-authorization markers

Do not display a second target until a tested deterministic T2 model exists. The current
backend contract contains one `take_profit`, so the UI must call it **Primary Target**.

## KEEP — canonical Trade Brain core

The following areas are part of the BSE product and should remain, subject to normal
refactoring/deduplication:

### Evidence, identity and market data
- `backend/tradebrain/identity.py`
- `backend/tradebrain/security_master.py`
- `backend/tradebrain/security_store.py`
- `backend/tradebrain/provenance.py`
- `backend/tradebrain/corporate_events.py`
- `backend/tradebrain/corporate_event_store.py`
- `backend/tradebrain/documents.py`
- `backend/tradebrain/market_data.py`
- `backend/tradebrain/market_data_store.py`
- `backend/tradebrain/market_source_policy.py`
- `backend/tradebrain/kite_data.py`
- `backend/tradebrain/kite_history_range.py`
- `backend/tradebrain/kite_stream.py`

### Research validation and learning
- `backend/tradebrain/replay.py`
- `backend/tradebrain/evidence_baseline.py`
- `backend/tradebrain/exploratory_studies.py`
- `backend/tradebrain/focus_lab.py`
- `backend/tradebrain/focus_lab_store.py`
- `backend/tradebrain/challenger.py`
- `backend/tradebrain/challenger_store.py`
- `backend/tradebrain/prospective_gap.py`
- `backend/tradebrain/soft_evidence.py`
- `backend/tradebrain/soft_runtime.py`
- `backend/tradebrain/study_cycle.py`
- sanitized TXT audit/learning files

### Decision/safety/accounting
- `backend/tradebrain/policy.py`
- `backend/tradebrain/advisory_pipeline.py`
- `backend/tradebrain/advisory_store.py`
- `backend/tradebrain/exchange_calendar.py`
- `backend/tradebrain/regime_hardening.py`
- `backend/tradebrain/schedule.py`
- `backend/tradebrain/trade_modes.py`
- `backend/tradebrain/equity_costs.py`
- `backend/tradebrain/paper_ledger.py`
- `backend/tradebrain/actual_trade_journal.py`
- `backend/tradebrain/llm_failover.py`

### Required operational surfaces
- Windows launcher / Kite auth helpers
- Settings for local Gemini/Groq credentials
- Actual Trades journal
- audited BSE chart/history
- BSE analysis result/details

## CONVERT — useful capability, wrong generic product framing

These capabilities should survive only after becoming BSE-centric:

### Multi-agent analysis
Current generic ticker selection becomes fixed BSE Ltd analysis. The analyst graph remains
useful as a research input, but its prompts/tools must focus on BSE Ltd and treat broader
market data as context rather than independent recommendations.

### Dashboard / market context
Keep relevant macro/context signals such as:
- NIFTY / broad market direction
- BANK NIFTY / financial-market context where empirically useful
- India VIX / volatility regime
- market breadth/liquidity context
- FII/DII only as contextual evidence, not a direct BSE trade trigger without evidence
- exchange/regulatory/company-specific news
- BSE corporate actions/results/events
- relevant global risk cues

The dashboard must become **BSE Today**, not a general market discovery page.

### Performance / insights / calibration
Merge overlapping generic validation screens into a BSE evidence workspace built around the
canonical replay, prospective evidence, challenger and actual-trade data. Legacy metrics may
be retained only when their methodology is compatible and clearly labeled.

### News
Filter/rank toward BSE Ltd, Indian capital markets/exchange structure, regulation, market
activity and other evidence shown to matter for BSE. Generic RSS browsing is secondary.

## REMOVE FROM PRODUCT SURFACE — generic ITA concepts

These should disappear from normal Trade Brain navigation immediately. Physical code deletion
comes only after imports/tests prove they are dead:

- Top Picks / generic multi-stock recommender
- generic market scanner as a trade-finding tool
- generic watchlist
- generic stock/ticker search for Deep Analysis
- generic strategy catalog as independent tradable-stock strategies
- generic sector heatmap as a discovery surface
- generic AI multi-stock backtest UI
- generic multi-stock simulation UI
- legacy signal-performance UI when superseded by audited BSE evidence
- legacy verdict-calibration UI when superseded by audited BSE evidence
- shadow-trade UI unless its counterfactual method is explicitly migrated into BSE evidence
- memory-admin as a day-to-day trading navigation item

## Candidate physical deletion after dependency audit

The following legacy modules are candidates for removal or isolation after the BSE routes no
longer import them. Do not delete them merely by filename; prove no canonical BSE dependency
first:

- `backend/backtest_engine.py`
- `backend/recommender.py`
- `backend/scanner.py`
- `backend/stock_list.py`
- generic `backend/simulation.py`
- generic `backend/shadow_trades.py`
- generic `backend/signal_performance.py`
- generic `backend/verdict_calibration.py`
- generic `backend/confidence_calibration.py`
- generic watchlist/recommender/scanner/backtest/simulation routers
- corresponding generic frontend routes/components
- optional unused data-vendor/provider adapters after import/dependency audit

## Target frontend information architecture

### 1. BSE Today
The first screen should answer the decision question without asking for a ticker.

Top block:
- BSE Ltd live/last price and source/freshness
- market/session state in IST
- explicit data state: LIVE / STALE / CLOSED / FALLBACK

Decision block — two clearly separate cards:

**INTRADAY**
- LONG / SHORT / WAIT / BLOCKED
- Entry
- Stop
- Primary Target
- R:R
- session cutoff/validity
- key evidence and blockers

**SWING**
- LONG / WAIT / BLOCKED / EXIT
- Entry
- Stop
- Primary Target
- R:R
- event/corporate-risk context
- key evidence and blockers

If no valid geometry exists, show `WAIT / NO VALID LEVELS` rather than inventing prices.

### 2. BSE Analysis
- BSE fixed; no ticker search
- Analysis Date is India/IST date
- multi-agent research visible as supporting detail
- structured BSE decision card is primary output
- Gemini primary with Groq retryable-failure fallback

### 3. BSE Price & Structure
- audited Kite candles/history
- support/resistance/volume/gap/regime evidence
- source + timestamp + comparable-price-era treatment

### 4. BSE Context
- broader market/regulatory/news inputs that may support or weaken a BSE decision
- every item explicitly labeled as context, not a trade target

### 5. BSE Evidence
- replay/backtest outcomes
- prospective frozen hypotheses
- challenger evidence
- calibration only where methodology is valid
- after-market study status
- actual-vs-advisory outcome summaries

### 6. Actual Trades
Manual record of trades the human actually executed externally.

### 7. Settings
Local provider credentials, operating timezone display preference and non-secret configuration.

## Code-deletion rule

Use three stages:

1. **Hide / disconnect** generic ITA product surfaces from BSE runtime/navigation.
2. Run Foundation + Windows + Security + BSE regression tests.
3. Delete proven-dead files and run the full suite again.

This avoids breaking useful inherited utilities while still producing a genuinely BSE-only
application.

## Original ITA comparison after Trade Brain completion

The original ITA baseline remains frozen on `main`. Do not back-port Trade Brain logic into
that branch before the benchmark.

A fair comparison should use the same BSE dates and information cutoffs and should prevent
look-ahead leakage. Suggested measures:

- analysis completion/failure rate
- structured-level completeness (mode/entry/SL/target)
- directional/outcome accuracy under one harmonized scoring rule
- net-of-cost result under identical execution assumptions where simulation is valid
- max drawdown / adverse excursion
- abstention quality (`WAIT` when evidence is weak)
- data provenance/look-ahead violations
- hard-rule/session violations
- latency
- LLM calls/tokens/cost
- provider-quota resilience

Do not compare a raw ITA BUY/SELL string to a Trade Brain advisory as if they were equivalent.
Both systems need a frozen evaluation adapter and identical outcome definitions.

## Immediate conversion sequence

1. Add a central BSE-only scope contract and reject non-BSE analysis requests.
2. Remove ticker selection from BSE Analysis.
3. Surface mode/direction/Entry/SL/Primary Target/R:R in the main decision card.
4. Replace the generic sidebar with BSE Today / Analysis / Price & Structure / Context /
   Evidence / Actual Trades / Settings.
5. Convert dashboard from market-discovery to BSE Today.
6. Consolidate validation/evidence pages.
7. Disconnect generic backend routers.
8. Prove dead code, then delete it.
9. Update canonical project docs and freeze a BSE v1 benchmark candidate.
10. Run the controlled BSE Trade Brain vs original ITA benchmark.
