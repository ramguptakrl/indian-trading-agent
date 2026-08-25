"""FastAPI application for Trade Brain — BSE Ltd."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import ensure_db
from backend.routers import (
    analysis,
    market_data,
    news as news_router,
    settings as settings_router,
    tradebrain as tradebrain_router,
    tradebrain_actual_trades as tradebrain_actual_trades_router,
    tradebrain_evidence as tradebrain_evidence_router,
    tradebrain_phase3 as tradebrain_phase3_router,
    tradebrain_phase4 as tradebrain_phase4_router,
    tradebrain_phase5 as tradebrain_phase5_router,
    tradebrain_phase6 as tradebrain_phase6_router,
    tradebrain_phase7 as tradebrain_phase7_router,
    tradebrain_phase8 as tradebrain_phase8_router,
    tradebrain_phase9 as tradebrain_phase9_router,
    tradebrain_phase10 as tradebrain_phase10_router,
)
from backend.settings_manager import apply_llm_config_to_default, load_api_keys_into_env
from backend.tradebrain.actual_trade_journal import ensure_actual_trade_schema
from backend.tradebrain.advisory_store import ensure_advisory_schema
from backend.tradebrain.bse_scope import public_scope
from backend.tradebrain.challenger_store import ensure_challenger_schema
from backend.tradebrain.corporate_event_store import ensure_corporate_event_schema
from backend.tradebrain.evidence_baseline import ensure_evidence_schema
from backend.tradebrain.exchange_calendar import ensure_exchange_calendar_schema
from backend.tradebrain.focus_lab_store import ensure_focus_lab_schema
from backend.tradebrain.kite_stream import ensure_kite_live_schema
from backend.tradebrain.market_data_store import ensure_market_data_schema
from backend.tradebrain.market_source_policy import market_source_status
from backend.tradebrain.paper_ledger import ensure_paper_ledger_schema
from backend.tradebrain.prospective_gap import ensure_prospective_gap_schema
from backend.tradebrain.regime_hardening import install_phase4_regime_hardening
from backend.tradebrain.security_store import ensure_security_master_schema
from backend.tradebrain.store import ensure_tradebrain_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_db()
    ensure_tradebrain_schema()
    ensure_security_master_schema()
    ensure_corporate_event_schema()
    ensure_market_data_schema()
    ensure_focus_lab_schema()
    ensure_challenger_schema()
    ensure_paper_ledger_schema()
    ensure_exchange_calendar_schema()
    ensure_advisory_schema()
    ensure_evidence_schema()
    ensure_prospective_gap_schema()
    ensure_kite_live_schema()
    ensure_actual_trade_schema()
    install_phase4_regime_hardening()
    load_api_keys_into_env()
    apply_llm_config_to_default()
    yield


app = FastAPI(
    title="Trade Brain — BSE Ltd",
    description=(
        "BSE Ltd-only resident-Indian INTRADAY/SWING research with audited evidence, "
        "deterministic gating, broader-market context and broker execution disabled"
    ),
    version="0.13.0-bse",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# BSE product runtime surface. The original generic ITA runtime remains preserved on `main`.
# This branch intentionally does NOT mount legacy recommender/scanner/watchlist/backtest/
# generic-simulation/calibration/shadow-trade/memory-admin APIs.
app.include_router(market_data.router)
app.include_router(analysis.router)
app.include_router(settings_router.router)
app.include_router(news_router.router)
app.include_router(tradebrain_router.router)
app.include_router(tradebrain_phase3_router.router)
app.include_router(tradebrain_phase4_router.router)
app.include_router(tradebrain_phase5_router.router)
app.include_router(tradebrain_phase6_router.router)
app.include_router(tradebrain_phase7_router.router)
app.include_router(tradebrain_phase8_router.router)
app.include_router(tradebrain_phase9_router.router)
app.include_router(tradebrain_phase10_router.router)
app.include_router(tradebrain_evidence_router.router)
app.include_router(tradebrain_actual_trades_router.router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "trade-brain-bse",
        "tradebrain_reframe": True,
        "tradebrain_version": "0.13.0-bse",
        "product_scope": public_scope(),
        "bse_only_trade_target": True,
        "broader_market_role": "CONTEXT_ONLY",
        "legacy_ita_trade_discovery_routes_mounted": False,
        "trader_profile": "RESIDENT_INDIAN",
        "active_trade_modes": ["INTRADAY", "SWING"],
        "mtf_enabled": False,
        "corporate_event_memory": True,
        "audited_market_data": True,
        "lookahead_safe_replay": True,
        "strict_replay_outcomes": True,
        "focus_instrument_lab": True,
        "frozen_challenger_validation": True,
        "approved_soft_runtime": True,
        "verified_exchange_calendar_capability": True,
        "kite_market_data_only_adapter": True,
        "kite_websocket_live_plane": True,
        "kite_long_history_chunking": True,
        "market_source_preference": market_source_status(),
        "resident_equity_cost_engine": True,
        "net_cost_paper_ledger": True,
        "actual_manual_trade_journal": True,
        "actual_trades_link_to_advisory_snapshot": True,
        "actual_trade_partial_close": True,
        "final_advisory_pipeline": True,
        "descriptive_evidence_baseline": True,
        "prospective_hypothesis_collection": True,
        "prospective_gap_freeze_date": "2026-08-21",
        "raw_buy_sell_signal_disabled": True,
        "human_approval_required_for_soft_promotion": True,
        "data_credentials_may_be_data_only": True,
        "advisory_only": True,
        "trade_authorization": False,
        "order_execution_enabled": False,
    }


@app.get("/api/config")
def get_config():
    from tradingagents.default_config import DEFAULT_CONFIG

    safe_keys = [
        "llm_provider",
        "deep_think_llm",
        "quick_think_llm",
        "market",
        "default_exchange",
        "trading_style",
        "max_debate_rounds",
        "max_risk_discuss_rounds",
        "dry_run",
        "order_execution_enabled",
        "advisory_only",
        "active_trade_modes",
        "intraday_no_fresh_entry",
        "intraday_hard_exit",
        "trader_profile",
        "market_data_credential_role",
        "mtf_enabled",
        "max_position_value",
        "max_loss_per_trade",
        "max_daily_loss",
        "max_open_positions",
    ]
    config = {key: DEFAULT_CONFIG.get(key) for key in safe_keys}
    config["product_scope"] = public_scope()
    return config
