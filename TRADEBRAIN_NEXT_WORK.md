# Trade Brain — Next Work

Updated: 2026-08-26

This is the active short-list for work remaining on the BSE Ltd Trade Brain branch. It is intentionally separate from historical project-state notes.

## Production analysis intelligence

- [ ] Replace normal-user Shallow / Medium / Deep selection with one canonical **Analyze INTRADAY + SWING** production flow.
- [ ] Add an internal adaptive reasoning-depth controller: clear evidence uses normal reasoning; conflicting/unusual/major-event evidence escalates to deeper challenge; unresolved evidence stays WAIT / NO TRADE.
- [ ] Move explicit 1/2/3-round depth comparison into a Developer / Validation Lab rather than the normal trading UI.
- [ ] Benchmark 1 vs 2 vs 3 debate rounds on chronological BSE evidence before selecting the production default.
- [ ] Build the planned BSE-specific optimizer that measures which indicators, indicator combinations, timeframes, regimes and setups actually add predictive value for INTRADAY LONG, INTRADAY SHORT and SWING · MTF LONG.
- [ ] Keep hard rules deterministic; learned indicator/model weighting may never override BSE scope, session, provenance, broker/funding, market-halt or safety gates.

## AI provider reliability / cost safety

- [x] Select a paid-capacity development path while Groq Developer upgrades are unavailable: **OpenAI paid API**.
- [x] Configure recommended OpenAI model choices in code/settings: **gpt-5.6-luna quick** + **gpt-5.6-terra deep**.
- [x] Add retryable-capacity failover from OpenAI primary to configured **Gemini 3.6 Flash**.
- [x] Allow Gemini to remain the independent material verifier when OpenAI is primary.
- [x] Preserve shared analyst checkpoints so completed Market / News / Fundamentals work is not rerun solely because a later provider call fails.
- [x] Read actual Groq provider rate-limit/remaining/reset metadata where available instead of relying only on hard-coded free-tier assumptions.
- [ ] Locally save and test the newly-created OpenAI API key through **Settings > Models & Keys**; never commit the key.
- [ ] Set OpenAI as the local default after the key test passes; retain Gemini and Groq as configured alternates where available.
- [ ] Finish/validate generous runaway API circuit breakers that allow normal Deep runs but stop accidental graph/provider loops before abnormal spend.
- [ ] Record actual per-run calls, input/output tokens, provider/model and estimated cost for development comparison.

## UI / user experience

- [x] Simplify the BSE Analysis page so Shared Evidence, INTRADAY and SWING · MTF are immediately readable.
- [x] Collapse raw agent reasoning/diagnostics instead of showing every report/debate by default.
- [x] Separate INTRADAY and SWING rows in Analysis Outcomes/History.
- [x] Clean stale inherited API-cost/provider guidance from Settings.
- [ ] Remove normal-user reasoning-depth selection after adaptive depth is implemented.

## Validation

- [ ] Pull the current branch into `D:\TradeBrain-Current` and confirm the refreshed Settings UI locally.
- [ ] Save/test OpenAI key locally and confirm `gpt-5.6-luna` + `gpt-5.6-terra` are selected.
- [ ] Prove Shallow/normal production analysis end-to-end on Windows using OpenAI primary.
- [ ] Prove OpenAI -> Gemini capacity failover with a controlled test; do not intentionally burn quota.
- [ ] Prove full Deep validation analysis end-to-end without provider-limit failure.
- [ ] Compare decisions and token/cost usage across reasoning depths; do not expose multiple competing live verdicts to the normal user.
- [ ] Continue prospective BSE evidence collection and leakage-safe historical/walk-forward testing.

## Product invariants

- BSE Ltd / NSE:BSE remains the only trade target.
- INTRADAY = LONG/SHORT, same-session only.
- SWING = LONG only, Zerodha MTF-funded only.
- Kite remains market-data-only; no broker order mutation route is enabled.
- AI cannot override deterministic scope, session, provenance, broker/funding, halt or safety gates.
- All Trade Brain analysis remains advisory-only with broker order execution OFF.
