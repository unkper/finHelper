"""估值 AI 参数推荐。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services.valuation_ai import _clamp, _extract_json_object, recommend_valuation_params


class ValuationAiParseTest(unittest.TestCase):
    def test_extract_json_from_fence(self):
        raw = '```json\n{"wacc": 11.5, "rationale": "test"}\n```'
        obj = _extract_json_object(raw)
        self.assertEqual(obj["wacc"], 11.5)

    def test_clamp_wacc(self):
        self.assertEqual(_clamp("wacc", 30), 25.0)
        self.assertEqual(_clamp("wacc", 4), 6.0)
        self.assertIsNone(_clamp("wacc", "bad"))


class RecommendValuationParamsTest(unittest.TestCase):
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
        extracted = {
            "currency": "USD",
            "unit": "millions",
            "periods": ["2025-Q4"],
            "kpis": {"2025-Q4": {"revenue": {"value": 100, "yoy_pct": 20}, "net_profit": {"value": 20}}},
            "income_statement": {"2025-Q4": {"revenue": 100, "net_income": 20}},
            "cash_flow": {"2025-Q4": {"operating": 18}},
            "ai_summary": "稳健增长",
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

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    @patch("app.services.valuation_ai.has_financial_ai_configured", return_value=False)
    def test_requires_ai_config(self, _mock):
        result = recommend_valuation_params(1)
        self.assertIn("error", result)

    @patch("app.services.valuation_ai.fetch_us_market_stats")
    @patch("app.services.valuation_ai.chat_completion_messages")
    @patch("app.services.valuation_ai.has_financial_ai_configured", return_value=True)
    def test_parses_and_clamps_params(self, _cfg, mock_chat, mock_stats):
        mock_stats.return_value = {
            "AAPL": {
                "price": 150.0,
                "market_cap": 3_000_000_000_000.0,
                "shares_outstanding": 20_000_000_000.0,
                "source": "fmp",
            }
        }
        mock_chat.return_value = {
            "text": json.dumps(
                {
                    "wacc": 50,
                    "optimistic_factor": 1.25,
                    "pessimistic_factor": 0.65,
                    "terminal_growth_optimistic": 3.5,
                    "terminal_growth_base": 2.5,
                    "terminal_growth_pessimistic": 2.0,
                    "rationale": "盈利期公司，增速稳健。",
                },
                ensure_ascii=False,
            )
        }
        result = recommend_valuation_params(1)
        self.assertNotIn("error", result)
        self.assertEqual(result["params"]["wacc"], 25.0)
        self.assertEqual(result["params"]["optimistic_factor"], 1.25)
        self.assertIn("rationale", result)

    @patch("app.services.valuation_ai.chat_completion_messages")
    @patch("app.services.valuation_ai.has_financial_ai_configured", return_value=True)
    def test_invalid_json_returns_error(self, _cfg, mock_chat):
        mock_chat.return_value = {"text": "not json"}
        with patch("app.services.valuation_ai.fetch_us_market_stats", return_value={}):
            result = recommend_valuation_params(1)
        self.assertEqual(result["error"], "AI 返回格式无法解析")


if __name__ == "__main__":
    unittest.main()
