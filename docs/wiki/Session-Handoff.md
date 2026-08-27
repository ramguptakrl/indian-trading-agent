# Session Handoff — Latest Resume Point

> This page is the first page to read when a chat/session is becoming slow or a new chat is opened. It records the exact resume point, timestamps, claim boundaries, and next action.

## Handoff timestamp

- **Toronto / Eastern Time:** 2026-08-26 21:26:54 EDT (UTC-04:00)
- **India Standard Time:** 2026-08-27 06:56:54 IST (UTC+05:30)
- **UTC:** 2026-08-27 01:26:54 UTC

## Repository anchor

- Repository: `ramguptakrl/indian-trading-agent`
- Active branch: `tradebrain/reframe-foundation`
- Branch head at the start of this handoff capture: `23a1ba16d21dac5dbb5d0aab530e850e543f9469`
- Latest research-code commit before Wiki-only handoff/documentation commits: `a33c6769e0e7fb664f0337e65260004c71414282`
- Last fully certified statistical-governance boundary: `5700f2e8282583ef7f9acb87a5641a4ccf23d379`
- PR #1: remains open/unmerged. Do not merge unless explicitly requested.

## Immutable checkpoint for this handoff

- **Checkpoint branch:** `checkpoint/tradebrain-handoff-2026-08-26-2127-et`
- **Checkpoint SHA:** `e340d983db0a40f8c8990cbb8558c3f748423423`
- **Checkpoint timestamp — Toronto:** 2026-08-26 21:26:54 EDT
- **Checkpoint timestamp — IST:** 2026-08-27 06:56:54 IST
- **Checkpoint timestamp — UTC:** 2026-08-27 01:26:54 UTC
- **Purpose:** preserve the current ML research/governance implementation together with the timestamped cross-chat Wiki handoff system before exact-head certification of the newest research modules.
- **Immutability:** do not repoint this checkpoint branch. Create a new timestamped checkpoint instead.

The active working branch continues to move after this checkpoint because the Wiki pages record the checkpoint itself. That is expected; the checkpoint SHA above remains the recovery anchor.

## ML state at handoff

There is **no approved champion**.

Historical real-data findings already established:

- `BSE_INTRADAY_LONG`: rejected under hardened evidence. Compact + weighted challenger improved validation but failed OOS; only 23 OOS trades and 2×-friction expectancy became negative with PF below 1.
- `BSE_INTRADAY_SHORT`: rejected; no robust candidate after the compact/weighted challenger experiment.
- `BSE_SWING_LONG_MTF`: rejected for promotion. Earlier superficial OOS pass was invalidated by stronger gates: ~62.8% drawdown, weak 2× friction edge, negative regime evidence, and only 1/15 CPCV folds passing.
- The 2026 historical holdout has already been opened once and is therefore **consumed**. It must not be described as untouched or used to choose/tune new A/B/C/D/E challenger architectures.
- Future prospective sessions are the cleanest new evidence.

## Certified statistical-governance core

The last certified boundary includes:

- persistent research ledger;
- DSR multiple-testing correction;
- PBO based on a fixed candidate set across purged folds;
- CPCV / purge / embargo diagnostics;
- stationary-bootstrap confidence intervals;
- hardened OOS promotion thresholds;
- PSI distribution baseline + active drift contribution;
- Brier/performance drift monitoring;
- model registry fail-closed evidence requirements;
- 30-session same-artifact shadow buffer before integration eligibility;
- no automatic champion promotion;
- advisory only, no broker execution authority.

## Implemented after the last certified boundary — certification pending

These exist in code but the newest combined exact head must pass CI before they are called green:

1. Per-hypothesis-family research kill budget / MinTRL governance.
2. Predeclared 15-May-2023 structural-break challenger:
   - full-history control;
   - pre-break down-weighted;
   - post-break-only.
3. Meta-labeling primary-signal families:
   - trend/momentum;
   - mean reversion;
   - volatility breakout.
4. Causal tabular sequence/context challenger:
   - lagged 1/3/5 state;
   - Garman–Klass volatility;
   - Parkinson volatility;
   - close-location value;
   - ATR-normalized VWAP distance;
   - range/ATR and relative-volume interactions;
   - 5/10/20-bar directional efficiency.
5. GitHub Wiki durable-memory synchronization.

## No-cheating boundary

At historical decision time `T`, Trade Brain may use only evidence genuinely available by `T`.

Forbidden:

- future candle values;
- unresolved labels;
- later news;
- future market-context candles;
- holdout information for feature/hypothesis selection;
- synthetic validation/OOS data;
- researcher selection based on repeatedly peeking at the same OOS block.

News remains OFF in the first historical replay baseline unless point-in-time publication/availability provenance can be proven.

## Exact next action

**NEXT:** certify the newest combined research head with the full relevant CI/test suite.

Then, in order:

1. Fix any exact-head CI failures before adding more research ideas.
2. Wire the kill-criteria/DSR family status back into the after-market supervisor artifacts so closed families cannot be parameter-mined again automatically.
3. Implement the honest `1m`-derived Volume / Rupee Activity Bar challenger, explicitly without claiming intra-minute trade sequence or Level-2 information.
4. Run structural-break, meta-label, sequence/context, and activity-bar challengers under the locked research ledger / DSR / PBO / CPCV / bootstrap / friction rules.
5. Do **not** use the consumed 2026 historical holdout to choose among those new architectures.
6. Any surviving model enters prospective shadow evidence; no model is promoted merely because a historical backtest is attractive.

## Project-wide work still outside the ML research core

Before the whole application is called production-ready, important non-ML items still include paid-LLM runaway/billing guard integration, remaining generic multi-stock escape paths/memories/prompts, news provenance hardening, stale docs/config mismatches, and scheduled dependency-refresh mutation risk.

## Resume protocol for the next chat

Before doing substantial work:

1. Read `Home`.
2. Read `Current-Status`.
3. Read this `Session-Handoff` page.
4. Read `Roadmap-and-Next-Steps`.
5. Re-fetch the active branch HEAD and compare it with the anchors above.
6. Check exact-head CI before making any new green/certified claim.
7. Continue from **Exact next action**, not from chat memory.

If code or Wiki status has moved since this timestamp, update this page with a new timestamp rather than silently replacing the historical meaning of the previous checkpoint.
