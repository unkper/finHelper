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
    @patch("app.services.news_translate.is_translation_available", return_value=False)
    def test_no_package_returns_unchanged(self, _mock_avail):
        items = [{"title": "Hello", "summary": "World"}]
        self.assertEqual(translate_news_items(items), items)

    @patch("app.services.news_translate._ensure_en_zh_package", return_value=True)
    @patch("app.services.news_translate._translate_texts")
    @patch("app.services.news_translate.is_translation_available", return_value=True)
    def test_translates_english_items(self, _mock_avail, mock_translate, _mock_pkg):
        mock_translate.return_value = ["苹果新闻", "摘要"]
        items = [{"title": "Apple news", "summary": "Summary"}]
        result = translate_news_items(items)
        self.assertEqual(result[0]["title"], "苹果新闻")
        self.assertEqual(result[0]["summary"], "摘要")
        self.assertTrue(result[0].get("translated"))
        mock_translate.assert_called_once_with(["Apple news", "Summary"])

    @patch("app.services.news_translate._translate_texts")
    @patch("app.services.news_translate.is_translation_available", return_value=True)
    def test_chinese_items_skip_api_call(self, _mock_avail, mock_translate):
        items = [{"title": "苹果公司财报", "summary": "业绩超预期"}]
        result = translate_news_items(items)
        self.assertEqual(result, items)
        mock_translate.assert_not_called()

    @patch("app.services.news_translate._translate_texts", return_value=["Apple news", "Summary"])
    @patch("app.services.news_translate.is_translation_available", return_value=True)
    def test_failed_translation_keeps_original(self, _mock_avail, _mock_translate):
        items = [{"title": "Apple news", "summary": "Summary"}]
        result = translate_news_items(items)
        self.assertEqual(result[0]["title"], "Apple news")
        self.assertFalse(result[0].get("translated"))


class EnsureEnZhPackageTest(unittest.TestCase):
    def setUp(self):
        import app.services.news_translate as mod
        mod._package_ready = None

    def tearDown(self):
        import app.services.news_translate as mod
        mod._package_ready = None

    @patch("app.services.news_translate._is_package_installed", return_value=True)
    def test_skips_download_when_installed(self, _mock_installed):
        from app.services.news_translate import _ensure_en_zh_package

        self.assertTrue(_ensure_en_zh_package())

    @patch("app.services.news_translate._is_package_installed", return_value=False)
    def test_returns_false_when_import_missing(self, _mock_installed):
        from app.services import news_translate as mod

        mod._package_ready = None
        with patch.dict("sys.modules", {"argostranslate.package": None}):
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError(name)),
            ):
                self.assertFalse(mod._ensure_en_zh_package())


if __name__ == "__main__":
    unittest.main()
