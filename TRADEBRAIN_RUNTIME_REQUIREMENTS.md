# Trade Brain — BSE Ltd Runtime Requirements

Status date: 2026-08-25  
Canonical branch: `tradebrain/reframe-foundation`  
Trade target: BSE Ltd (`NSE:BSE`)

## Operating clock

- `Asia/Kolkata` is authoritative for market/session rules.
- PRE_MARKET_RESEARCH, LIVE_MARKET_RESEARCH, LIVE_MARKET_RISK_ONLY,
  POST_MARKET_STUDY and STUDY_REPLAY remain valid operating states.
- Calendar/session state must be exchange-aware and fail closed when unverified.

## Live data

- Kite WebSocket is preferred when authenticated/configured.
- REST quote/history is supplemental and rate-governed.
- Yahoo/yfinance remains explicitly labelled fallback/research data only where permitted.
- LLM analysis is event/material-change driven, not triggered on every tick.
- Position Guardian requires a timestamped, fresh persisted Kite BSE quote before it may
  interpret stop/target/HOLD risk. Missing, malformed or stale quote state fails closed.

## Technical/research stack

Core hierarchy:

- 1D dominant trend/regime;
- 4H structure derived deterministically from completed lower-timeframe bars;
- 1H setup;
- 15m entry refinement.

Gap, volume, support/resistance, FVG, Fibonacci, candlestick and other concepts are
research features until they pass chronological validation.

## INTRADAY doctrine

- LONG or SHORT cash equity.
- Same session only.
- No fresh entry from 15:10 IST.
- Intended flat by 15:15 IST.
- No overnight cash-equity short.
- Conversion or pyramiding cannot be invented from confidence language.

## SWING / MTF doctrine — owner decision 2026-08-25

- SWING is LONG-only and multi-day.
- Active SWING funding is **Zerodha MTF only**.
- MTF is not a third trade mode.
- Historical `CNC_OWN_CASH` labels may remain readable for audit/replay, but must not
  grant active SWING permission.
- Current broker/security MTF eligibility must be verified at decision time.
- A positive funded amount is required.
- Net economics must combine resident equity transaction costs with the versioned MTF
  incremental profile.
- A positive interest-days/holding scenario is required before a fully costed SWING
  candidate can PASS; software must not invent the holding period.
- MTF-to-CNC conversion review is a separate manual/broker rule check and does not turn
  CNC into an active SWING funding path.
- No MTF modeling creates broker execution permission.

## Market / abnormal-event guards

Priority:

`SCOPE > HALT > PRICE RANGE > DATA QUALITY/FREAK TICK > OPEN-POSITION RISK > BROKER/FUNDING RULES > TECHNICAL SETUP > LLM OPINION`

Missing ticks alone are not proof of a halt. Unknown critical market state blocks new
advice rather than being guessed. Direct live-advisory callers are BSE/NSE scope-checked
before market/policy evaluation.

## Corporate-action rules

- Official events remain permanent evidence even after inbox review/archive.
- Explicit split/dividend dates and terms may be normalized from source text.
- Record date, ex-date, payment date, split ratio and dividend amount are never invented.
- An ex-date is never inferred from a record date.
- Stock splits create raw-price comparability boundaries without rewriting stored OHLC.
- Dividend ex-dates create economic review context, not split-style structural price eras.

## Learning

Every new concept:

1. define without look-ahead;
2. calculate from audited completed data;
3. study descriptively;
4. freeze hypothesis/windows;
5. evaluate after realistic INTRADAY or SWING+MTF costs;
6. compare with incumbent;
7. require human approval;
8. preserve lineage.

## Actual trades

Human-executed trades remain separate evidence from replay/paper research.

Active SWING journal records are explicitly MTF-aware:

- LONG only;
- MTF eligibility verification recorded;
- funded amount and user cash contribution retained separately;
- explicit MTF interest-days used for estimates;
- partial exit slices allocate modeled MTF costs proportionally;
- broker-confirmed actual charge override may replace estimates for closed slices.

The journal records what the human did externally; it never places broker orders.

## LLM roles

- Groq primary research/synthesis when configured.
- Gemini material-finding verifier/challenger when configured.
- Provider failover handles retryable capacity/quota states.
- LLM disagreement never creates order authorization.

## Execution boundary

Kite remains `MARKET_DATA_ONLY`. No place/modify/cancel order methods.
All final results retain:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```
