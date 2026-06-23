"""投研批量 FMP 任务：候选排序、跳过已有、失败递补。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services.research_batch import plan_quarter_candidates
from app.services.research_batch_store import (
    BATCH_STATUS_DONE,
    ITEM_STATUS_FAILED,
    ITEM_STATUS_SKIPPED,
    ITEM_STATUS_SUCCESS,
    fetch_batch_job,
)


class PlanQuarterCandidatesTest(unittest.TestCase):
    def test_filters_and_sorts_quarters(self):
        dates = [
            {"year": 2024, "period": "FY"},
            {"year": 2025, "period": "Q1"},
            {"year": 2025, "period": "Q3"},
            {"year": 2024, "period": "Q4"},
        ]
        result = plan_quarter_candidates(dates)
        self.assertEqual(
            [(r["year"], r["period"]) for r in result],
            [(2025, "Q3"), (2025, "Q1"), (2024, "Q4")],
        )


class ExecuteBatchJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.database import init_db

        init_db()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    @patch("app.services.research_batch.time.sleep", return_value=None)
    @patch("app.services.research_batch.fetch_and_parse_fmp_report")
    @patch("app.services.research_batch.fetch_report_dates")
    def test_skips_existing_and_stops_at_four(
        self, mock_dates, mock_fetch, _mock_sleep
    ):
        from app.services.financial_reports import create_financial_report, save_pending_analysis
        from app.services.research_batch import _execute_batch_job
        from app.services.research_batch_store import create_batch_job

        mock_dates.return_value = [
            {"year": 2025, "period": "Q4"},
            {"year": 2025, "period": "Q3"},
            {"year": 2025, "period": "Q2"},
            {"year": 2025, "period": "Q1"},
            {"year": 2024, "period": "Q4"},
            {"year": 2024, "period": "Q3"},
            {"year": 2024, "period": "Q2"},
        ]

        create_financial_report("MU", "2025-Q3", "Existing", "", source_type="sec_fmp")

        def fake_fetch(ticker, year, period):
            mapping = {
                ("2025", "Q4"): "2025-Q3",
                ("2025", "Q3"): "2025-Q2",
                ("2025", "Q2"): "2025-Q1",
                ("2025", "Q1"): "2024-Q4",
                ("2024", "Q4"): "2024-Q3",
                ("2024", "Q3"): "2024-Q2",
            }
            if period == "Q1" and year == 2025:
                raise RuntimeError("FMP timeout")
            fp = mapping.get((str(year), period))
            if not fp:
                raise ValueError("unknown period")
            return {
                "suggested_fiscal_period": fp,
                "suggested_title": f"MU {fp}",
                "source_text_summary": "summary",
                "extracted": {
                    "periods": [fp],
                    "unit": "millions",
                    "currency": "USD",
                    "kpis": {fp: {}},
                    "income_statement": {fp: {}},
                    "balance_sheet": {fp: {}},
                    "cash_flow": {fp: {}},
                },
            }

        mock_fetch.side_effect = fake_fetch

        job_id = create_batch_job("MU", 4)
        _execute_batch_job(job_id)

        job = fetch_batch_job(job_id)
        self.assertEqual(job["status"], BATCH_STATUS_DONE)
        statuses = [item["status"] for item in job["items"]]
        self.assertIn(ITEM_STATUS_SKIPPED, statuses)
        self.assertIn(ITEM_STATUS_FAILED, statuses)
        self.assertEqual(statuses.count(ITEM_STATUS_SUCCESS), 4)
        self.assertLessEqual(len(job["items"]), 6)


if __name__ == "__main__":
    unittest.main()
