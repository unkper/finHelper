"""投研估值计算。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services.financial_valuation import (
    _compute_ttm,
    build_valuation_payload,
    get_valuation_override,
    save_valuation_dcf_params,
    save_valuation_override,
)


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
        result = build_valuation_payload("AAPL", chart, market, None)
        self.assertEqual(result["stage"], "profitable")
        self.assertEqual(result["primary_metric"], "PE")
        self.assertEqual(result["multiples"]["ps"], 1000.0)
        self.assertEqual(result["multiples"]["pe"], 5000.0)
        self.assertAlmostEqual(result["multiples"]["peg"], 200.0, places=1)

    def test_pre_profit_uses_ps(self):
        chart = _chart_payload_single_q(revenue=100.0, net_income=-5.0, yoy=30.0)
        market = {"price": 10.0, "market_cap": 200_000_000_000.0, "source": "fmp"}
        result = build_valuation_payload("XYZ", chart, market, None)
        self.assertEqual(result["stage"], "pre_profit")
        self.assertEqual(result["primary_metric"], "PS")
        self.assertIsNone(result["multiples"]["pe"])

    def test_manual_override_priority(self):
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 100.0, "source": "fmp"}
        override = {"market_cap": 500_000_000_000.0, "dcf_params": {}}
        result = build_valuation_payload("AAPL", chart, market, override)
        self.assertEqual(result["market"]["source"], "manual")
        self.assertEqual(result["market"]["market_cap"], 500_000_000_000.0)

    def test_dcf_scenario_order(self):
        chart = _chart_payload_single_q()
        market = {"price": 10.0, "market_cap": 400_000_000_000.0, "shares_outstanding": 1_000_000_000.0}
        result = build_valuation_payload("AAPL", chart, market, None)
        scenarios = result["dcf"]["scenarios"]
        self.assertEqual(len(scenarios), 3)
        prices = [s["implied_price"] for s in scenarios if s.get("implied_price")]
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_missing_market_cap_warning(self):
        result = build_valuation_payload("AAPL", _chart_payload_single_q(), {}, None)
        self.assertIn("缺少市值", " ".join(result["warnings"]))


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
        save_valuation_dcf_params(1, {"wacc": 11.5, "optimistic_factor": 1.2})
        row = get_valuation_override(1)
        self.assertEqual(row["dcf_params"]["wacc"], 11.5)
        self.assertEqual(row["dcf_params"]["optimistic_factor"], 1.2)


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

    @patch("app.routes.investments.fetch_us_market_stats")
    def test_chart_data_includes_valuation(self, mock_stats):
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
