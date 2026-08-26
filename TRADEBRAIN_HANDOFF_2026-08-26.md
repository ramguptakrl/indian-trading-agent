# Trade Brain — Chat Handoff / Checkpoint

Date: **2026-08-26**
Repo: `ramguptakrl/indian-trading-agent`
Active branch: `tradebrain/reframe-foundation`
PR #1: **OPEN / DRAFT / intentionally UNMERGED**

This file records the exact continuation point after the Aug 26 UI/provider-capacity work so a new chat can resume from GitHub rather than conversation memory.

## Product boundary — do not mix projects

This is **our BSE Trade Brain / Vibe Trading software**. It is not Kronos-BSE and it is not the generic inherited ITA product.

Trade target remains only:

- BSE Ltd
- `NSE:BSE`
- ISIN `INE118H01025`

Active horizons:

- **INTRADAY** — LONG or SHORT, same-session only.
- **SWING · MTF** — LONG only, Zerodha MTF-funded only.

Always:

```text
advisory_only = true
trade_authorization = false
order_execution_allowed = false
```

Kite remains market-data-only; no place/modify/cancel order route is enabled.

## UI state reached in this session

The BSE Analysis screen was simplified so a screenshot is immediately readable:

1. Shared Evidence
2. INTRADAY
3. SWING · MTF

Raw reports, debates, task IDs and diagnostics are collapsed by default. Decision cards are compact. Analysis Outcomes/History now shows INTRADAY and SWING separately instead of two indistinguishable NO TRADE rows.

Settings was also cleaned so stale inherited Claude/GPT-4o/API-cost guidance is no longer presented as the Trade Brain recommendation.

## Provider-capacity problem discovered

A prior full analysis exhausted/ran into free-provider capacity. The screen correctly failed closed to WAIT / NO TRADE, but the session exposed unnecessary token burn and weak diagnostics.

Changes made:

- Groq completion cap reduced for concise agent outputs.
- Gemini fallback output bounded and fallback thinking reduced.
- Groq governor now reads provider limit/remaining/reset headers when available.
- Shared Market / News / Fundamentals work is checkpointed analyst-by-analyst so a later capacity failure does not rerun already-completed analyst work.
- Provider errors distinguish capacity/rate-limit classes more clearly.
- Shared-evidence failure should be shown once rather than repeated as three red errors.

## Reasoning-depth product decision

Normal users should **not** choose Shallow / Medium / Deep as three competing analysis methods.

Planned production behavior:

```text
Analyze INTRADAY + SWING
        ↓
Trade Brain decides internal reasoning depth
        ↓
clear evidence -> normal reasoning
conflicting/unusual/major-event evidence -> deeper challenge
still unresolved -> WAIT / NO TRADE
```

Explicit 1/2/3-round comparison belongs in a future Developer / Validation Lab. It must be benchmarked chronologically on BSE before choosing the production default.

This is recorded in `TRADEBRAIN_NEXT_WORK.md`.

## BSE-specific intelligence still planned

The longer-term analysis should compare **what happened, what is happening, and what historically worked specifically for BSE Ltd**. The planned optimizer should measure indicators/combinations/timeframes/regimes rather than assume RSI/MACD/VWAP/etc. are universally useful.

This remains future work; do not claim the full ML/indicator optimizer is already implemented.

## Paid API decision

Groq Developer upgrade was shown as temporarily unavailable due to demand, so the development path moved to a paid OpenAI API account.

The user has created/funded an OpenAI API account and created a key. **The secret was not shared in chat and must never be committed.**

Recommended Trade Brain OpenAI models now wired into Settings/catalog:

- Quick think: `gpt-5.6-luna`
- Deep think: `gpt-5.6-terra`

OpenAI primary now has retryable-capacity fallback to configured **Gemini 3.6 Flash**. Gemini remains eligible as an independent material verifier when OpenAI is primary. Groq may remain configured as another available provider, but it is no longer required as primary for development.

## Immediate local next step

Do **not** paste any API key into chat.

On Windows:

```powershell
Ctrl+C
cd D:\TradeBrain-Current
git pull --ff-only origin tradebrain/reframe-foundation
.\Start-TradeBrain.bat
```

Then open:

**Settings -> Models & Keys -> OpenAI**

Locally:

1. paste/save the OpenAI key;
2. click Test;
3. confirm Quick = `gpt-5.6-luna`;
4. confirm Deep = `gpt-5.6-terra`;
5. set OpenAI as default;
6. keep Gemini configured as fallback/verifier;
7. send only a screenshot of the masked Settings state, never the key.

Do not immediately spend tokens on another full BSE analysis until the Settings state is verified.

## CI note at handoff creation

A prior Foundation run on head `39bb6fdb0d947240c0cdfd23e8fa1951906a2c2f` had:

- frontend contract/build: PASS;
- Python compile/launcher checks: PASS;
- unit-tests: FAIL during collection because a newly-added OpenAI regression test imported `tradingagents.llm_clients`, which transitively required `langchain_openai` in the intentionally lightweight Foundation unit-test environment.

That was a **test-environment import problem**, not evidence of a runtime trading-logic failure. The regression test was changed to verify the model catalog from source without importing optional runtime SDKs, while still testing the actual OpenAI/Gemini failover functions normally.

Fresh GitHub Actions were running after that repair and the subsequent state-doc update when this handoff file was created. Do not call the final handoff head CI-green until those runs are checked.

## Existing protected checkpoints — do not overwrite

- `checkpoint/tradebrain-bse-framework-2026-08-25` at `5d8ff95c013a9091f576591dbbe9bae4439c099e`
- `checkpoint/tradebrain-ml-plan-2026-08-26` at `95516cdc39738a025c4913f56764ea3a012561ea`

Create/use a new Aug-26 provider/UI checkpoint for this continuation point; do not move the older checkpoint refs.

## Important next-work file

Read `TRADEBRAIN_NEXT_WORK.md` before continuing. It contains the active checklist for adaptive reasoning depth, BSE-specific optimizer work, OpenAI local validation, provider failover, runaway spend protection and end-to-end validation.
