"""监控标的财经新闻。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services.quote_providers import eodhd
from app.services.stock_news import (
    fetch_ticker_news,
    list_news_tickers,
)


class ListNewsTickersTest(unittest.TestCase):
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
        assistant_id = conn.execute(
            "SELECT id FROM investment_assistants LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO themes (id, title, assistant_id) VALUES (1, 'T1', ?), (2, 'T2', ?)",
            (assistant_id, assistant_id),
        )
        conn.execute(
            """
            INSERT INTO theme_assets (id, theme_id, ticker, exchange) VALUES
            (1, 1, 'AAPL', 'US'),
            (2, 2, 'AAPL', 'US'),
            (3, 1, '0700', 'HK')
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_us_only_and_deduped(self):
        tickers = list_news_tickers()
        self.assertEqual(len(tickers), 1)
        self.assertEqual(tickers[0]["ticker"], "AAPL")
        self.assertEqual(len(tickers[0]["themes"]), 2)


class FetchTickerNewsCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.app.config["EODHD_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.database import init_db

        init_db()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    @patch("app.services.stock_news.translate_news_items", side_effect=lambda items: items)
    @patch.object(eodhd, "is_news_feature_on_cooldown", return_value=False)
    @patch.object(eodhd, "fetch_financial_news")
    def test_cache_avoids_repeat_fetch(self, mock_fetch, _cooldown, _translate):
        mock_fetch.return_value = [
            {
                "date": "2026-01-01T10:00:00+00:00",
                "title": "Apple news",
                "summary": "Summary",
                "link": "https://example.com",
                "tags": [],
                "sentiment_label": "中性",
            }
        ]
        items1, _, _ = fetch_ticker_news("AAPL", offset=0, limit=20)
        items2, _, _ = fetch_ticker_news("AAPL", offset=0, limit=20)
        self.assertEqual(len(items1), 1)
        self.assertEqual(len(items2), 1)
        mock_fetch.assert_called_once()

    @patch("app.services.stock_news.translate_news_items", side_effect=lambda items: items)
    @patch.object(eodhd, "is_news_feature_on_cooldown", return_value=False)
    @patch.object(eodhd, "fetch_financial_news")
    def test_force_refresh_bypasses_cache(self, mock_fetch, _cooldown, _translate):
        mock_fetch.return_value = []
        fetch_ticker_news("AAPL", offset=0, limit=20)
        fetch_ticker_news("AAPL", offset=0, limit=20, force_refresh=True)
        self.assertEqual(mock_fetch.call_count, 2)


class FetchFinancialNewsOffsetTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["EODHD_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch.object(eodhd, "_http_get_json", return_value=[])
    @patch.object(eodhd, "is_news_feature_on_cooldown", return_value=False)
    def test_offset_passed_to_api(self, _cooldown, mock_http):
        eodhd.fetch_financial_news(symbol="AAPL", limit=10, offset=20)
        params = mock_http.call_args[0][1]
        self.assertEqual(params["offset"], "20")
        self.assertEqual(params["limit"], "10")


class NewsRouteTest(unittest.TestCase):
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

    def test_news_page_renders(self):
        rv = self.client.get("/investments/news")
        self.assertEqual(rv.status_code, 200)
        body = rv.get_data(as_text=True)
        self.assertIn("监控标的新闻", body)
        self.assertIn("STOCK_NEWS_PAGE", body)

    @patch.object(eodhd, "has_api_key", return_value=False)
    def test_feed_without_key_returns_503(self, _mock_key):
        rv = self.client.get("/investments/news/api/feed?ticker=AAPL")
        self.assertEqual(rv.status_code, 503)


if __name__ == "__main__":
    unittest.main()
