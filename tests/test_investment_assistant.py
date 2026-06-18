"""投资助手删除。"""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from flask import Flask

from app.services.investment import (
    create_assistant,
    delete_assistant,
    fetch_archived_themes,
    fetch_assistant_by_id,
    fetch_assistants_with_themes,
)


class DeleteAssistantTest(unittest.TestCase):
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
        default_id = conn.execute(
            "SELECT id FROM investment_assistants WHERE is_default = 1 LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO investment_assistants (id, name, description, is_default)
            VALUES (2, '宏观助手', '测试', 0)
            """
        )
        conn.execute(
            """
            INSERT INTO themes (id, title, description, assistant_id) VALUES
            (1, '活跃主题A', 'desc', 2),
            (2, '活跃主题B', 'desc', 2),
            (3, '已封存主题', 'desc', 2)
            """
        )
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "UPDATE themes SET archived_at = ? WHERE id = 3",
            (now,),
        )
        conn.commit()
        conn.close()
        self.default_id = default_id
        self.assistant_id = 2

    def tearDown(self):
        from app.database import close_db

        close_db(None)
        self.ctx.pop()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_delete_archives_active_themes_and_removes_assistant(self):
        result = delete_assistant(self.assistant_id)
        self.assertEqual(result, ("宏观助手", 2))
        self.assertIsNone(fetch_assistant_by_id(self.assistant_id))

        archived = fetch_archived_themes()
        titles = {row["title"] for row in archived}
        self.assertIn("活跃主题A", titles)
        self.assertIn("活跃主题B", titles)
        self.assertIn("已封存主题", titles)

        groups = dict(
            (assistant["id"], themes)
            for assistant, themes in fetch_assistants_with_themes()
        )
        self.assertNotIn(self.assistant_id, groups)

    def test_archived_themes_reassigned_to_default(self):
        delete_assistant(self.assistant_id)
        archived = fetch_archived_themes()
        for row in archived:
            self.assertEqual(row["assistant_id"], self.default_id)

    def test_cannot_delete_default_assistant(self):
        self.assertFalse(delete_assistant(self.default_id))
        self.assertIsNotNone(fetch_assistant_by_id(self.default_id))

    def test_delete_missing_assistant_returns_none(self):
        self.assertIsNone(delete_assistant(9999))

    def test_delete_empty_assistant(self):
        assistant_id = create_assistant("空助手")
        result = delete_assistant(assistant_id)
        self.assertEqual(result, ("空助手", 0))
        self.assertIsNone(fetch_assistant_by_id(assistant_id))


class DeleteAssistantRouteTest(unittest.TestCase):
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
            conn = sqlite3.connect(cls.tmp.name)
            conn.execute(
                """
                INSERT INTO investment_assistants (id, name, description, is_default)
                VALUES (2, '待删助手', NULL, 0)
                """
            )
            conn.execute(
                "INSERT INTO themes (title, assistant_id) VALUES ('T1', 2)"
            )
            conn.commit()
            conn.close()

    @classmethod
    def tearDownClass(cls):
        Path(cls.tmp.name).unlink(missing_ok=True)

    def setUp(self):
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True

    def test_delete_assistant_route(self):
        rv = self.client.post("/investments/assistants/2/delete", follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        body = rv.get_data(as_text=True)
        self.assertIn("已移除", body)
        self.assertIn("1 个主题已移入回收站", body)

    def test_cannot_delete_default_via_route(self):
        rv = self.client.post("/investments/assistants/1/delete", follow_redirects=True)
        self.assertEqual(rv.status_code, 200)
        self.assertIn("默认投资助手不可移除", rv.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
