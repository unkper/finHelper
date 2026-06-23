"""10-K Word 补充合并进 structured 数据。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


class MergeWordSupplementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.app.config["DEEPSEEK_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.database import init_db

        init_db()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    @patch("app.services.financial_ai._call_deepseek_chat")
    def test_merge_appends_events_and_summary(self, mock_chat):
        from app.services.financial_ai import merge_word_supplement
        from app.services.financial_reports import (
            create_financial_report,
            get_pending_extracted,
            save_financial_report_analysis,
            save_pending_analysis,
        )

        extracted = {
            "currency": "USD",
            "unit": "millions",
            "periods": ["2025-Q2"],
            "kpis": {"2025-Q2": {"revenue": {"value": 9301.0}}},
            "income_statement": {"2025-Q2": {"revenue": 9301.0, "net_income": 1885.0}},
            "balance_sheet": {"2025-Q2": {}},
            "cash_flow": {"2025-Q2": {}},
            "ai_summary": "Base summary.",
            "material_events": [],
            "red_flags": [],
        }
        mock_chat.return_value = {
            "content": json.dumps(
                {
                    "material_events": [
                        {
                            "type": "loss",
                            "title": "Facility impairment",
                            "amount_millions": 120,
                            "period": "2025-Q2",
                            "description": "One-time write-down disclosed in 10-K.",
                        }
                    ],
                    "red_flags": [{"code": "capex", "message": "Elevated capex may pressure FCF."}],
                    "ai_summary_addendum": "10-K highlights higher NAND capex and China export controls.",
                }
            )
        }

        result = merge_word_supplement(
            extracted,
            "Word body " * 80,
            ticker="MU",
            fiscal_period="2025-Q2",
            model="deepseek-chat",
        )
        self.assertEqual(result["status"], "ok")
        merged = result["extracted"]
        self.assertTrue(merged.get("filing_meta", {}).get("word_supplement"))
        self.assertIn("Facility impairment", merged["material_events"][0]["title"])
        self.assertIn("10-K Word 补充", merged["ai_summary"])
        self.assertEqual(merged["income_statement"]["2025-Q2"]["revenue"], 9301.0)

        report_id = create_financial_report("MU", "2025-Q2", "Test", "src")
        save_financial_report_analysis(report_id, extracted, "Base summary.")
        save_pending_analysis(report_id, merged, merged.get("ai_summary"))
        pending = get_pending_extracted(report_id)
        self.assertIn("Facility impairment", pending["material_events"][0]["title"])


if __name__ == "__main__":
    unittest.main()
