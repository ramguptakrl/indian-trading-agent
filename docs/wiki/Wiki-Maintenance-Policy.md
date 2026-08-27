# Wiki Maintenance Policy

This Wiki is the project's durable memory. It should be treated as part of the engineering workflow, not as optional documentation.

## Required update rule

Whenever a meaningful Trade Brain change is made, update the relevant Wiki page in the same work session or immediately after the code/test result is known.

Meaningful changes include:

- architecture or product-doctrine changes;
- new ML/research hypothesis families;
- feature/label/validation changes;
- statistical gate changes;
- data-source/provenance changes;
- scheduler/retraining behavior changes;
- model-registry/promotion changes;
- CI certification or failure that changes project status;
- checkpoint creation;
- roadmap priority changes;
- discovery that an earlier assumption was wrong;
- production-readiness caveats being added or resolved.

## Read-before-work rule

Before resuming substantial project work, use these pages as the canonical orientation set:

1. `Home`
2. `Current-Status`
3. `Session-Handoff`
4. `Roadmap-and-Next-Steps`
5. the relevant subsystem page, especially `ML-Research-Plan` for optimizer work.

Git history/code remains the source of truth for implementation details. The Wiki is the source of truth for **project state and intent**.

## Timestamp rule

Every checkpoint, session handoff, major CI certification, and major research-state change must include explicit timestamps in all three forms:

- **Toronto / Eastern Time** with UTC offset and timezone abbreviation when unambiguous;
- **India Standard Time (IST)** with UTC+05:30;
- **UTC**.

Use an exact date and clock time, not only words like "today", "tonight", or "last night".

A checkpoint entry must also record:

- immutable checkpoint branch/tag/ref;
- exact commit SHA;
- active working branch at creation;
- what the checkpoint preserves;
- last certified-green boundary, if different;
- unfinished work / next exact action.

This makes checkpoints recoverable even when chat history is unavailable or ambiguous across time zones.

## Session-handoff rule

When a chat becomes slow, reaches context limits, or substantial work is about to pause:

1. update `Session-Handoff` with Toronto, IST, and UTC timestamps;
2. record the active branch and exact branch HEAD at handoff start;
3. distinguish the latest research-code commit from later documentation-only commits when useful;
4. record the last fully certified-green boundary separately from the newest head;
5. state the next exact action in imperative form;
6. create an immutable timestamped checkpoint branch for material development stages when useful;
7. update `Checkpoints-and-Recovery` with its exact SHA.

A newer session should replace the *latest resume point* on `Session-Handoff`, while durable named checkpoints remain listed in `Checkpoints-and-Recovery`.

## Status vocabulary

Use these labels precisely:

### Certified / Green

The exact commit being described passed the relevant CI/test boundary.

### Implemented — certification pending

Code exists, but the newest exact head has not yet completed the required CI/test suite.

### Planned

Approved next work, not yet implemented.

### Deferred

Intentionally postponed because prerequisites/evidence are insufficient.

### Rejected / Killed hypothesis

A research idea or parameter family was stopped by predeclared evidence/kill criteria. This is not automatically a software failure or proof that all BSE strategies lack edge.

Never call a newer head green because an older commit was green.

## What not to put in the Wiki

The repository and Wiki may be public. Never record:

- API keys, access tokens, secrets, passwords;
- broker credentials;
- private account identifiers;
- personal financial/account data;
- machine-specific sensitive information that is not required for public technical documentation.

Use environment-variable names and generic paths instead of secrets or personal machine details.

## Research documentation rule

Every new research family should record:

- hypothesis name;
- why it is distinct from existing families;
- deterministic/predeclared parts;
- parameters that consume research budget;
- chronology used;
- whether OOS/holdout were used at any stage;
- cost/slippage assumptions;
- DSR/PBO/bootstrap/CPCV requirements;
- kill criteria;
- whether it is implemented, certified, planned, or rejected.

## CI documentation rule

When exact-head CI completes:

- update `Current-Status` with the exact commit SHA;
- add Toronto / IST / UTC certification timestamps;
- state what passed;
- state what remains unverified;
- do not convert software validation into a profitability claim.

## Roadmap hygiene

`Roadmap-and-Next-Steps` should always answer one question unambiguously:

> **What is the next exact thing to do?**

Completed items should be moved into status/history rather than left looking unfinished.

## Checkpoint hygiene

When a new immutable checkpoint is created:

1. add its exact branch/tag/ref and SHA to `Checkpoints-and-Recovery`;
2. add Toronto / IST / UTC creation timestamps;
3. explain what it preserves;
4. do not move older checkpoint refs;
5. note any important unfinished work at that checkpoint;
6. state the next exact action after the checkpoint.

## Wiki sync model

Canonical managed Markdown lives under `docs/wiki/` on the active Trade Brain branch. A GitHub Actions workflow mirrors those managed pages into the repository's actual GitHub Wiki repository.

This gives us:

- normal code-reviewable history for project memory;
- an easy-to-read GitHub Wiki;
- a recoverable canonical copy even if Wiki content is edited or lost.

If the actual GitHub Wiki has never had its first page initialized, GitHub may require a one-time initial page creation before the `.wiki.git` repository can be cloned/pushed. After that, the sync workflow is the normal maintenance path.

### Verified operational status

The real GitHub Wiki repository was initialized and automatic synchronization was verified on 2026-08-26. Workflow run `33029999638` cloned `indian-trading-agent.wiki.git`, committed all eight initial managed pages as Wiki commit `9cc32d6`, and pushed successfully to the Wiki `master` branch.

From this point forward, meaningful changes to `docs/wiki/**` on `tradebrain/reframe-foundation` automatically trigger `Sync Trade Brain Wiki`. The workflow manages only the declared Trade Brain pages and does not delete unrelated Wiki pages.

The managed-page set now includes `Session-Handoff.md` for timestamped cross-chat resume state.
