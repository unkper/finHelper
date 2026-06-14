"""财报 AI 答疑：上下文组装、提问与路由。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.services.financial_qa import (
    PRESET_QUESTIONS,
    ask_report_question,
    build_report_qa_context,
    get_preset_question,
    trim_session_messages,
)


class TrimSessionMessagesTest(unittest.TestCase):
    def test_trims_to_six(self):
        messages = [{"role": "user", "content": f"q{i}"} for i in range(10)]
        trimmed = trim_session_messages(messages)
        self.assertEqual(len(trimmed), 6)
        self.assertEqual(trimmed[0]["content"], "q4")


class PresetQuestionsTest(unittest.TestCase):
    def test_get_preset_question(self):
        self.assertIn("基本面", get_preset_question("fundamentals") or "")
        self.assertIsNone(get_preset_question("unknown"))
        self.assertEqual(len(PRESET_QUESTIONS), 2)


class BuildReportQaContextTest(unittest.TestCase):
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

    def test_missing_report_returns_none(self):
        self.assertIsNone(build_report_qa_context(999))

    def test_source_text_only_context(self):
        from app.services.financial_reports import create_financial_report

        report_id = create_financial_report(
            "AAPL",
            "2026-Q1",
            "Test",
            source_text="Revenue grew 10% to $100M.",
        )
        context = build_report_qa_context(report_id)
        self.assertIsNotNone(context)
        self.assertEqual(context["ticker"], "AAPL")
        self.assertIn("source_text_excerpt", context)

    def test_empty_report_returns_none(self):
        from app.database import get_db

        db = get_db()
        db.execute(
            """
            INSERT INTO financial_reports
            (ticker, fiscal_period, title, source_text, source_type, parse_status, parse_progress)
            VALUES ('AAPL', '2026-Q1', 'Empty', '', 'paste', 'idle', 0)
            """
        )
        db.commit()
        report_id = db.execute("SELECT id FROM financial_reports").fetchone()["id"]
        self.assertIsNone(build_report_qa_context(report_id))


class AskReportQuestionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.app = Flask(__name__)
        self.app.config["DATABASE_PATH"] = self.tmp.name
        self.app.config["DEEPSEEK_API_KEY"] = "test-key"
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.database import init_db

        init_db()
        from app.services.financial_reports import create_financial_report

        self.report_id = create_financial_report(
            "NVDA",
            "2026-Q1",
            "NVDA Q1",
            source_text="Data center revenue was strong.",
        )

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    @patch("app.services.financial_qa.chat_completion_messages")
    def test_ask_includes_question_in_messages(self, mock_chat):
        mock_chat.return_value = {"text": "基本面稳健。"}
        result = ask_report_question(self.report_id, "公司基本面如何？")
        self.assertEqual(result.get("answer"), "基本面稳健。")
        mock_chat.assert_called_once()
        messages = mock_chat.call_args[0][0]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("NVDA", messages[0]["content"])
        self.assertEqual(messages[-1]["content"], "公司基本面如何？")

    @patch("app.services.financial_qa.chat_completion_messages")
    def test_session_messages_forwarded(self, mock_chat):
        mock_chat.return_value = {"text": "跟进回答"}
        history = [
            {"role": "user", "content": "第一个问题"},
            {"role": "assistant", "content": "第一个回答"},
        ]
        ask_report_question(self.report_id, "第二个问题", history)
        messages = mock_chat.call_args[0][0]
        self.assertEqual(messages[-3]["content"], "第一个问题")
        self.assertEqual(messages[-2]["content"], "第一个回答")
        self.assertEqual(messages[-1]["content"], "第二个问题")

    def test_empty_question_error(self):
        result = ask_report_question(self.report_id, "   ")
        self.assertIn("error", result)


class ResearchAskRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp.close()
        from app import create_app

        cls.app = create_app()
        cls.app.config["DATABASE_PATH"] = cls.tmp.name
        cls.app.config["WEB_PASSWORD"] = "test"
        cls.app.config["DEEPSEEK_API_KEY"] = "test-key"
        with cls.app.app_context():
            from app.database import init_db
            from app.services.financial_reports import create_financial_report

            init_db()
            cls.report_id = create_financial_report(
                "MSFT",
                "2026-Q1",
                "MSFT Q1",
                source_text="Cloud revenue increased.",
            )

    @classmethod
    def tearDownClass(cls):
        Path(cls.tmp.name).unlink(missing_ok=True)

    def setUp(self):
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True

    def test_ask_route_not_found(self):
        rv = self.client.post(
            "/investments/research/reports/99999/ask",
            json={"question": "test"},
        )
        self.assertEqual(rv.status_code, 404)

    @patch("app.services.financial_qa.chat_completion_messages")
    def test_ask_route_success(self, mock_chat):
        mock_chat.return_value = {"text": "回答内容"}
        rv = self.client.post(
            f"/investments/research/reports/{self.report_id}/ask",
            json={"question": "风险有哪些？"},
        )
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["answer"], "回答内容")

    @patch("app.services.financial_qa.chat_completion_messages")
    def test_ask_route_preset(self, mock_chat):
        mock_chat.return_value = {"text": "预设回答"}
        rv = self.client.post(
            f"/investments/research/reports/{self.report_id}/ask",
            json={"preset_id": "fundamentals"},
        )
        self.assertEqual(rv.status_code, 200)
        data = rv.get_json()
        self.assertEqual(data["preset_id"], "fundamentals")

    def test_ask_route_empty_question(self):
        rv = self.client.post(
            f"/investments/research/reports/{self.report_id}/ask",
            json={"question": ""},
        )
        self.assertEqual(rv.status_code, 400)


if __name__ == "__main__":
    unittest.main()
