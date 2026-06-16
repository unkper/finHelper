"""财经新闻自动翻译。"""
import unittest
from unittest.mock import patch

from app.services.news_translate import needs_translation, translate_news_items


class NeedsTranslationTest(unittest.TestCase):
    def test_english_needs_translation(self):
        self.assertTrue(needs_translation("Apple reports strong earnings"))

    def test_chinese_skips(self):
        self.assertFalse(needs_translation("苹果公司发布强劲财报"))

    def test_empty_skips(self):
        self.assertFalse(needs_translation(""))
        self.assertFalse(needs_translation("   "))


class TranslateNewsItemsTest(unittest.TestCase):
    @patch("app.services.news_translate.has_financial_ai_configured", return_value=False)
    def test_no_ai_returns_unchanged(self, _mock_ai):
        items = [{"title": "Hello", "summary": "World"}]
        self.assertEqual(translate_news_items(items), items)

    @patch("app.services.news_translate.chat_completion_messages")
    @patch("app.services.news_translate.has_financial_ai_configured", return_value=True)
    def test_translates_english_items(self, _mock_ai, mock_chat):
        mock_chat.return_value = {
            "text": '[{"index": 0, "title": "苹果新闻", "summary": "摘要"}]',
        }
        items = [{"title": "Apple news", "summary": "Summary"}]
        result = translate_news_items(items)
        self.assertEqual(result[0]["title"], "苹果新闻")
        self.assertEqual(result[0]["summary"], "摘要")
        self.assertTrue(result[0].get("translated"))
        mock_chat.assert_called_once()

    @patch("app.services.news_translate.chat_completion_messages")
    @patch("app.services.news_translate.has_financial_ai_configured", return_value=True)
    def test_chinese_items_skip_api_call(self, _mock_ai, mock_chat):
        items = [{"title": "苹果公司财报", "summary": "业绩超预期"}]
        result = translate_news_items(items)
        self.assertEqual(result, items)
        mock_chat.assert_not_called()

    @patch("app.services.news_translate.chat_completion_messages", return_value={"error": "fail"})
    @patch("app.services.news_translate.has_financial_ai_configured", return_value=True)
    def test_api_error_returns_original(self, _mock_ai, _mock_chat):
        items = [{"title": "Apple news", "summary": "Summary"}]
        self.assertEqual(translate_news_items(items), items)


if __name__ == "__main__":
    unittest.main()
