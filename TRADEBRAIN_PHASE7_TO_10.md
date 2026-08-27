# Trade Brain Phases 7–10 — Runtime Governance to Final Advisory Boundary

Status: implemented in Trade Brain v0.11.0.

These phases finish the control-plane/productization work that remained after the resident-INTRADAY/SWING economics and paper ledger in Phase 6. Automatic order execution remains OFF.

## Phase 7 — human-approved soft parameters at runtime

Phase 5 can promote a validated soft parameter only after explicit human approval. Phase 7 is the reviewed runtime bridge.

Currently supported runtime soft preferences:

- INTRADAY minimum reward:risk, backed by the legacy registry key `day_min_reward_risk` / scope `DAY` for audit compatibility.
- SWING minimum reward:risk, backed by `swing_min_reward_risk` / scope `SWING_POSITION`.

Rules:

- only one ACTIVE version for the exact key/scope may apply;
- the ACTIVE row must retain human approver and approval-note provenance;
- missing, malformed, ambiguous or unavailable registry state falls back to the documented default;
- the gate exposes the parameter key, version and source used;
- the registry affects only the soft PASS/WAIT preference;
- hard clocks, Crash Guard, geometry, broker permission, SWING long-only, advisory-only and execution-disabled rules are never read from this registry.

## Phase 8 — verified exchange calendar/session memory

Weekday logic is no longer treated as proof that an exchange is open.

Implemented:

- official NSE trading holiday-master collector for the cash-market (`CM`) segment;
- raw content-addressed archive + SHA-256 + parser version;
- persistent source/year coverage;
- explicit CLOSED dates;
- regular weekdays inferred only within a year covered by official annual holiday evidence;
- Diwali/Muhurat-like holiday rows are `SPECIAL_PENDING` until verified session times are supplied;
- verified special/exception override path requires an HTTPS official NSE/BSE source URL plus SHA-256;
- BSE is not silently assumed to share NSE's calendar;
- safety-critical scheduler calls can require verified coverage and fail closed when unavailable.

The immutable INTRADAY 15:10 no-new-entry and 15:15 flat-before clock remains above calendar exceptions. A special session cannot silently rewrite those hard times.

## Phase 9 — Kite Connect market-data-only adapter

Kite credentials are transport credentials, not trader identity.

The adapter can use:

- instrument master;
- full/OHLC/LTP quotes;
- historical candles;
- audited replay/backtest input.

The adapter deliberately has no place/modify/cancel order methods and imports no margin/account restrictions into resident policy.

Boundary:

- modeled trader: `RESIDENT_INDIAN`;
- credential may belong to an NRI account: yes;
- credential role: `MARKET_DATA_ONLY`;
- credential account type affects policy: false;
- credential account type affects resident cost profile: false;
- order API enabled: false.

Historical Kite candles are normalized into the same Phase-3 source-aware RAW_UNADJUSTED store, with fetch audit records, SHA-256 normalized snapshots, identity binding and the same `ts_close <= as_of` replay contract.

No live Kite transport success is claimed until valid data credentials are actually configured.

## Phase 10 — final fail-closed advisory pipeline

The upstream graph previously collapsed final research prose into a naked BUY/SELL/HOLD label using another LLM call. That seam is removed.

### Safe research labels

The compatibility SignalProcessor is deterministic and returns only:

- `LONG_CANDIDATE`
- `SHORT_CANDIDATE`
- `EXIT_CANDIDATE`
- `WAIT`
- `NO_TRADE`

These are research labels, not trade permission.

### Strict candidate parser

Only explicit labelled Portfolio Manager fields are parsed:

- Candidate Verdict
- Trade Mode
- Direction
- Entry Price
- Stop-Loss
- Take-Profit

Free-form prose is never searched for bullish/bearish intent. Numeric ranges, alternatives or missing geometry fail closed.

A SELL/EXIT label is treated as reduction/exit context and cannot silently become a fresh short. A new short must be an explicit INTRADAY `SHORT CANDIDATE` with valid geometry.

### Final validation order

A new-entry candidate must pass:

1. strict structured parse;
2. verified exchange calendar/session state;
3. explicit Crash Guard state;
4. explicit broker/exchange permission state;
5. deterministic Trade Brain hard-rule gate;
6. current human-approved/default soft R:R preference;
7. optional resident transaction-cost target/stop scenarios when quantity is supplied.

Unknown deterministic facts block final validation instead of being defaulted from AI prose.

The final object separately exposes:

- AI candidate parse;
- calendar/session evidence;
- deterministic gate;
- trade geometry;
- soft-parameter provenance;
- resident transaction-cost scenarios;
- advisory/execution boundary.

Every final object states:

- `advisory_only=true`;
- `trade_authorization=false`;
- `order_execution_allowed=false`;
- `order_endpoint_present=false`.

### General analysis endpoint

The existing `/api/analysis` flow remains available for the upstream UI, but its old BUY/SELL `signal` meaning is removed. The compatibility field now contains a safe research label and the WebSocket/result payload explicitly states that Trade Brain validation is required.

For historical analysis requests containing only a date, the system does not invent a decision clock; it labels the result `HISTORICAL_RESEARCH_NOT_LIVE_GATE`.

For current-date analysis, the automatic wrapper does not fabricate Crash Guard or broker permission. A fully validated current advisory requires those explicit facts through the Phase-10 final-advisory endpoint.

Final boundaries are persisted in `tb_final_advisories` beside the upstream analysis history without destructively changing the upstream table.

## Product completion boundary

At v0.11.0 the core Trade Brain framework is considered constructed:

- resident trader profile;
- INTRADAY + SWING only;
- no MTF;
- official identity/provenance;
- event/document memory;
- audited market history/replay;
- strict outcomes/Focus Lab;
- frozen walk-forward challenger governance;
- human-approved soft runtime;
- resident transaction-cost paper accounting;
- verified calendar capability;
- optional Kite data-only adapter;
- fail-closed final advisory boundary;
- no automatic orders.

Remaining work is deployment/evidence/configuration rather than an implicit execution phase: load/refresh source data, configure optional data credentials, supply verified BSE special-session evidence where needed, accumulate real replay/paper samples, and decide separately whether/when the draft branch should be merged.
