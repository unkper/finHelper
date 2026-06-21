"""监控标的财经新闻。"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services.quote_providers import eodhd, fmp
from app.services.stock_news import (
    _parse_cache_payload,
    _read_cache_entry,
    _write_cache,
    fetch_ticker_news,
    list_news_tickers,
)

SAMPLE_ITEM = {
    "date": "2026-01-01T10:00:00+00:00",
    "title": "Apple news",
    "summary": "Summary",
    "link": "https://example.com",
    "tags": [],
    "sentiment_label": "中性",
}


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


class CachePayloadTest(unittest.TestCase):
    def test_legacy_list_is_translated(self):
        items, translated = _parse_cache_payload([SAMPLE_ITEM])
        self.assertEqual(len(items), 1)
        self.assertTrue(translated)

    def test_wrapper_respects_translated_flag(self):
        items, translated = _parse_cache_payload({"items": [SAMPLE_ITEM], "translated": False})
        self.assertEqual(len(items), 1)
        self.assertFalse(translated)


class FetchTickerNewsCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.app.config["FMP_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.database import init_db

        init_db()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    @patch.object(fmp, "is_news_feature_on_cooldown", return_value=False)
    @patch.object(fmp, "fetch_stock_news")
    def test_cache_avoids_repeat_fetch(self, mock_fetch, _cooldown):
        mock_fetch.return_value = [SAMPLE_ITEM]
        items1, _, meta1 = fetch_ticker_news("AAPL", offset=0, limit=20)
        items2, _, meta2 = fetch_ticker_news("AAPL", offset=0, limit=20)
        self.assertEqual(len(items1), 1)
        self.assertEqual(len(items2), 1)
        self.assertTrue(meta1["translated"])
        self.assertTrue(meta2["translated"])
        mock_fetch.assert_called_once()

    @patch.object(fmp, "is_news_feature_on_cooldown", return_value=False)
    @patch.object(fmp, "fetch_stock_news")
    def test_force_refresh_bypasses_cache(self, mock_fetch, _cooldown):
        mock_fetch.return_value = []
        fetch_ticker_news("AAPL", offset=0, limit=20)
        fetch_ticker_news("AAPL", offset=0, limit=20, force_refresh=True)
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("app.services.stock_news._schedule_translation", return_value=True)
    @patch("app.services.stock_news.is_translation_available", return_value=True)
    @patch.object(fmp, "is_news_feature_on_cooldown", return_value=False)
    @patch.object(fmp, "fetch_stock_news")
    def test_async_translation_returns_immediately(self, mock_fetch, _cooldown, _avail, _schedule):
        mock_fetch.return_value = [SAMPLE_ITEM]
        items, _, meta = fetch_ticker_news(
            "AAPL",
            offset=0,
            limit=20,
            app=self.app,
        )
        self.assertEqual(len(items), 1)
        self.assertFalse(meta["translated"])
        self.assertTrue(meta["translating"])
        _schedule.assert_called_once()

    @patch("app.services.stock_news.is_translation_available", return_value=True)
    @patch.object(fmp, "is_news_feature_on_cooldown", return_value=False)
    def test_legacy_cache_treated_as_translated(self, _cooldown, _avail):
        cache_key = "AAPL:0:20::"
        db = __import__("app.database", fromlist=["get_db"]).get_db()
        db.execute(
            """
            INSERT INTO stock_news_cache (cache_key, payload_json, fetched_at)
            VALUES (?, ?, ?)
            """,
            (
                cache_key,
                json.dumps([SAMPLE_ITEM], ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        db.commit()

        entry = _read_cache_entry(cache_key)
        self.assertIsNotNone(entry)
        items, translated, _fetched_at = entry
        self.assertEqual(len(items), 1)
        self.assertTrue(translated)

        items, _, meta = fetch_ticker_news("AAPL", offset=0, limit=20, app=self.app)
        self.assertEqual(len(items), 1)
        self.assertTrue(meta["translated"])
        self.assertFalse(meta["translating"])

    @patch("app.services.stock_news._schedule_translation", return_value=True)
    @patch("app.services.stock_news.is_translation_available", return_value=True)
    @patch.object(fmp, "is_news_feature_on_cooldown", return_value=False)
    def test_untranslated_cache_schedules_translation(self, _cooldown, _avail, schedule):
        cache_key = "AAPL:0:20::"
        _write_cache(cache_key, [SAMPLE_ITEM], translated=False)
        items, _, meta = fetch_ticker_news("AAPL", offset=0, limit=20, app=self.app)
        self.assertEqual(len(items), 1)
        self.assertFalse(meta["translated"])
        self.assertTrue(meta["translating"])
        schedule.assert_called_once()

    @patch.object(fmp, "is_news_feature_on_cooldown", return_value=False)
    @patch.object(fmp, "fetch_stock_news", return_value=[])
    @patch.object(eodhd, "is_news_feature_on_cooldown", return_value=False)
    @patch.object(eodhd, "fetch_financial_news")
    def test_falls_back_to_eodhd(self, mock_eodhd, _eod_cool, _fmp_fetch, _fmp_cool):
        self.app.config["EODHD_API_KEY"] = "eod-key"
        mock_eodhd.return_value = [SAMPLE_ITEM]
        items, _, _meta = fetch_ticker_news("AAPL", offset=0, limit=20)
        self.assertEqual(len(items), 1)
        mock_eodhd.assert_called_once()


class FetchStockNewsPageTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["FMP_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    @patch.object(fmp, "_http_get_json", return_value=[])
    @patch.object(fmp, "is_news_feature_on_cooldown", return_value=False)
    def test_page_derived_from_offset(self, _cooldown, mock_http):
        fmp.fetch_stock_news("AAPL", limit=10, page=2)
        params = mock_http.call_args[0][1]
        self.assertEqual(params["page"], "2")
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

    @patch.object(fmp, "has_api_key", return_value=False)
    @patch.object(eodhd, "has_api_key", return_value=False)
    def test_feed_without_key_returns_503(self, _eod, _fmp):
        rv = self.client.get("/investments/news/api/feed?ticker=AAPL")
        self.assertEqual(rv.status_code, 503)

    @patch("app.services.stock_news._schedule_translation", return_value=True)
    @patch("app.services.stock_news.is_translation_available", return_value=True)
    @patch.object(fmp, "is_news_feature_on_cooldown", return_value=False)
    @patch.object(fmp, "fetch_stock_news")
    def test_feed_includes_translation_flags(self, mock_fetch, _cooldown, _avail, _schedule):
        self.app.config["FMP_API_KEY"] = "test-key"
        mock_fetch.return_value = [SAMPLE_ITEM]
        rv = self.client.get("/investments/news/api/feed?ticker=AAPL")
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertFalse(data["translated"])
        self.assertTrue(data["translating"])


if __name__ == "__main__":
    unittest.main()
