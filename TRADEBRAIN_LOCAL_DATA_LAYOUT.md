# Trade Brain local data layout

Trade Brain can keep all user-specific runtime data beside the project instead of under the Windows user profile.

Recommended local root:

```text
D:\TradeBrain-Current\.tradebrain\
    trading_agent.db
    audit_txt\
    archive\
    snapshots\
    models\          # future ML model registry
    ml_runs\         # future ML training/optimization runs
    backups\
    logs\
    after_market_study_state.json
    after_market_study_v2_state.json
```

Set this only in the local ignored `.env`:

```text
TRADEBRAIN_DATA_DIR=D:\TradeBrain-Current\.tradebrain
```

When configured, `backend.db` places `trading_agent.db` inside that directory and Trade Brain modules that already honor `TRADEBRAIN_DATA_DIR` use the same root for study state, audit data and related evidence artifacts. The legacy fallback remains `~/.tradingagents/trading_agent.db` plus `~/.tradingagents/tradebrain/` when the setting is absent.

## Migration rule

Copy first; do not delete the old C-drive data until the D-drive copy has been verified. The migration should merge the old `~/.tradingagents/tradebrain/` contents into the new root and copy `~/.tradingagents/trading_agent.db` to the new root. Then add `TRADEBRAIN_DATA_DIR` to the local `.env`.

The project `.gitignore` excludes `.tradebrain/`, databases, logs and `.env`, so historical candles, credentials, study state and future trained-model artifacts stay local and must never be committed to GitHub.

## Safety boundary

Changing the storage location does not change product authority. Trade Brain remains advisory-only and broker order execution remains disabled.
