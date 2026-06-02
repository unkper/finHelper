"""时间线 AI 重要性：分数 clamp、均分逻辑、上下文构建（不调用 DeepSeek）。"""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mi = _load_module("milestone_importance", "app/services/milestone_importance.py")


class ClampScoreTest(unittest.TestCase):
    def test_clamp_in_range(self):
        self.assertEqual(_mi.clamp_importance_score(7.55), 7.5)
        self.assertEqual(_mi.clamp_importance_score(-1), 0.0)
        self.assertEqual(_mi.clamp_importance_score(15), 10.0)

    def test_clamp_invalid(self):
        self.assertIsNone(_mi.clamp_importance_score("x"))


class TruncateTest(unittest.TestCase):
    def test_truncate_short(self):
        self.assertEqual(_mi._truncate("abc", 10), "abc")

    def test_truncate_long(self):
        self.assertEqual(_mi._truncate("abcdefghij", 5), "abcd…")


class BuildScoringContextTest(unittest.TestCase):
    @patch.object(_mi, "_build_price_dynamics", return_value=[])
    @patch.object(_mi, "fetch_milestone_by_id")
    def test_includes_theme_and_milestone(self, mock_fetch, mock_prices):
        mock_fetch.return_value = {
            "description": "产品发布",
            "event_date": "2025-01-15",
            "end_date": "2025-01-15",
            "is_completed": 1,
        }
        theme_row = {"title": "AI 主题", "description": "长期看好"}
        article_row = {
            "title": "研报",
            "summary": "利好",
            "created_at": "2025-02-01",
        }
        mock_db = MagicMock()
        mock_db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=theme_row)),
            MagicMock(fetchall=MagicMock(return_value=[article_row])),
        ]

        with patch("app.database.get_db", return_value=mock_db):
            ctx = _mi.build_scoring_context(1, 2)

        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["theme"]["title"], "AI 主题")
        self.assertEqual(ctx["milestone"]["description"], "产品发布")
        self.assertEqual(len(ctx["articles"]), 1)
        self.assertEqual(ctx["articles"][0]["title"], "研报")
        mock_prices.assert_called_once_with(1, "2025-01-15")

    @patch.object(_mi, "fetch_milestone_by_id", return_value=None)
    def test_missing_milestone(self, _mock_fetch):
        self.assertIsNone(_mi.build_scoring_context(1, 99))


class FetchThemeScoreTest(unittest.TestCase):
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
            """
            INSERT INTO theme_milestones
            (theme_id, event_date, description, importance_score, importance_status)
            VALUES (1, '2025-01-01', 'a', 8.0, 'done'),
                   (1, '2025-02-01', 'b', 6.0, 'done'),
                   (1, '2025-03-01', 'c', NULL, 'idle')
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_average_importance_score(self):
        from app.services.investment import fetch_theme_score

        result = fetch_theme_score(1)
        self.assertEqual(result["scored_milestones"], 2)
        self.assertAlmostEqual(result["theme_score"], 7.0)


if __name__ == "__main__":
    unittest.main()
