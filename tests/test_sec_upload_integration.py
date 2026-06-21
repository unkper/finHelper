"""SEC 上传集成测试。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sec" / "mu_10q.xls"


@unittest.skipUnless(FIXTURE.is_file(), "缺少 MU 10-Q fixture")
class UploadSecIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        with patch("flask_apscheduler.scheduler.APScheduler.init_app"), patch(
            "flask_apscheduler.scheduler.APScheduler.start"
        ):
            from app import create_app

            cls.app = create_app()
        cls.app.config["DATABASE_PATH"] = cls.tmp.name
        cls.app.config["WEB_PASSWORD"] = "test"

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

    def test_upload_sec_creates_pending(self):
        with open(FIXTURE, "rb") as fh:
            data = {
                "ticker": "MU",
                "file": (fh, "mu_10q.xls"),
            }
            res = self.client.post(
                "/investments/research/reports/upload-sec",
                data=data,
                content_type="multipart/form-data",
            )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertIn("report_id", body)
        report_id = body["report_id"]

        pending = self.client.get(f"/investments/research/reports/{report_id}/pending-extracted")
        self.assertEqual(pending.status_code, 200)
        payload = pending.get_json()
        self.assertIn("extracted", payload)
        self.assertEqual(payload["extracted"]["filing_meta"]["form_type"], "10-Q")
        self.assertEqual(body["suggested"]["fiscal_period"], "2025-Q2")


if __name__ == "__main__":
    unittest.main()
