"""10-K Word (.docx) 正文抽取。"""
import io
import tempfile
import unittest
from pathlib import Path

from flask import Flask


def _make_docx_bytes(paragraphs):
    from docx import Document

    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class ExtractTextFromDocxTest(unittest.TestCase):
    def test_extracts_paragraphs(self):
        from app.services.financial_docx import extract_text_from_docx

        data = _make_docx_bytes(
            [
                "Micron Technology, Inc.",
                "Annual Report on Form 10-K",
                "Risk Factors: memory pricing volatility may impact margins.",
                "Item 7. Management's Discussion and Analysis of Financial Condition.",
            ]
            + [f"Supplement paragraph {i} with operational detail." for i in range(20)]
        )
        result = extract_text_from_docx(data)
        self.assertGreaterEqual(result["char_count"], 200)
        self.assertIn("Risk Factors", result["text"])
        self.assertIn("Management's Discussion", result["text"])


class SaveUploadedDocxSupplementTest(unittest.TestCase):
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

    def test_rejects_short_text(self):
        from app.services.financial_docx import save_uploaded_docx_supplement
        from app.services.financial_reports import create_financial_report

        report_id = create_financial_report("AAPL", "2025-Q4", "Test", "body")
        data = _make_docx_bytes(["short"])

        class FakeUpload:
            filename = "10k.docx"

            def read(self):
                return data

        with self.assertRaises(ValueError):
            save_uploaded_docx_supplement(report_id, FakeUpload())

    def test_saves_supplement_text(self):
        from app.services.financial_docx import save_uploaded_docx_supplement
        from app.services.financial_reports import (
            create_financial_report,
            get_report_supplement_text,
        )

        report_id = create_financial_report("AAPL", "2025-Q4", "Test", "body")
        long_text = " ".join(["Annual report narrative section."] * 40)
        data = _make_docx_bytes([long_text])

        class FakeUpload:
            filename = "aapl_10k.docx"

            def read(self):
                return data

        result = save_uploaded_docx_supplement(report_id, FakeUpload())
        self.assertGreaterEqual(result["char_count"], 200)
        stored = get_report_supplement_text(report_id)
        self.assertIn("Annual report narrative", stored)


if __name__ == "__main__":
    unittest.main()
