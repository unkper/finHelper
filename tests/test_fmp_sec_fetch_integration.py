"""FMP fetch-fmp 集成测试（mock HTTP）。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FIXTURE_JSON = Path(__file__).resolve().parent / "fixtures" / "fmp" / "mu_2025_q3.json"
FIXTURE_DATES = Path(__file__).resolve().parent / "fixtures" / "fmp" / "mu_dates.json"


@unittest.skipUnless(FIXTURE_JSON.is_file() and FIXTURE_DATES.is_file(), "缺少 FMP fixtures")
class FetchFmpIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        cls.fmp_json = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
        cls.fmp_dates = json.loads(FIXTURE_DATES.read_text(encoding="utf-8"))
        with patch("flask_apscheduler.scheduler.APScheduler.init_app"), patch(
            "flask_apscheduler.scheduler.APScheduler.start"
        ):
            from app import create_app

            cls.app = create_app()
        cls.app.config["DATABASE_PATH"] = cls.tmp.name
        cls.app.config["WEB_PASSWORD"] = "test"
        cls.app.config["FMP_API_KEY"] = "test-key"

    @classmethod
    def tearDownClass(cls):
        Path(cls.tmp.name).unlink(missing_ok=True)

    def setUp(self):
        with self.app.app_context():
            from app.database import init_db

            init_db()
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True

    def _mock_http(self, url, params):
        if "financial-reports-dates" in url:
            return self.fmp_dates
        if "financial-reports-json" in url:
            return self.fmp_json
        return None

    def test_fetch_fmp_creates_pending(self):
        with patch("app.services.fmp_sec_reports.http_get_json", side_effect=self._mock_http):
            res = self.client.post(
                "/investments/research/reports/fetch-fmp",
                json={"ticker": "MU", "year": 2025, "period": "Q3"},
            )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertIn("report_id", body)
        report_id = body["report_id"]
        self.assertEqual(body["suggested"]["fiscal_period"], "2025-Q2")

        pending = self.client.get(f"/investments/research/reports/{report_id}/pending-extracted")
        self.assertEqual(pending.status_code, 200)
        payload = pending.get_json()
        self.assertEqual(payload["extracted"]["filing_meta"]["source"], "sec_fmp")

    def test_fmp_periods_list(self):
        with patch("app.services.fmp_sec_reports.http_get_json", side_effect=self._mock_http):
            res = self.client.get("/investments/research/reports/fmp-periods?ticker=MU")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["ticker"], "MU")
        self.assertTrue(len(body["periods"]) >= 1)
        first = body["periods"][0]
        self.assertIn("year", first)
        self.assertIn("period", first)
        self.assertIn("label", first)


if __name__ == "__main__":
    unittest.main()
