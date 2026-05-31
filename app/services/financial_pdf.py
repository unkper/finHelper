"""PDF 上传、本地抽文本与后台解析任务。"""
import threading
from pathlib import Path
from typing import Any, Dict

from flask import current_app

from app.services.financial_ai import extract_from_financial_text
from app.services.financial_reports import (
    PARSE_STATUS_AI,
    PARSE_STATUS_EXTRACTING,
    PARSE_STATUS_DONE,
    PARSE_STATUS_FAILED,
    SOURCE_PDF,
    fetch_report_by_id,
    save_pending_analysis,
    update_parse_state,
)

MIN_EXTRACTED_CHARS = 200


def _pdf_dir() -> Path:
    path = Path(current_app.config.get("FINANCIAL_PDF_DIR", ""))
    path.mkdir(parents=True, exist_ok=True)
    return path


def pdf_path_for_report(report_id: int) -> Path:
    return _pdf_dir() / f"{report_id}.pdf"


def save_uploaded_pdf(report_id: int, file_storage) -> str:
    max_bytes = int(current_app.config.get("FINANCIAL_PDF_MAX_BYTES", 20 * 1024 * 1024))
    data = file_storage.read()
    if len(data) > max_bytes:
        raise ValueError(f"PDF 文件超过 {max_bytes // (1024 * 1024)}MB 限制")
    if not data[:4] == b"%PDF":
        raise ValueError("文件不是有效的 PDF")

    dest = pdf_path_for_report(report_id)
    dest.write_bytes(data)
    rel = str(dest)
    update_parse_state(report_id, pdf_path=rel, status="idle", progress=0, message="PDF 已上传")
    return rel


def extract_text_from_pdf(path: str) -> Dict[str, Any]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("未安装 pymupdf，请执行 pip install pymupdf") from exc

    doc = fitz.open(path)
    parts = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    text = "\n".join(parts).strip()
    return {
        "text": text,
        "page_count": len(parts),
        "char_count": len(text),
    }


def run_parse_job(app, report_id: int) -> None:
    """在后台线程中执行：抽文本 + DeepSeek Pro 结构化。"""

    def _worker():
        with app.app_context():
            _parse_report(report_id)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def _parse_report(report_id: int) -> None:
    report = fetch_report_by_id(report_id)
    if not report:
        return

    pdf_path = report.get("pdf_path")
    if not pdf_path or not Path(pdf_path).is_file():
        update_parse_state(
            report_id,
            status=PARSE_STATUS_FAILED,
            progress=0,
            error="PDF 文件不存在",
            message="解析失败",
        )
        return

    try:
        update_parse_state(
            report_id,
            status=PARSE_STATUS_EXTRACTING,
            progress=10,
            message="正在从 PDF 提取文本…",
            error=None,
        )
        extracted_meta = extract_text_from_pdf(pdf_path)
        text = extracted_meta["text"]
        if len(text) < MIN_EXTRACTED_CHARS:
            update_parse_state(
                report_id,
                status=PARSE_STATUS_FAILED,
                progress=0,
                error=(
                    f"PDF 提取文字过少（{extracted_meta['char_count']} 字符），"
                    "可能是扫描版，请改用可选取文字的 PDF 或粘贴解读文字"
                ),
                message="解析失败",
            )
            return

        update_parse_state(
            report_id,
            status=PARSE_STATUS_EXTRACTING,
            progress=40,
            message=f"已提取 {extracted_meta['page_count']} 页文本，正在 AI 结构化…",
            source_text=text,
        )

        update_parse_state(
            report_id,
            status=PARSE_STATUS_AI,
            progress=55,
            message="DeepSeek Pro 正在分析财报…",
        )

        from app.services.settings import get_ai_financial_parse_model

        result = extract_from_financial_text(
            report["ticker"],
            report["fiscal_period"],
            report["title"],
            text,
            model=get_ai_financial_parse_model(),
        )
        if result.get("error"):
            update_parse_state(
                report_id,
                status=PARSE_STATUS_FAILED,
                progress=40,
                error=result["error"],
                message="AI 分析失败",
            )
            return

        save_pending_analysis(
            report_id,
            result["extracted"],
            result.get("ai_summary"),
        )
        update_parse_state(
            report_id,
            status=PARSE_STATUS_DONE,
            progress=100,
            message="解析完成，请确认结构化结果",
        )
    except Exception as exc:
        update_parse_state(
            report_id,
            status=PARSE_STATUS_FAILED,
            progress=0,
            error=str(exc),
            message="解析失败",
        )
