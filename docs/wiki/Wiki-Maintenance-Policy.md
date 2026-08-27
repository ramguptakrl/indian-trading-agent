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
3. `Roadmap-and-Next-Steps`
4. the relevant subsystem page, especially `ML-Research-Plan` for optimizer work.

Git history/code remains the source of truth for implementation details. The Wiki is the source of truth for **project state and intent**.

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
2. explain what it preserves;
3. do not move older checkpoint refs;
4. note any important unfinished work at that checkpoint.

## Wiki sync model

Canonical managed Markdown lives under `docs/wiki/` on the active Trade Brain branch. A GitHub Actions workflow mirrors those managed pages into the repository's actual GitHub Wiki repository.

This gives us:

- normal code-reviewable history for project memory;
- an easy-to-read GitHub Wiki;
- a recoverable canonical copy even if Wiki content is edited or lost.

If the actual GitHub Wiki has never had its first page initialized, GitHub may require a one-time initial page creation before the `.wiki.git` repository can be cloned/pushed. After that, the sync workflow is the normal maintenance path.
