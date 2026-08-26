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

- [ ] Validate a paid-capacity primary provider for full Deep/validation workloads while Groq Developer upgrades are unavailable.
- [ ] Preserve shared analyst checkpoints so completed Market / News / Fundamentals work is never rerun solely because a later provider call fails.
- [ ] Keep per-analyst automatic provider failover and expose provider-specific capacity diagnostics without secrets.
- [ ] Read actual provider rate-limit/remaining/reset metadata where available instead of relying only on hard-coded free-tier assumptions.
- [ ] Add generous runaway API circuit breakers that allow normal Deep runs but stop accidental graph/provider loops before abnormal spend.
- [ ] Record actual per-run calls, input/output tokens, provider/model and estimated cost for development comparison.

## Validation

- [ ] Prove Shallow/normal production analysis end-to-end on Windows.
- [ ] Prove full Deep validation analysis end-to-end without rate-limit failure.
- [ ] Compare decisions and token/cost usage across reasoning depths; do not expose multiple competing live verdicts to the normal user.
- [ ] Continue prospective BSE evidence collection and leakage-safe historical/walk-forward testing.

All Trade Brain analysis remains advisory-only with broker order execution OFF.
