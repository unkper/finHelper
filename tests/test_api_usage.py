"""外部 API 调用统计。"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from flask import Flask

from app.services.api_usage import (
    PROVIDERS,
    fetch_usage_stats,
    infer_provider_from_url,
    record_api_call,
)


class InferProviderTest(unittest.TestCase):
    def test_eodhd(self):
        self.assertEqual(
            infer_provider_from_url("https://eodhd.com/api/real-time/AAPL.US"),
            "eodhd",
        )

    def test_alpha_vantage(self):
        self.assertEqual(
            infer_provider_from_url("https://www.alphavantage.co/query?function=GLOBAL_QUOTE"),
            "alpha_vantage",
        )

    def test_fmp(self):
        self.assertEqual(
            infer_provider_from_url("https://financialmodelingprep.com/stable/quote"),
            "fmp",
        )

    def test_unknown(self):
        self.assertIsNone(infer_provider_from_url("https://example.com/api"))


class RecordApiCallTest(unittest.TestCase):
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

    def test_same_day_accumulates(self):
        record_api_call("eodhd", 2)
        record_api_call("eodhd", 3)
        stats = fetch_usage_stats(7)
        self.assertEqual(stats["totals"]["eodhd"], 5)
        self.assertEqual(stats["today_total"], 5)

    def test_invalid_provider_ignored(self):
        record_api_call("unknown", 1)
        stats = fetch_usage_stats(7)
        self.assertEqual(stats["period_total"], 0)

    def test_fetch_usage_stats_matrix(self):
        today = date.today().isoformat()
        from app.database import get_db

        db = get_db()
        db.execute(
            "INSERT INTO api_usage_daily (usage_date, provider, call_count) VALUES (?, ?, ?)",
            (today, "fmp", 4),
        )
        db.execute(
            "INSERT INTO api_usage_daily (usage_date, provider, call_count) VALUES (?, ?, ?)",
            (today, "deepseek", 2),
        )
        db.commit()

        stats = fetch_usage_stats(7)
        self.assertIn(today, stats["dates"])
        idx = stats["dates"].index(today)
        self.assertEqual(stats["series"]["fmp"][idx], 4)
        self.assertEqual(stats["series"]["deepseek"][idx], 2)
        self.assertEqual(len(stats["providers"]), len(PROVIDERS))

    def test_old_data_retained(self):
        old = (date.today() - timedelta(days=200)).isoformat()
        from app.database import get_db

        db = get_db()
        db.execute(
            "INSERT INTO api_usage_daily (usage_date, provider, call_count) VALUES (?, ?, ?)",
            (old, "eodhd", 9),
        )
        db.commit()
        stats = fetch_usage_stats(0)
        self.assertTrue(stats["all_time"])
        self.assertIn(old, stats["dates"])
        self.assertEqual(stats["totals"]["eodhd"], 9)


class UsageStatsRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        from app import create_app

        cls.app = create_app()
        cls.app.config["DATABASE_PATH"] = cls.tmp.name
        cls.app.config["WEB_PASSWORD"] = "test"
        with cls.app.app_context():
            from app.database import init_db

            init_db()

    @classmethod
    def tearDownClass(cls):
        Path(cls.tmp.name).unlink(missing_ok=True)

    def setUp(self):
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True

    def test_usage_stats_route(self):
        rv = self.client.get("/settings/api/usage-stats?days=30")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertEqual(data["days"], 30)
        self.assertIn("series", data)
        self.assertIn("dates", data)

    def test_usage_stats_all_time(self):
        rv = self.client.get("/settings/api/usage-stats?days=0")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertTrue(data["all_time"])

    def test_settings_api_usage_tab(self):
        rv = self.client.get("/settings?tab=api-usage")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_data(as_text=True)
        self.assertIn("apiUsageChart", body)
        self.assertIn("chart-component.js", body)
        self.assertIn("SETTINGS_PAGE", body)


if __name__ == "__main__":
    unittest.main()
