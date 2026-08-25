"""Regression coverage for the single-instrument BSE Ltd product boundary."""

import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.models import AnalysisRequest
from backend.tradebrain.bse_scope import BSE_SCOPE, is_bse_trade_target, require_bse_trade_target

ROOT = Path(__file__).resolve().parents[1]


class TradeBrainBseScopeTests(unittest.TestCase):
    def test_canonical_bse_scope_is_single_instrument(self):
        self.assertEqual(BSE_SCOPE.company_name, "BSE Ltd")
        self.assertEqual(BSE_SCOPE.ticker, "BSE")
        self.assertEqual(BSE_SCOPE.exchange, "NSE")
        self.assertEqual(BSE_SCOPE.kite_symbol, "NSE:BSE")
        self.assertEqual(BSE_SCOPE.isin, "INE118H01025")
        self.assertEqual(BSE_SCOPE.tradable_instruments, ("NSE:BSE",))
        self.assertEqual(BSE_SCOPE.active_modes, ("INTRADAY", "SWING"))

    def test_bse_aliases_normalize_to_canonical_ticker(self):
        for alias in ("BSE", "NSE:BSE", "BSE.NS", "BSE Ltd", "BSE LIMITED"):
            with self.subTest(alias=alias):
                self.assertTrue(is_bse_trade_target(alias))
                self.assertEqual(require_bse_trade_target(alias), "BSE")

    def test_non_bse_trade_target_is_rejected(self):
        self.assertFalse(is_bse_trade_target("RELIANCE"))
        with self.assertRaisesRegex(ValueError, "BSE Ltd-only"):
            require_bse_trade_target("RELIANCE")

    def test_analysis_request_cannot_become_generic_multi_stock(self):
        request = AnalysisRequest(ticker="NSE:BSE", trade_date="2026-08-25")
        self.assertEqual(request.ticker, "BSE")
        with self.assertRaises(ValidationError):
            AnalysisRequest(ticker="INFY", trade_date="2026-08-25")

    def test_frontend_analysis_is_fixed_bse_and_dual_horizon(self):
        page = (ROOT / "frontend" / "src" / "app" / "analysis" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn('const BSE_TICKER = "BSE"', page)
        self.assertNotIn("TickerSearch", page)
        self.assertNotIn("useAnalysisStore", page)
        self.assertIn("useHorizonAnalysisStore", page)
        self.assertIn("Analyze INTRADAY + SWING", page)
        self.assertIn("INTRADAY plan", page)
        self.assertIn("SWING · MTF plan", page)
        self.assertIn("SWING · ZERODHA MTF", page)
        self.assertIn("Neither horizon may substitute for the other", page)
        self.assertIn("Analysis Date", page)
        self.assertIn("India / IST", page)

    def test_frontend_dual_horizon_client_uses_paired_backend(self):
        client = (ROOT / "frontend" / "src" / "lib" / "tradebrain-horizon-api.ts").read_text(encoding="utf-8")
        store = (ROOT / "frontend" / "src" / "lib" / "horizon-analysis-store.ts").read_text(encoding="utf-8")
        self.assertIn("/api/analysis/run-horizons", client)
        self.assertIn("/api/analysis/ws/", client)
        self.assertIn('TradeBrainHorizon = "INTRADAY" | "SWING"', client)
        self.assertIn('INTRADAY: emptyPlan("INTRADAY")', store)
        self.assertIn('SWING: emptyPlan("SWING")', store)
        self.assertIn('attachStream("INTRADAY"', store)
        self.assertIn('attachStream("SWING"', store)
        self.assertNotIn("runAnalysis(", store)

    def test_bse_decision_card_surfaces_structured_price_levels(self):
        card = (ROOT / "frontend" / "src" / "components" / "analysis" / "DecisionCard.tsx").read_text(encoding="utf-8")
        for label in ("Entry", "Stop-Loss", "Primary Target", "Gross R:R"):
            self.assertIn(label, card)
        self.assertIn("Trade Brain will not invent levels", card)

    def test_sidebar_hides_generic_ita_discovery_surface(self):
        sidebar = (ROOT / "frontend" / "src" / "components" / "layout" / "Sidebar.tsx").read_text(encoding="utf-8")
        for required in ("BSE Today", "BSE Analysis", "Price & Structure", "BSE Context", "BSE Evidence", "Actual Trades"):
            self.assertIn(required, sidebar)
        for removed in ("Top Picks", "Market Scan", "Verdict Calibration", "Shadow Trades", "AI Backtest"):
            self.assertNotIn(removed, sidebar)

    def test_frontend_route_surface_is_bse_product_only(self):
        app_root = ROOT / "frontend" / "src" / "app"
        actual = {
            path.relative_to(app_root).as_posix()
            for path in app_root.rglob("page.tsx")
        }
        expected = {
            "page.tsx",
            "analysis/page.tsx",
            "analysis/[id]/page.tsx",
            "charts/page.tsx",
            "history/page.tsx",
            "insights/page.tsx",
            "news/page.tsx",
            "settings/page.tsx",
            "trades/page.tsx",
        }
        self.assertEqual(actual, expected)
        for dead_route in (
            "backtest/page.tsx",
            "confidence-calibration/page.tsx",
            "memory-admin/page.tsx",
            "performance/page.tsx",
            "recommendations/page.tsx",
            "scanner/page.tsx",
            "shadow-trades/page.tsx",
            "signals/page.tsx",
            "simulation/page.tsx",
            "strategies/page.tsx",
            "strategies/cyclical/page.tsx",
            "strategies/support-resistance/page.tsx",
            "verdict-calibration/page.tsx",
        ):
            self.assertNotIn(dead_route, actual)


if __name__ == "__main__":
    unittest.main()
