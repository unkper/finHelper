"""分级通知 digest 单元测试。"""
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from app.services.notification import (
    PRIORITY_EARNINGS,
    PRIORITY_MACD,
    PRIORITY_MILESTONE_ADVANCE,
    PRIORITY_MILESTONE_DAY,
    PRIORITY_PRICE,
    AlertEvent,
    CollectResult,
    build_digest,
    run_monitor_digest,
)


class BuildDigestTest(unittest.TestCase):
    def test_priority_order(self):
        events = [
            AlertEvent(PRIORITY_EARNINGS, "earnings", "E5", ("A",)),
            AlertEvent(PRIORITY_MACD, "macd", "M2", ("B",)),
            AlertEvent(PRIORITY_PRICE, "price", "P0", ("C",)),
            AlertEvent(PRIORITY_MILESTONE_DAY, "milestone_day", "D1", ("D",)),
            AlertEvent(PRIORITY_MILESTONE_ADVANCE, "milestone_advance", "A3", ("E",)),
        ]
        digest, omitted = build_digest(events)
        self.assertEqual(omitted, 0)
        idx_p0 = digest.index("P0")
        idx_p1 = digest.index("P1")
        idx_p2 = digest.index("P2")
        idx_p3 = digest.index("P3")
        idx_p5 = digest.index("P5")
        self.assertLess(idx_p0, idx_p1)
        self.assertLess(idx_p1, idx_p2)
        self.assertLess(idx_p2, idx_p3)
        self.assertLess(idx_p3, idx_p5)


class RunMonitorDigestTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["FEISHU_ALERT_RECEIVER_ID"] = "test-receiver"
        self.app.config["FEISHU_ALERT_RECEIVER_TYPE"] = "open_id"
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch("app.services.notification.get_db")
    @patch("app.services.notification.push_feishu_message", return_value=False)
    @patch("app.services.earnings_monitor.collect_earnings_alerts")
    @patch("app.services.macd_monitor.collect_macd_alerts")
    @patch("app.services.monitor.collect_milestone_alerts")
    @patch("app.services.price_monitor.collect_price_alerts")
    def test_push_failure_does_not_apply_marks(
        self,
        mock_price,
        mock_milestone,
        mock_macd,
        mock_earnings,
        _mock_push,
        mock_get_db,
    ):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        applied = {"called": False}

        def apply_marks():
            applied["called"] = True

        mock_price.return_value = CollectResult(
            events=[AlertEvent(PRIORITY_PRICE, "price", "body", ())],
            apply_marks=apply_marks,
        )
        mock_milestone.return_value = CollectResult()
        mock_macd.return_value = CollectResult()
        mock_earnings.return_value = CollectResult()

        run_monitor_digest()
        self.assertFalse(applied["called"])
        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()

    @patch("app.services.notification.get_db")
    @patch("app.services.notification.push_feishu_message", return_value=True)
    @patch("app.services.earnings_monitor.collect_earnings_alerts")
    @patch("app.services.macd_monitor.collect_macd_alerts")
    @patch("app.services.monitor.collect_milestone_alerts")
    @patch("app.services.price_monitor.collect_price_alerts")
    def test_push_success_applies_marks(
        self,
        mock_price,
        mock_milestone,
        mock_macd,
        mock_earnings,
        _mock_push,
        mock_get_db,
    ):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        applied = {"called": False}

        def apply_marks():
            applied["called"] = True

        mock_price.return_value = CollectResult(
            events=[AlertEvent(PRIORITY_PRICE, "price", "body", ())],
            apply_marks=apply_marks,
        )
        mock_milestone.return_value = CollectResult()
        mock_macd.return_value = CollectResult()
        mock_earnings.return_value = CollectResult()

        run_monitor_digest()
        self.assertTrue(applied["called"])
        mock_db.commit.assert_called_once()

    @patch("app.services.notification.push_feishu_message", return_value=True)
    @patch("app.services.earnings_monitor.collect_earnings_alerts")
    @patch("app.services.macd_monitor.collect_macd_alerts")
    @patch("app.services.monitor.collect_milestone_alerts")
    @patch("app.services.price_monitor.collect_price_alerts")
    def test_empty_events_no_push(
        self,
        mock_price,
        mock_milestone,
        mock_macd,
        mock_earnings,
        mock_push,
    ):
        mock_price.return_value = CollectResult()
        mock_milestone.return_value = CollectResult()
        mock_macd.return_value = CollectResult()
        mock_earnings.return_value = CollectResult()

        run_monitor_digest()
        mock_push.assert_not_called()

    @patch("app.services.features.is_earnings_enabled", return_value=False)
    def test_earnings_collector_skipped_when_disabled(self, _mock_enabled):
        from app.services.earnings_monitor import collect_earnings_alerts

        result = collect_earnings_alerts()
        self.assertEqual(result.events, [])


if __name__ == "__main__":
    unittest.main()
