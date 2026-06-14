"""价位告警：冷却配置、监控去重、批量删除。"""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services.price_monitor import _alert_is_due
from app.services.settings import (
    DEFAULT_PRICE_ALERT_COOLDOWN_HOURS,
    get_price_alert_cooldown_hours,
    set_price_alert_cooldown_hours,
)


class CooldownSettingsTest(unittest.TestCase):
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

    def test_clamp_cooldown_hours(self):
        self.assertEqual(set_price_alert_cooldown_hours(999), 168)
        self.assertEqual(set_price_alert_cooldown_hours(0), 1)
        self.assertEqual(get_price_alert_cooldown_hours(), 1)

    def test_default_cooldown(self):
        self.assertEqual(get_price_alert_cooldown_hours(), DEFAULT_PRICE_ALERT_COOLDOWN_HOURS)


class AlertIsDueTest(unittest.TestCase):
    @patch("app.services.price_monitor.get_price_alert_cooldown_hours", return_value=12)
    def test_due_when_no_prior_trigger(self, _mock):
        self.assertTrue(_alert_is_due(None))

    @patch("app.services.price_monitor.get_price_alert_cooldown_hours", return_value=12)
    def test_not_due_within_cooldown(self, _mock):
        recent = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        self.assertFalse(_alert_is_due(recent))

    @patch("app.services.price_monitor.get_price_alert_cooldown_hours", return_value=6)
    def test_due_after_cooldown(self, _mock):
        old = (datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds")
        self.assertTrue(_alert_is_due(old))


class DeletePriceAlertsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.database import init_db

        init_db()
        conn = sqlite3.connect(self.tmp.name)
        conn.execute(
            "INSERT INTO themes (id, title, assistant_id) VALUES (1, 'T', 1)"
        )
        conn.execute(
            "INSERT INTO theme_assets (id, theme_id, ticker, exchange) VALUES (1, 1, 'AAPL', 'US')"
        )
        conn.execute(
            """
            INSERT INTO theme_asset_price_alerts
            (id, asset_id, target_price, direction, alert_type)
            VALUES (1, 1, 150.0, 'above', 'price'),
                   (2, 1, 140.0, 'below', 'price'),
                   (3, 1, 130.0, 'below', 'milestone')
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_delete_only_price_alerts(self):
        from app.services.price_alerts import delete_price_alerts

        deleted = delete_price_alerts([1, 2, 3, 99])
        self.assertEqual(deleted, 2)

        conn = sqlite3.connect(self.tmp.name)
        remaining = conn.execute(
            "SELECT id, alert_type FROM theme_asset_price_alerts ORDER BY id"
        ).fetchall()
        conn.close()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0][1], "milestone")


class PriceAlertsRouteTest(unittest.TestCase):
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

    def test_price_alerts_page_redirects_to_settings_tab(self):
        rv = self.client.get("/investments/price-alerts")
        self.assertEqual(rv.status_code, 302)
        location = rv.headers.get("Location", "")
        self.assertIn("/settings", location)
        self.assertIn("tab=price-alerts", location)

    def test_settings_price_alerts_tab_renders(self):
        rv = self.client.get("/settings?tab=price-alerts")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_data(as_text=True)
        self.assertIn("价位告警管理", body)
        self.assertIn("cooldownSettingsForm", body)
        self.assertIn("PRICE_ALERTS_PAGE", body)


if __name__ == "__main__":
    unittest.main()
