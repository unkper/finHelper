"""投研估值计算。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services.financial_valuation import (
    _capitalize_rd,
    _compute_ttm,
    _implied_price_at_wacc,
    build_valuation_payload,
    get_valuation_override,
    save_valuation_dcf_params,
    save_valuation_override,
    solve_implied_wacc,
)

EMPTY_FUNDAMENTALS = {
    "source": "none",
    "equity_usd": None,
    "rd_expense_usd": None,
    "net_income_usd": None,
    "operating_cf_usd": None,
    "beta": None,
    "total_debt_usd": None,
}


def _build_payload(*args, **kwargs):
    with patch(
        "app.services.financial_valuation.fetch_fundamentals_ttm",
        return_value=dict(EMPTY_FUNDAMENTALS),
    ):
        return build_valuation_payload(*args, **kwargs)


def _chart_payload_single_q(revenue=100.0, net_income=20.0, yoy=25.0):
    return {
        "periods": ["2025-Q4"],
        "focus_period": "2025-Q4",
        "income_statement": {
            "2025-Q4": {"revenue": revenue, "net_income": net_income},
        },
        "kpis": {
            "2025-Q4": {
                "revenue": {"value": revenue, "yoy_pct": yoy},
                "net_profit": {"value": net_income, "yoy_pct": yoy},
            },
        },
        "cash_flow": {"2025-Q4": {"operating": 18.0}},
    }


def _chart_payload_four_q():
    periods = ["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"]
    income = {p: {"revenue": 25.0, "net_income": 5.0} for p in periods}
    kpis = {
        p: {"revenue": {"value": 25.0, "yoy_pct": 20.0}, "net_profit": {"value": 5.0}}
        for p in periods
    }
    return {
        "periods": periods,
        "focus_period": "2024-Q4",
        "income_statement": income,
        "kpis": kpis,
        "cash_flow": {p: {"operating": 4.0} for p in periods},
    }


class TtmTest(unittest.TestCase):
    def test_single_quarter_annualized(self):
        ttm = _compute_ttm(
            ["2025-Q4"],
            {"2025-Q4": {"revenue": 100.0, "net_income": 10.0}},
            {"2025-Q4": {"revenue": {"value": 100.0}}},
        )
        self.assertEqual(ttm["method"], "annualized_single_q")
        self.assertEqual(ttm["revenue_millions"], 400.0)
        self.assertEqual(ttm["net_income_millions"], 40.0)

    def test_four_quarters_summed(self):
        payload = _chart_payload_four_q()
        ttm = _compute_ttm(
            payload["periods"],
            payload["income_statement"],
            payload["kpis"],
        )
        self.assertEqual(ttm["method"], "sum_last_4q")
        self.assertEqual(ttm["revenue_millions"], 100.0)
        self.assertEqual(ttm["net_income_millions"], 20.0)


class BuildValuationPayloadTest(unittest.TestCase):
    def test_profitable_pe_ps_peg(self):
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 400_000_000_000.0, "shares_outstanding": 1_000_000_000.0, "source": "fmp"}
        result = _build_payload("AAPL", chart, market, None)
        self.assertEqual(result["stage"], "profitable")
        self.assertEqual(result["primary_metric"], "PE")
        self.assertEqual(result["multiples"]["ps"], 1000.0)
        self.assertEqual(result["multiples"]["pe"], 5000.0)
        self.assertAlmostEqual(result["multiples"]["peg"], 200.0, places=1)

    def test_pre_profit_uses_ps(self):
        chart = _chart_payload_single_q(revenue=100.0, net_income=-5.0, yoy=30.0)
        market = {"price": 10.0, "market_cap": 200_000_000_000.0, "source": "fmp"}
        result = _build_payload("XYZ", chart, market, None)
        self.assertEqual(result["stage"], "pre_profit")
        self.assertEqual(result["primary_metric"], "PS")
        self.assertIsNone(result["multiples"]["pe"])

    def test_manual_override_priority(self):
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 100.0, "source": "fmp"}
        override = {"market_cap": 500_000_000_000.0, "dcf_params": {}}
        result = _build_payload("AAPL", chart, market, override)
        self.assertEqual(result["market"]["source"], "manual")
        self.assertEqual(result["market"]["market_cap"], 500_000_000_000.0)

    def test_derives_shares_from_market_cap_and_price(self):
        chart = _chart_payload_single_q()
        market = {"price": 100.0, "market_cap": 1_000_000_000_000.0, "source": "fmp"}
        result = _build_payload("AAPL", chart, market, None)
        self.assertEqual(result["market"]["shares"], 10_000_000_000.0)
        self.assertTrue(result["dcf"]["scenarios"][0].get("implied_price"))

    def test_dcf_scenario_order(self):
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 400_000_000_000.0, "shares_outstanding": 1_000_000_000.0}
        result = _build_payload("AAPL", chart, market, None)
        scenarios = result["dcf"]["scenarios"]
        self.assertEqual(len(scenarios), 3)
        prices = [s["implied_price"] for s in scenarios if s.get("implied_price")]
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_missing_market_cap_warning(self):
        result = _build_payload("AAPL", _chart_payload_single_q(), {}, None)
        self.assertIn("缺少市值", " ".join(result["warnings"]))


class SolveImpliedWaccTest(unittest.TestCase):
    def test_round_trip_near_known_wacc(self):
        fcf_usd = 5_000_000_000.0
        growth = 15.0
        terminal = 3.0
        shares = 1_000_000_000.0
        wacc = 12.0
        price = _implied_price_at_wacc(fcf_usd, growth, wacc, terminal, shares)
        self.assertIsNotNone(price)
        implied = solve_implied_wacc(fcf_usd, growth, terminal, shares, price)
        self.assertIsNotNone(implied)
        self.assertAlmostEqual(implied, wacc, delta=0.15)

    def test_missing_shares_unavailable(self):
        chart = _chart_payload_single_q()
        market = {"price": 100.0, "market_cap": None, "source": "fmp"}
        result = _build_payload("AAPL", chart, market, None)
        implied = result["implied_wacc"]
        self.assertFalse(implied["available"])
        self.assertIn("股本", implied["reason"])

    def test_implied_wacc_in_payload_when_available(self):
        chart = _chart_payload_single_q()
        market = {
            "price": 150.0,
            "market_cap": 3_000_000_000_000.0,
            "shares_outstanding": 20_000_000_000.0,
            "source": "fmp",
        }
        result = _build_payload("AAPL", chart, market, None)
        implied = result["implied_wacc"]
        self.assertIn("available", implied)
        if implied["available"]:
            self.assertIsNotNone(implied["value"])
            self.assertEqual(implied["scenario"], "base")


class DataGapsTest(unittest.TestCase):
    def test_lists_missing_market_cap(self):
        result = _build_payload("AAPL", _chart_payload_single_q(), {}, None)
        gaps = result.get("data_gaps") or {}
        self.assertTrue(gaps.get("has_gaps"))
        cap = next(i for i in gaps["items"] if i["id"] == "market_cap")
        self.assertEqual(cap["status"], "missing")
        self.assertIn("FMP", cap["action"])

    def test_single_quarter_marked_partial(self):
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 400_000_000_000.0, "shares_outstanding": 1_000_000_000.0}
        result = _build_payload("AAPL", chart, market, None)
        quarters = next(i for i in result["data_gaps"]["items"] if i["id"] == "quarters")
        self.assertEqual(quarters["status"], "partial")
        self.assertIn("×4", quarters["detail"])

    def test_negative_fcf_marked_partial(self):
        chart = _chart_payload_single_q()
        chart["cash_flow"] = {"2025-Q4": {"operating": -50.0}}
        market = {"price": 10.0, "market_cap": 400_000_000_000.0, "shares_outstanding": 1_000_000_000.0}
        result = _build_payload("AAOI", chart, market, None)
        fcf_item = next(i for i in result["data_gaps"]["items"] if i["id"] == "fcf")
        self.assertEqual(fcf_item["status"], "partial")
        model_item = next(i for i in result["data_gaps"]["items"] if i["id"] == "valuation_model")
        self.assertEqual(model_item["status"], "partial")


class RdCapDamodaranRimTest(unittest.TestCase):
    def test_capitalize_rd_adjusts_fcf(self):
        adj = _capitalize_rd(
            rd_expense_usd=100.0,
            net_income_usd=200.0,
            fcf_usd=150.0,
            equity_usd=1000.0,
            rd_capitalize=True,
            rd_amort_years=5,
        )
        self.assertTrue(adj["rd_capitalized"])
        self.assertAlmostEqual(adj["adjusted_fcf_usd"], 150 + 100 - 20, places=2)
        self.assertAlmostEqual(adj["adjusted_equity_usd"], 1000 + 80, places=2)

    @patch("app.services.financial_valuation.fetch_fundamentals_ttm")
    def test_survival_rate_lowers_implied_price(self, mock_fund):
        mock_fund.return_value = dict(EMPTY_FUNDAMENTALS)
        chart = _chart_payload_single_q()
        market = {
            "price": 10.0,
            "market_cap": 400_000_000_000.0,
            "shares_outstanding": 1_000_000_000.0,
        }
        high = _build_payload("AAPL", chart, market, {"dcf_params": {"survival_rate": 1.0}})
        low = _build_payload("AAPL", chart, market, {"dcf_params": {"survival_rate": 0.7}})
        high_base = next(s for s in high["damodaran"]["scenarios"] if s["name"] == "base")
        low_base = next(s for s in low["damodaran"]["scenarios"] if s["name"] == "base")
        self.assertGreater(high_base["implied_price"], low_base["implied_price"])

    @patch("app.services.financial_valuation.fetch_fundamentals_ttm")
    def test_rim_missing_equity_empty(self, mock_fund):
        mock_fund.return_value = dict(EMPTY_FUNDAMENTALS)
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 400_000_000_000.0, "shares_outstanding": 1_000_000_000.0}
        result = _build_payload("AAPL", chart, market, {"dcf_params": {"valuation_model": "rim"}})
        self.assertEqual(result["valuation_model"], "rim")
        self.assertEqual(result["rim"]["scenarios"], [])
        self.assertEqual(result["dcf"], result["rim"])

    @patch("app.services.financial_valuation.fetch_fundamentals_ttm")
    def test_rim_with_equity_scenario_order(self, mock_fund):
        mock_fund.return_value = {
            **EMPTY_FUNDAMENTALS,
            "equity_usd": 50_000_000_000.0,
            "net_income_usd": 8_000_000_000.0,
            "source": "fmp",
        }
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 400_000_000_000.0, "shares_outstanding": 1_000_000_000.0}
        result = _build_payload("AAPL", chart, market, {"dcf_params": {"valuation_model": "rim"}})
        prices = [s["implied_price"] for s in result["rim"]["scenarios"] if s.get("implied_price")]
        self.assertEqual(prices, sorted(prices, reverse=True))

    @patch("app.services.financial_valuation.fetch_fundamentals_ttm")
    def test_dcf_mirrors_active_model(self, mock_fund):
        mock_fund.return_value = dict(EMPTY_FUNDAMENTALS)
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 400_000_000_000.0, "shares_outstanding": 1_000_000_000.0}
        dam = _build_payload("AAPL", chart, market, {"dcf_params": {"valuation_model": "damodaran"}})
        rim = _build_payload("AAPL", chart, market, {"dcf_params": {"valuation_model": "rim", "cost_of_equity": 11}})
        self.assertEqual(dam["dcf"], dam["damodaran"])
        self.assertEqual(rim["dcf"], rim["rim"])


class ValuationOverrideDbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.database import init_db

        init_db()
        import sqlite3

        conn = sqlite3.connect(self.tmp.name)
        conn.execute(
            """
            INSERT INTO financial_reports (id, ticker, fiscal_period, title, source_text)
            VALUES (1, 'AAPL', '2025-Q4', 'T', 'text')
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_save_and_load_override(self):
        save_valuation_override(1, market_cap=1e11, shares_outstanding=5e9)
        row = get_valuation_override(1)
        self.assertEqual(row["market_cap"], 1e11)
        self.assertEqual(row["shares_outstanding"], 5e9)

    def test_save_dcf_params(self):
        save_valuation_dcf_params(
            1,
            {
                "wacc": 11.5,
                "optimistic_factor": 1.2,
                "valuation_model": "rim",
                "survival_rate": 0.9,
                "rd_capitalize": False,
                "rd_amort_years": 7,
            },
        )
        row = get_valuation_override(1)
        self.assertEqual(row["dcf_params"]["wacc"], 11.5)
        self.assertEqual(row["dcf_params"]["valuation_model"], "rim")
        self.assertEqual(row["dcf_params"]["survival_rate"], 0.9)
        self.assertFalse(row["dcf_params"]["rd_capitalize"])
        self.assertEqual(row["dcf_params"]["rd_amort_years"], 7)


class ChartDataIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        from unittest.mock import patch

        with patch("flask_apscheduler.scheduler.APScheduler.init_app"), patch(
            "flask_apscheduler.scheduler.APScheduler.start"
        ):
            from app import create_app

            cls.app = create_app()
        cls.app.config["DATABASE_PATH"] = cls.tmp.name
        cls.app.config["WEB_PASSWORD"] = "test"
        with cls.app.app_context():
            from app.database import init_db

            init_db()
            import sqlite3

            conn = sqlite3.connect(cls.tmp.name)
            extracted = {
                "currency": "USD",
                "unit": "millions",
                "periods": ["2025-Q4"],
                "kpis": {"2025-Q4": {"revenue": {"value": 100, "yoy_pct": 20}, "net_profit": {"value": 20}}},
                "income_statement": {"2025-Q4": {"revenue": 100, "net_income": 20}},
                "cash_flow": {"2025-Q4": {"operating": 18}},
            }
            conn.execute(
                """
                INSERT INTO financial_reports
                    (id, ticker, fiscal_period, title, source_text, extracted_json)
                VALUES (1, 'AAPL', '2025-Q4', 'T', 'text', ?)
                """,
                (json.dumps(extracted, ensure_ascii=False),),
            )
            conn.commit()
            conn.close()

    @classmethod
    def tearDownClass(cls):
        Path(cls.tmp.name).unlink(missing_ok=True)

    def setUp(self):
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True

    @patch("app.services.financial_valuation.fetch_fundamentals_ttm")
    @patch("app.routes.investments.fetch_us_market_stats")
    def test_chart_data_includes_valuation(self, mock_stats, mock_fund):
        mock_fund.return_value = dict(EMPTY_FUNDAMENTALS)
        mock_stats.return_value = {
            "AAPL": {
                "price": 150.0,
                "market_cap": 3_000_000_000_000.0,
                "shares_outstanding": 20_000_000_000.0,
                "source": "fmp",
            }
        }
        rv = self.client.get("/investments/research/reports/1/chart-data")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertIn("valuation", data)
        self.assertEqual(data["valuation"]["stage"], "profitable")
        self.assertIsNotNone(data["valuation"]["multiples"]["pe"])


if __name__ == "__main__":
    unittest.main()
