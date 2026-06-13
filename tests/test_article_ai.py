"""研报 AI 归纳：summarize_article、独立存储与空摘要校验（不调用真实 DeepSeek）。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_aa = _load_module("article_ai", "app/services/article_ai.py")


class SummarizeArticleTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["DEEPSEEK_API_KEY"] = "test-key"

    def test_empty_summary_returns_error(self):
        with self.app.app_context():
            result = _aa.summarize_article("测试标题", "")
        self.assertIn("error", result)
        self.assertIn("摘要", result["error"])

    def test_whitespace_summary_returns_error(self):
        with self.app.app_context():
            result = _aa.summarize_article("测试标题", "   \n  ")
        self.assertIn("error", result)

    @patch.object(_aa, "_call_deepseek_chat")
    def test_summarize_returns_refined_text(self, mock_chat):
        mock_chat.return_value = {
            "content": "- 核心观点一\n- 关键数据二\n- 关注 NVDA 目标价 150",
        }
        with self.app.app_context():
            result = _aa.summarize_article("高盛 AI 报告", "很长的原文摘要内容…")

        self.assertEqual(result["summary"], "- 核心观点一\n- 关键数据二\n- 关注 NVDA 目标价 150")
        mock_chat.assert_called_once()
        prompt = mock_chat.call_args[0][0]
        self.assertIn("高盛 AI 报告", prompt)
        self.assertIn("很长的原文摘要内容", prompt)

    @patch.object(_aa, "_call_deepseek_chat")
    def test_summarize_propagates_api_error(self, mock_chat):
        mock_chat.return_value = {"error": "AI 服务调用失败：timeout"}
        with self.app.app_context():
            result = _aa.summarize_article("标题", "有内容的摘要")
        self.assertEqual(result["error"], "AI 服务调用失败：timeout")

    def test_not_configured_returns_error(self):
        app = Flask(__name__)
        app.config["DEEPSEEK_API_KEY"] = ""
        with app.app_context():
            result = _aa.summarize_article("标题", "摘要")
        self.assertIn("DEEPSEEK_API_KEY", result["error"])


class UpdateThemeArticleAiSummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.app.config["DEEPSEEK_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.database import get_db, init_db
        from app.services.investment import add_theme_article, update_theme_article_ai_summary

        init_db()
        db = get_db()
        assistant = db.execute(
            "SELECT id FROM investment_assistants ORDER BY id LIMIT 1"
        ).fetchone()
        assistant_id = assistant["id"]
        db.execute(
            "INSERT INTO themes (id, title, assistant_id) VALUES (1, 'Theme', ?)",
            (assistant_id,),
        )
        db.commit()
        add_theme_article(1, "报告", None, "原文摘要内容", None)
        self._get_db = get_db
        self._update_ai = update_theme_article_ai_summary

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_ai_summary_does_not_overwrite_summary(self):
        row = self._get_db().execute(
            "SELECT id FROM theme_articles WHERE theme_id = 1"
        ).fetchone()
        article_id = row["id"]
        saved = self._update_ai(1, article_id, "- 归纳要点一")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["ai_summary"], "- 归纳要点一")

        updated = self._get_db().execute(
            "SELECT summary, ai_summary FROM theme_articles WHERE id = ?",
            (article_id,),
        ).fetchone()
        self.assertEqual(updated["summary"], "原文摘要内容")
        self.assertEqual(updated["ai_summary"], "- 归纳要点一")

    def test_update_missing_article_returns_none(self):
        self.assertIsNone(self._update_ai(1, 9999, "x"))


class AiSummarizeRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.app.config["DEEPSEEK_API_KEY"] = "test-key"
        self.app.config["SECRET_KEY"] = "test"
        from app.database import close_db, get_db, init_db
        from app.routes.investments import bp

        self.app.teardown_appcontext(close_db)
        self.app.register_blueprint(bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        init_db()
        db = get_db()
        assistant = db.execute(
            "SELECT id FROM investment_assistants ORDER BY id LIMIT 1"
        ).fetchone()
        assistant_id = assistant["id"]
        db.execute(
            "INSERT INTO themes (id, title, assistant_id) VALUES (1, 'Theme', ?)",
            (assistant_id,),
        )
        db.execute(
            """
            INSERT INTO theme_articles (theme_id, title, summary, ai_summary)
            VALUES (1, '报告', '原文', '已存归纳')
            """
        )
        db.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    @patch("app.services.auth.is_authenticated", return_value=True)
    @patch("app.routes.investments.summarize_article")
    def test_ai_summarize_returns_cached_without_deepseek(self, mock_summarize, _auth):
        mock_summarize.side_effect = AssertionError("不应调用 DeepSeek")

        response = self.client.post("/investments/1/articles/1/ai-summarize")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["cached"])
        self.assertEqual(payload["refined_summary"], "已存归纳")
        self.assertEqual(payload["original_summary"], "原文")
        mock_summarize.assert_not_called()

    @patch("app.services.auth.is_authenticated", return_value=True)
    def test_apply_summary_rejects_empty_body(self, _auth):
        response = self.client.post(
            "/investments/1/articles/1/apply-summary",
            json={"ai_summary": "  "},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能为空", response.get_json()["error"])

    @patch("app.services.auth.is_authenticated", return_value=True)
    def test_apply_summary_preserves_original(self, _auth):
        response = self.client.post(
            "/investments/1/articles/1/apply-summary",
            json={"ai_summary": "新归纳"},
        )
        self.assertEqual(response.status_code, 200)

        from app.database import get_db

        row = get_db().execute(
            "SELECT summary, ai_summary FROM theme_articles WHERE id = 1"
        ).fetchone()
        self.assertEqual(row["summary"], "原文")
        self.assertEqual(row["ai_summary"], "新归纳")


if __name__ == "__main__":    unittest.main()
