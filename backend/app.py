"""FastAPI application for the Indian Market Trading Agent."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from backend.db import ensure_db
from backend.routers import (
    market_data, analysis, watchlist, backtest, strategies, scanner, performance,
    recommender, settings as settings_router, news as news_router,
    simulation as simulation_router, insights as insights_router, fii_dii as fii_dii_router,
    calendar as calendar_router, concentration as concentration_router,
    daily_verdict as daily_verdict_router, signal_performance as signal_performance_router,
    verdict_calibration as verdict_calibration_router, regime as regime_router,
    confidence_calibration as confidence_calibration_router, shadow_trades as shadow_trades_router,
    memory as memory_router, tradebrain as tradebrain_router,
    tradebrain_phase3 as tradebrain_phase3_router,
    tradebrain_phase4 as tradebrain_phase4_router,
    tradebrain_phase5 as tradebrain_phase5_router,
    tradebrain_phase6 as tradebrain_phase6_router,
    tradebrain_phase7 as tradebrain_phase7_router,
    tradebrain_phase8 as tradebrain_phase8_router,
    tradebrain_phase9 as tradebrain_phase9_router,
    tradebrain_phase10 as tradebrain_phase10_router,
    tradebrain_evidence as tradebrain_evidence_router,
)
from backend.settings_manager import load_api_keys_into_env, apply_llm_config_to_default
from backend.tradebrain.store import ensure_tradebrain_schema
from backend.tradebrain.security_store import ensure_security_master_schema
from backend.tradebrain.corporate_event_store import ensure_corporate_event_schema
from backend.tradebrain.market_data_store import ensure_market_data_schema
from backend.tradebrain.focus_lab_store import ensure_focus_lab_schema
from backend.tradebrain.challenger_store import ensure_challenger_schema
from backend.tradebrain.regime_hardening import install_phase4_regime_hardening
from backend.tradebrain.paper_ledger import ensure_paper_ledger_schema
from backend.tradebrain.exchange_calendar import ensure_exchange_calendar_schema
from backend.tradebrain.advisory_store import ensure_advisory_schema
from backend.tradebrain.evidence_baseline import ensure_evidence_schema
from backend.tradebrain.prospective_gap import ensure_prospective_gap_schema
from backend.tradebrain.kite_stream import ensure_kite_live_schema
from backend.tradebrain.market_source_policy import market_source_status


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
    install_phase4_regime_hardening()
    load_api_keys_into_env()
    apply_llm_config_to_default()
    yield


app = FastAPI(
    title="Indian Market Trading Agent — Trade Brain Reframe",
    description="Resident-Indian INTRADAY/SWING research with audited evidence, deterministic gating and execution disabled",
    version="0.12.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_data.router)
app.include_router(analysis.router)
app.include_router(watchlist.router)
app.include_router(backtest.router)
app.include_router(strategies.router)
app.include_router(scanner.router)
app.include_router(performance.router)
app.include_router(recommender.router)
app.include_router(settings_router.router)
app.include_router(news_router.router)
app.include_router(simulation_router.router)
app.include_router(insights_router.router)
app.include_router(fii_dii_router.router)
app.include_router(calendar_router.router)
app.include_router(concentration_router.router)
app.include_router(daily_verdict_router.router)
app.include_router(signal_performance_router.router)
app.include_router(verdict_calibration_router.router)
app.include_router(regime_router.router)
app.include_router(confidence_calibration_router.router)
app.include_router(shadow_trades_router.router)
app.include_router(memory_router.router)
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


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "indian-trading-agent",
        "tradebrain_reframe": True,
        "tradebrain_version": "0.12.0",
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
        "llm_provider", "deep_think_llm", "quick_think_llm",
        "market", "default_exchange", "trading_style",
        "max_debate_rounds", "max_risk_discuss_rounds",
        "dry_run", "order_execution_enabled", "advisory_only",
        "active_trade_modes", "intraday_no_fresh_entry", "intraday_hard_exit",
        "trader_profile", "market_data_credential_role", "mtf_enabled",
        "max_position_value", "max_loss_per_trade", "max_daily_loss",
        "max_open_positions",
    ]
    return {k: DEFAULT_CONFIG.get(k) for k in safe_keys}
