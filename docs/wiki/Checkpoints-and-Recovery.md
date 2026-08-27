# Checkpoints and Recovery

These refs are recovery anchors. Treat them as immutable unless there is an explicit, deliberate project decision to create a **new** checkpoint. Do not move an existing checkpoint ref.

## Immutable checkpoints

| Checkpoint | Commit | Purpose |
|---|---|---|
| `checkpoint/tradebrain-foundation-green-2026-08-26` | `e702229640e3177fb57df3071d3dd9370b811506` | Foundation-green recovery boundary |
| `checkpoint/tradebrain-openai-ui-2026-08-26` | `e3ad4e74d60c2e03b603cee522cfd3bbb846ebbc` | OpenAI/UI recovery boundary |
| `checkpoint/tradebrain-bse-framework-2026-08-25` | `5d8ff95c013a9091f576591dbbe9bae4439c099e` | BSE Trade Brain framework checkpoint |
| `checkpoint/tradebrain-ml-plan-2026-08-26` | `95516cdc39738a025c4913f56764ea3a012561ea` | Frozen v0.14 ML self-training plan |

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
5. A checkpoint should state what it preserves and what remained unfinished at that moment.
6. Before recovering, compare the active branch against the checkpoint rather than overwriting blindly.

## Historical staged-tree warning

There were older staged trees built from the OpenAI/UI-era checkpoint. They must not be directly committed onto the modern branch. If any idea from them is still needed, rebuild the relevant change against the current active head and test it normally.

Known historical staged trees:

- `32380e8...` — LLM guard integration/default BSE config/memory/run-ID ideas.
- `6e16def...` — BSE prompts/router/news-safety/pyproject cleanup ideas.

These are references for reconstruction only, not merge targets.

## What a new checkpoint should capture

For a future ML/research checkpoint, record at least:

- exact commit SHA;
- branch name;
- exact CI status;
- unit-test count if useful;
- what statistical safeguards are present;
- what remains unverified on local audited Kite data;
- whether any model has actually been trained/registered;
- whether PR #1 remains unmerged;
- advisory/execution boundary.
