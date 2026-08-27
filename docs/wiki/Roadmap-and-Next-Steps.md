# Roadmap and Next Steps

This page is the operational queue. Update it whenever the next concrete work item changes.

## Immediate priority — certify newest research head

The newest structural-break, kill-governance, meta-label, and causal-sequence modules were added after the last fully certified statistical-governance boundary.

Before calling them green:

1. run exact-head Foundation CI;
2. confirm compile and launcher validation;
3. confirm the complete `tests/test_tradebrain_*.py` suite;
4. confirm observational smoke phases remain clean;
5. inspect any new failures rather than weakening statistical gates.

Do not transfer an older green status to a newer commit.

## Next implementation — finish kill-criteria orchestration

The research ledger and kill/MinTRL logic exist, but the supervisor still needs final orchestration so run artifacts directly expose and enforce:

- selected candidate's DSR result written back into family research state;
- per-family distinct-candidate count;
- family exhausted / open status;
- MinTRL verdict;
- normal-friction viability verdict;
- reason parameter mining stopped;
- explicit distinction between `FAMILY_KILLED` and `TASK_HAS_NO_EDGE`.

No kill rule should weaken the ability to test a genuinely new, predeclared hypothesis family.

## Next challenger — 1-minute-derived alternative bars

Implement a separate research-only alternative-bar module using audited 1-minute BSE OHLCV.

Candidate constructions:

- volume bars;
- rupee-value/activity bars.

Required safeguards:

- deterministic construction;
- source-minute lineage;
- session-boundary handling;
- no cross-session aggregation unless explicitly designed;
- no claim of tick reconstruction;
- no claim of bid/ask or queue history;
- independent research-family accounting;
- chronology and holdout rules unchanged.

## Then — evaluate structural-break and meta-label challengers

Once audited local Kite history is available to the current exact code:

### Structural break

Compare:

- full-history control;
- pre-2023 downweighted;
- post-2023 only.

The winner, if any, must emerge under the same stress/multiple-testing/CI/CPCV rules. Do not assume post-2023 is superior before data says so.

### Meta-label families

Run trend, mean-reversion, and volatility-breakout primary setups as separate hypothesis families.

Track:

- setup count;
- coverage;
- long/short task separation;
- net expectancy;
- normal/1.5×/2× friction;
- DSR;
- PBO;
- stationary-bootstrap intervals;
- CPCV;
- MinTRL;
- regime stability.

## Audited local Kite run

When the local audited Kite historical database is ready, the ML optimizer should be run on that source rather than silently using Yahoo fallback.

Expected CLI path:

```bat
Optimize-TradeBrain-ML.bat --deep
```

Expected evidence after a real run:

- per-task dataset row counts;
- dataset snapshot/hash;
- chronology windows;
- trial count;
- research-ledger count;
- candidate metrics;
- normal / 1.5× / 2× stress metrics;
- DSR/PBO evidence;
- bootstrap evidence;
- CPCV evidence;
- registered model ID/stage when applicable;
- artifact paths/timestamps;
- explicit advisory-only/execution-false flags.

Do not claim model training occurred merely because historical data exists. Training is evidenced by optimizer artifacts/trials/model registry output.

## Cross-asset context — later

Add only after auditable point-in-time history is available:

- NIFTY 50;
- INDIA VIX;
- broad financial-sector context such as NIFTY Financial Services when appropriate.

Do not add arbitrary individual stocks simply to grow feature dimensionality.

## Neural sequence models — deferred

Do not implement LSTM/Transformer architectures now.

Revisit only if:

- the number of independent/non-overlapping setups is genuinely large;
- tabular sequence features have been fairly evaluated;
- the new model family can be charged cleanly to research budget;
- validation remains computationally feasible under purged chronology and multiple-testing controls.

## Whole-application hardening after ML research layer

Before calling the entire app production-ready, revisit:

- paid LLM runaway/billing guard integration;
- stale generic multi-stock memories;
- generic ticker/data-source escape paths;
- BSE-specific Bull/Bear/Risk prompt cleanup;
- replay/news lookback provenance;
- stale docs;
- scheduled dependency-refresh direct mutation risk;
- settings/provider-model consistency;
- remaining generic UI/API ticker parameters.

## End-state definition

A usable Trade Brain is not defined as “a model won a backtest.” It requires:

1. audited market data;
2. deterministic safety/risk boundaries;
3. statistically defensible candidate evidence;
4. exact-head tested software;
5. human-reviewed model stage;
6. prospective/shadow evidence;
7. advisory-only operation unless a completely separate future execution project is explicitly authorized.
