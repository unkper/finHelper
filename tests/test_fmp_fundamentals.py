"""FMP 基本面 TTM 拉取与回退。"""
import unittest
from unittest.mock import patch

from flask import Flask

from app.services.fmp_fundamentals import fetch_fundamentals_ttm, _ttm_from_extracted


class FmpFundamentalsTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["FMP_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch("app.services.fmp_fundamentals.http_get_json")
    def test_fmp_primary_source(self, mock_get):
        def side_effect(url, params):
            if "balance-sheet" in url:
                return [{"totalStockholdersEquity": 5000}]
            if "income-statement" in url:
                return [{"researchAndDevelopmentExpenses": 200, "netIncome": 800}]
            if "cash-flow" in url:
                return [{"operatingCashFlow": 900}]
            if "profile" in url:
                return [{"beta": 1.2}]
            return []

        mock_get.side_effect = side_effect
        result = fetch_fundamentals_ttm("AAPL", {})
        self.assertEqual(result["source"], "fmp")
        self.assertIsNotNone(result["equity_usd"])
        self.assertIsNotNone(result["rd_expense_usd"])
        self.assertEqual(result["beta"], 1.2)

    @patch("app.services.fmp_fundamentals._fetch_fmp_ttm")
    def test_extract_fallback_when_fmp_empty(self, mock_fmp):
        mock_fmp.return_value = {}
        chart = {
            "periods": ["2025-Q4"],
            "income_statement": {"2025-Q4": {"revenue": 100, "net_income": 20, "rd": 5}},
            "kpis": {"2025-Q4": {"revenue": {"value": 100}}},
            "balance_sheet": {"2025-Q4": {"equity": 500}},
            "cash_flow": {"2025-Q4": {"operating": 18}},
        }
        result = fetch_fundamentals_ttm("XYZ", chart)
        self.assertEqual(result["source"], "extracted")
        self.assertEqual(result["equity_usd"], 500 * 1_000_000)
        self.assertEqual(result["rd_expense_usd"], 5 * 4 * 1_000_000)

    @patch("app.services.fmp_fundamentals._fetch_fmp_ttm")
    def test_mixed_source(self, mock_fmp):
        mock_fmp.return_value = {"equity_usd": 1e9, "beta": 1.1}
        chart = {
            "periods": ["2025-Q4"],
            "income_statement": {"2025-Q4": {"net_income": 20, "rd": 3}},
            "kpis": {},
            "balance_sheet": {},
            "cash_flow": {"2025-Q4": {"operating": 18}},
        }
        result = fetch_fundamentals_ttm("MIX", chart)
        self.assertEqual(result["source"], "mixed")
        self.assertEqual(result["equity_usd"], 1e9)
        self.assertIsNotNone(result["rd_expense_usd"])


class TtmFromExtractedTest(unittest.TestCase):
    def test_single_quarter_rd_annualized(self):
        chart = {
            "periods": ["2025-Q4"],
            "income_statement": {"2025-Q4": {"revenue": 10, "net_income": 2, "rd": 1}},
            "kpis": {"2025-Q4": {"revenue": {"value": 10}}},
            "balance_sheet": {"2025-Q4": {"equity": 50}},
            "cash_flow": {"2025-Q4": {"operating": 3}},
        }
        result = _ttm_from_extracted(
            chart["periods"],
            chart["income_statement"],
            chart["kpis"],
            chart["balance_sheet"],
            chart["cash_flow"],
        )
        self.assertEqual(result["rd_expense_usd"], 4_000_000)


if __name__ == "__main__":
    unittest.main()
