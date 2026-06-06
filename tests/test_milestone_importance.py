"""时间线 AI 重要性：分数 clamp、均分、宏观回退上下文（不调用 DeepSeek）。"""
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
_mmc = _load_module("milestone_market_context", "app/services/milestone_market_context.py")


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


class EvidenceHintTest(unittest.TestCase):
    def test_macro_milestone_hint(self):
        hint = _mmc.resolve_evidence_hint(
            milestone_description="ISM 制造业 PMI 数据发布",
            theme_title="波段机会",
            articles=[{"summary": "简短"}],
        )
        self.assertEqual(hint, "macro_or_sparse")

    def test_rich_theme_hint(self):
        long_summary = "营收同比增长 12.5%，毛利率提升，验证主题逻辑。" * 3
        hint = _mmc.resolve_evidence_hint(
            milestone_description="公司财报超预期",
            theme_title="AI 算力",
            articles=[{"summary": long_summary}],
        )
        self.assertEqual(hint, "theme_rich")

    def test_extract_tokens(self):
        tokens = _mmc.extract_search_tokens("ISM 数据发布后个股分化")
        self.assertIn("ISM", tokens)


class RationaleBasisTest(unittest.TestCase):
    def test_prefix_market(self):
        out = _mmc.format_rationale_with_basis("标普走弱拖累风险偏好", "market")
        self.assertTrue(out.startswith("[大盘/宏观]"))


class BuildScoringContextTest(unittest.TestCase):
    @patch.object(_mi, "build_macro_context_block")
    @patch.object(_mi, "_build_price_dynamics", return_value=[])
    @patch.object(_mi, "fetch_milestone_by_id")
    def test_includes_macro_block(self, mock_fetch, mock_prices, mock_macro):
        mock_fetch.return_value = {
            "description": "ISM 发布",
            "event_date": "2025-01-15",
            "end_date": "2025-01-15",
            "is_completed": 1,
        }
        mock_macro.return_value = {
            "evidence_hint": "macro_or_sparse",
            "market_dynamics": [{"ticker": "SPY", "change_pct": -1.2}],
            "external_news": [{"title": "ISM 不及预期", "summary": "..."}],
            "economic_events": [],
            "eodhd_available": True,
        }
        theme_row = {"title": "波段机会", "description": "宏观驱动波段"}
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

        _mi.invalidate_scoring_context_cache(1, 2)
        with patch("app.database.get_db", return_value=mock_db):
            ctx = _mi.build_scoring_context(1, 2, use_cache=False)

        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["evidence_hint"], "macro_or_sparse")
        self.assertEqual(ctx["market_dynamics"][0]["ticker"], "SPY")
        self.assertEqual(len(ctx["external_news"]), 1)

    @patch.object(_mi, "fetch_milestone_by_id", return_value=None)
    def test_missing_milestone(self, _mock_fetch):
        self.assertIsNone(_mi.build_scoring_context(1, 99, use_cache=False))


class ScoringPromptTest(unittest.TestCase):
    def test_prompt_mentions_macro_fallback(self):
        self.assertIn("macro_or_sparse", _mi._SCORING_PROMPT)
        self.assertIn("market_dynamics", _mi._SCORING_PROMPT)


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
