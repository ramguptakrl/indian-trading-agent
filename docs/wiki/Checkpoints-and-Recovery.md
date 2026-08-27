# Checkpoints and Recovery

These refs are recovery anchors. Treat them as immutable unless there is an explicit, deliberate project decision to create a **new** checkpoint. Do not move an existing checkpoint ref.

## Latest timestamped checkpoint

### `checkpoint/tradebrain-handoff-2026-08-26-2127-et`

- **Commit:** `e340d983db0a40f8c8990cbb8558c3f748423423`
- **Toronto / Eastern Time:** 2026-08-26 21:26:54 EDT (UTC-04:00)
- **India Standard Time:** 2026-08-27 06:56:54 IST (UTC+05:30)
- **UTC:** 2026-08-27 01:26:54 UTC
- **Active working branch at creation:** `tradebrain/reframe-foundation`
- **Last fully certified statistical-governance boundary:** `5700f2e8282583ef7f9acb87a5641a4ccf23d379`
- **Latest research-code commit captured:** `a33c6769e0e7fb664f0337e65260004c71414282`
- **PR #1:** open/unmerged.
- **What it preserves:** the current ML statistical-governance work, research kill/MinTRL code, May-2023 structural-break challenger, meta-labeling primary-signal families, causal sequence/OHLC proxy features, and the timestamped GitHub Wiki handoff/memory system.
- **Important unfinished work:** the newest combined research modules still require exact-head CI certification; kill-family status still needs final supervisor orchestration; the 1m-derived Volume/Rupee Activity Bar challenger is not yet implemented.
- **Next exact action:** certify the newest combined research head with the full relevant CI/test suite before adding further model hypotheses.
- **Safety boundary:** advisory only; no broker execution authority; no approved ML champion.

This branch is an immutable handoff/recovery anchor. Do not repoint it.

## Earlier immutable checkpoints

| Checkpoint | Commit | Purpose |
|---|---|---|
| `checkpoint/tradebrain-foundation-green-2026-08-26` | `e702229640e3177fb57df3071d3dd9370b811506` | Foundation-green recovery boundary |
| `checkpoint/tradebrain-openai-ui-2026-08-26` | `e3ad4e74d60c2e03b603cee522cfd3bbb846ebbc` | OpenAI/UI recovery boundary |
| `checkpoint/tradebrain-bse-framework-2026-08-25` | `5d8ff95c013a9091f576591dbbe9bae4439c099e` | BSE Trade Brain framework checkpoint |
| `checkpoint/tradebrain-ml-plan-2026-08-26` | `95516cdc39738a025c4913f56764ea3a012561ea` | Frozen v0.14 ML self-training plan |

The earlier checkpoints were created before the explicit three-time-zone checkpoint rule. Their exact creation clock times were not recorded here, so **do not invent timestamps for them**. Their branch names, dates, purposes, and SHAs remain authoritative.

## Active development branch

`tradebrain/reframe-foundation`

Do not confuse the active branch head with a checkpoint. Development heads move; checkpoints do not.

## Known certified research boundary

The statistical-governance layer was fully certified at:

`5700f2e8282583ef7f9acb87a5641a4ccf23d379`

This is a useful green reference but, unless a dedicated immutable checkpoint branch/tag is explicitly created for it, do not describe it as one of the immutable checkpoint refs above.

## Recovery rules

1. Never force-update an immutable checkpoint.
2. Never merge PR #1 simply to create a recovery point.
3. When a major subsystem reaches a clean, exact-head green boundary, consider creating a **new named checkpoint** rather than repointing an old one.
4. Record every new checkpoint on this page immediately.
5. Record Toronto/Eastern, IST, and UTC timestamps for every new checkpoint.
6. A checkpoint should state what it preserves and what remained unfinished at that moment.
7. Before recovering, compare the active branch against the checkpoint rather than overwriting blindly.

## Historical staged-tree warning

There were older staged trees built from the OpenAI/UI-era checkpoint. They must not be directly committed onto the modern branch. If any idea from them is still needed, rebuild the relevant change against the current active head and test it normally.

Known historical staged trees:

- `32380e8...` — LLM guard integration/default BSE config/memory/run-ID ideas.
- `6e16def...` — BSE prompts/router/news-safety/pyproject cleanup ideas.

These are references for reconstruction only, not merge targets.

## What a new checkpoint should capture

For every future ML/research checkpoint, record at least:

- exact commit SHA;
- checkpoint branch/tag/ref;
- Toronto / Eastern timestamp with UTC offset;
- India Standard Time timestamp;
- UTC timestamp;
- active development branch at creation;
- exact CI status;
- unit-test count if useful;
- what statistical safeguards are present;
- what remains unverified on local audited Kite data;
- whether any model has actually been trained/registered;
- whether PR #1 remains unmerged;
- advisory/execution boundary;
- next exact action.
