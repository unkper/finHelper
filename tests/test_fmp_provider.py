"""FMP provider 单元测试。"""
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from app.services.quote_providers import fmp


class FmpProviderTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["FMP_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()
        fmp._FEATURE_COOLDOWN_UNTIL.clear()

    def tearDown(self):
        fmp._FEATURE_COOLDOWN_UNTIL.clear()
        self.ctx.pop()

    @patch.object(fmp, "_http_get_json")
    def test_fetch_us_quotes_parses_batch(self, mock_get):
        mock_get.return_value = [
            {"symbol": "AAPL", "price": 150.25},
            {"symbol": "MSFT", "price": 400.0},
        ]
        quotes = fmp.fetch_us_quotes(["AAPL", "MSFT"])
        self.assertEqual(quotes["AAPL"], 150.25)
        self.assertEqual(quotes["MSFT"], 400.0)

    @patch.object(fmp, "_http_get_json")
    def test_fetch_us_daily_series_includes_ohlc(self, mock_get):
        mock_get.return_value = [
            {
                "date": "2025-01-02",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
            }
        ]
        series = fmp.fetch_us_daily_series("AAPL")
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["close"], 10.5)
        self.assertEqual(series[0]["open"], 10.0)

    @patch.object(fmp, "_http_get_json")
    def test_fetch_stock_news_maps_fields(self, mock_get):
        mock_get.return_value = [
            {
                "symbol": "AAPL",
                "publishedDate": "2025-01-01 12:00:00",
                "title": "Apple news",
                "text": "Long body " * 50,
                "url": "https://example.com/a",
                "site": "Example",
            }
        ]
        items = fmp.fetch_stock_news("AAPL", limit=5, page=0)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Apple news")
        self.assertTrue(items[0]["summary"].endswith("…"))
        self.assertEqual(items[0]["sentiment_label"], "中性")

    @patch.object(fmp, "_http_get_json")
    def test_fetch_economic_calendar_filters_country(self, mock_get):
        mock_get.return_value = [
            {
                "date": "2025-01-05",
                "country": "US",
                "event": "Nonfarm Payrolls",
                "actual": 200,
                "estimate": 180,
                "previous": 170,
            },
            {
                "date": "2025-01-05",
                "country": "CN",
                "event": "PMI",
            },
        ]
        events = fmp.fetch_economic_calendar(
            from_date="2025-01-01",
            to_date="2025-01-10",
            country="US",
        )
        self.assertEqual(len(events), 1)
        self.assertIn("Nonfarm", events[0]["title"])
        self.assertIn("实际", events[0]["summary"])

    @patch("app.services.api_usage.record_api_call")
    def test_news_cooldown_on_403(self, _mock_record):
        with patch("app.services.quote_providers.fmp.build_opener") as mock_builder:
            import json
            from io import BytesIO
            from urllib.error import HTTPError

            class FakeResp:
                def __init__(self, payload):
                    self._payload = payload

                def read(self):
                    return json.dumps(self.payload).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            opener = mock_builder.return_value
            opener.open.side_effect = HTTPError(
                "url", 403, "Forbidden", None, BytesIO(b"")
            )
            result = fmp.fetch_stock_news("AAPL")
            self.assertEqual(result, [])
            self.assertTrue(fmp.is_news_feature_on_cooldown())


if __name__ == "__main__":
    unittest.main()
