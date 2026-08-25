"""Regression coverage for the single-instrument BSE Ltd product boundary."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.models import AnalysisRequest
from backend.tradebrain.bse_scope import BSE_SCOPE, is_bse_trade_target, require_bse_trade_target

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_bse_scope_is_single_instrument():
    assert BSE_SCOPE.company_name == "BSE Ltd"
    assert BSE_SCOPE.ticker == "BSE"
    assert BSE_SCOPE.exchange == "NSE"
    assert BSE_SCOPE.kite_symbol == "NSE:BSE"
    assert BSE_SCOPE.isin == "INE118H01025"
    assert BSE_SCOPE.tradable_instruments == ("NSE:BSE",)
    assert BSE_SCOPE.active_modes == ("INTRADAY", "SWING")


@pytest.mark.parametrize("alias", ["BSE", "NSE:BSE", "BSE.NS", "BSE Ltd", "BSE LIMITED"])
def test_bse_aliases_normalize_to_canonical_ticker(alias):
    assert is_bse_trade_target(alias) is True
    assert require_bse_trade_target(alias) == "BSE"


def test_non_bse_trade_target_is_rejected():
    assert is_bse_trade_target("RELIANCE") is False
    with pytest.raises(ValueError, match="BSE Ltd-only"):
        require_bse_trade_target("RELIANCE")


def test_analysis_request_cannot_become_generic_multi_stock():
    request = AnalysisRequest(ticker="NSE:BSE", trade_date="2026-08-25")
    assert request.ticker == "BSE"

    with pytest.raises(ValidationError):
        AnalysisRequest(ticker="INFY", trade_date="2026-08-25")


def test_frontend_analysis_has_no_generic_ticker_picker():
    page = (ROOT / "frontend" / "src" / "app" / "analysis" / "page.tsx").read_text(encoding="utf-8")
    assert 'const BSE_TICKER = "BSE"' in page
    assert "TickerSearch" not in page
    assert "Analyze BSE" in page
    assert "Analysis Date" in page and "India / IST" in page


def test_bse_decision_card_surfaces_structured_price_levels():
    card = (ROOT / "frontend" / "src" / "components" / "analysis" / "DecisionCard.tsx").read_text(encoding="utf-8")
    for label in ("Entry", "Stop-Loss", "Primary Target", "Gross R:R"):
        assert label in card
    assert "Trade Brain will not invent levels" in card


def test_sidebar_hides_generic_ita_discovery_surface():
    sidebar = (ROOT / "frontend" / "src" / "components" / "layout" / "Sidebar.tsx").read_text(encoding="utf-8")
    for required in ("BSE Today", "BSE Analysis", "Price & Structure", "BSE Context", "BSE Evidence", "Actual Trades"):
        assert required in sidebar
    for removed in ("Top Picks", "Market Scan", "Verdict Calibration", "Shadow Trades", "AI Backtest"):
        assert removed not in sidebar
