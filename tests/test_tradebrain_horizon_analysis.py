from backend.routers import analysis_horizons
from backend.routers.analysis_horizons import HorizonAnalysisRequest
from tradingagents.agents.managers.portfolio_manager import _horizon_instruction as manager_horizon
from tradingagents.agents.trader.trader import _horizon_instruction as trader_horizon


def test_horizon_instructions_do_not_allow_mode_substitution():
    intraday = trader_horizon("INTRADAY") + manager_horizon("INTRADAY")
    swing = trader_horizon("SWING") + manager_horizon("SWING")

    assert "MUST be INTRADAY" in intraday
    assert "Do not switch to SWING" in intraday
    assert "MUST be SWING" in swing
    assert "Direction` MUST be LONG" in swing
    assert "Do not switch to INTRADAY" in swing
    assert "Zerodha MTF only" in swing
    assert "Never invent" in swing


def test_run_horizon_pair_launches_two_independent_modes(monkeypatch):
    calls = []

    def fake_launch(req, mode):
        calls.append(mode)
        return f"task-{mode.lower()}"

    monkeypatch.setattr(analysis_horizons, "_launch", fake_launch)
    result = analysis_horizons.run_horizon_pair(
        HorizonAnalysisRequest(ticker="BSE", trade_date="2026-08-25")
    )

    assert calls == ["INTRADAY", "SWING"]
    assert result["tasks"] == {
        "INTRADAY": "task-intraday",
        "SWING": "task-swing",
    }
    assert result["independent_graph_runs"] is True
    assert result["shared_final_decision"] is False
    assert result["horizon_substitution_allowed"] is False
    assert result["swing_funding"] == "ZERODHA_MTF_ONLY"
    assert result["order_execution_allowed"] is False


def test_non_bse_target_is_rejected():
    try:
        HorizonAnalysisRequest(ticker="RELIANCE", trade_date="2026-08-25")
        raise AssertionError("expected BSE-only validation error")
    except Exception as exc:
        assert "BSE" in str(exc)
