from datetime import datetime
from zoneinfo import ZoneInfo

import backend.tradebrain.study_cycle as study


IST = ZoneInfo("Asia/Kolkata")


def test_study_cycle_skips_during_live_market(monkeypatch, tmp_path):
    monkeypatch.setattr(
        study,
        "get_operating_mode",
        lambda *args, **kwargs: {"mode": "LIVE_MARKET_RESEARCH", "calendar_verified": True},
    )
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.delenv("KITE_ACCESS_TOKEN", raising=False)

    result = study.run_after_market_study(
        now=datetime(2026, 8, 25, 10, 30, tzinfo=IST),
        state_path=tmp_path / "state.json",
    )

    assert result["status"] == "SKIPPED_NOT_STUDY_TIME"
    assert result["order_execution_allowed"] is False


def test_study_cycle_requires_local_kite_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(
        study,
        "get_operating_mode",
        lambda *args, **kwargs: {"mode": "POST_MARKET_STUDY", "calendar_verified": True},
    )
    monkeypatch.setattr(study, "audit_learning", lambda *args, **kwargs: str(tmp_path / "audit.txt"))
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.delenv("KITE_ACCESS_TOKEN", raising=False)

    result = study.run_after_market_study(
        now=datetime(2026, 8, 25, 18, 0, tzinfo=IST),
        state_path=tmp_path / "state.json",
    )

    assert result["status"] == "KITE_AUTH_REQUIRED"
    assert result["order_execution_allowed"] is False


def test_phase1_identity_is_reused_when_present(monkeypatch):
    monkeypatch.setattr(
        study,
        "get_exchange_listing",
        lambda exchange, symbol, db_path=None: {"exchange": exchange, "symbol": symbol, "isin": "INE118H01025"},
    )

    def should_not_refresh(**kwargs):
        raise AssertionError("security master should not refresh when NSE:BSE is already known")

    monkeypatch.setattr(study, "collect_nse_security_master", should_not_refresh)
    result = study._ensure_bse_phase1_identity()

    assert result["status"] == "ALREADY_PRESENT"
    assert result["exchange"] == "NSE"
    assert result["symbol"] == "BSE"


def test_phase1_identity_self_bootstraps_when_missing(monkeypatch):
    calls = {"lookups": 0, "refreshes": 0}

    def fake_listing(exchange, symbol, db_path=None):
        calls["lookups"] += 1
        if calls["lookups"] == 1:
            return None
        return {"exchange": exchange, "symbol": symbol, "isin": "INE118H01025"}

    def fake_refresh(**kwargs):
        calls["refreshes"] += 1
        return {"status": "SUCCESS", "rows_valid": 2000, "rows_rejected": 0}

    monkeypatch.setattr(study, "get_exchange_listing", fake_listing)
    monkeypatch.setattr(study, "collect_nse_security_master", fake_refresh)

    result = study._ensure_bse_phase1_identity()

    assert result["status"] == "REFRESHED"
    assert result["source"] == "NSE_EQUITY_SECURITY_MASTER"
    assert calls == {"lookups": 2, "refreshes": 1}


def test_phase1_identity_fails_closed_if_refresh_does_not_resolve_bse(monkeypatch):
    monkeypatch.setattr(study, "get_exchange_listing", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        study,
        "collect_nse_security_master",
        lambda **kwargs: {"status": "SUCCESS", "rows_valid": 2000, "rows_rejected": 0},
    )

    try:
        study._ensure_bse_phase1_identity()
    except ValueError as exc:
        assert "NSE:BSE is still unknown" in str(exc)
    else:
        raise AssertionError("study must fail closed when Phase 1 still cannot resolve NSE:BSE")


def test_successful_cycle_bootstraps_then_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("KITE_API_KEY", "A" * 16)
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "B" * 32)
    monkeypatch.setattr(
        study,
        "get_operating_mode",
        lambda *args, **kwargs: {"mode": "POST_MARKET_STUDY", "calendar_verified": True},
    )
    monkeypatch.setattr(
        study,
        "_ensure_bse_phase1_identity",
        lambda **kwargs: {
            "status": "ALREADY_PRESENT",
            "exchange": "NSE",
            "symbol": "BSE",
            "isin": "INE118H01025",
            "source": "PHASE1_LOCAL_IDENTITY_STORE",
        },
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def resolve_equity_instrument(self, exchange, symbol):
            assert (exchange, symbol) == ("NSE", "BSE")
            return {"instrument_token": 12345}

    monkeypatch.setattr(study, "KiteDataOnlyClient", FakeClient)

    calls = []

    def fake_sync(**kwargs):
        calls.append(kwargs["interval"])
        interval = "1d" if kwargs["interval"] == "day" else "5m"
        return {
            "status": "SUCCESS",
            "series_id": "series:test-bse",
            "interval": interval,
            "kite_interval": kwargs["interval"],
            "range_start": str(kwargs["from_time"]),
            "range_end": str(kwargs["to_time"]),
            "chunks": 2,
            "rows_received": 100,
            "bars_inserted": 90,
            "bars_updated": 10,
            "quality_issues_reported_across_chunks": 0,
            "source_key": "ZERODHA_KITE_CONNECT_MARKET_DATA_ONLY",
            "credential_role": "MARKET_DATA_ONLY",
            "order_api_enabled": False,
        }

    monkeypatch.setattr(study, "sync_kite_history_range", fake_sync)
    monkeypatch.setattr(
        study,
        "opening_gap_exploration",
        lambda *args, **kwargs: {
            "method_version": "TEST",
            "daily_bars": 100,
            "eligible_directional_gap_observations": 20,
            "cross_price_era_transitions_excluded": 0,
            "thresholds_pct": [0.5, 1.0],
            "cohorts": {},
        },
    )
    monkeypatch.setattr(
        study,
        "_replay_existing_bse_plans",
        lambda **kwargs: {
            "plans_seen": 3,
            "outcomes": {"TP_FIRST": 2, "SL_FIRST": 1},
            "failures": [],
            "failure_count": 0,
            "observation_kind": "HYPOTHETICAL_REPLAY",
            "automatic_policy_change": False,
        },
    )
    monkeypatch.setattr(
        study,
        "collect_prospective_gap_observations",
        lambda *args, **kwargs: {
            "hypothesis_id": "BSE_PROSPECTIVE_HYPOTHESIS_001",
            "freeze_date": "2026-08-21",
            "eligible_observations": 1,
            "skipped": {},
            "summary": {"decision": "NEEDS_MORE_DATA", "automatic_promotion": False},
        },
    )
    monkeypatch.setattr(study, "audit_learning", lambda *args, **kwargs: str(tmp_path / "audit.txt"))

    state_path = tmp_path / "state.json"
    result = study.run_after_market_study(
        now=datetime(2026, 8, 25, 18, 0, tzinfo=IST),
        state_path=state_path,
    )

    assert result["status"] == "SUCCESS"
    assert result["bootstrap"] is True
    assert result["phase1_identity"]["status"] == "ALREADY_PRESENT"
    assert calls == ["day", "5minute"]
    assert result["learning_boundary"]["llm_weights_modified"] is False
    assert result["learning_boundary"]["hard_rules_modified"] is False
    assert result["order_execution_allowed"] is False

    second = study.run_after_market_study(
        now=datetime(2026, 8, 25, 19, 0, tzinfo=IST),
        state_path=state_path,
    )
    assert second["status"] == "ALREADY_COMPLETED_TODAY"
