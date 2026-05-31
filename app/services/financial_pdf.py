"""PDF 上传、内存抽文本与后台解析任务。"""
import threading
from typing import Any, Dict, Union

from flask import current_app

from app.services.financial_ai import extract_from_financial_text
from app.services.financial_reports import (
    PARSE_STATUS_AI,
    PARSE_STATUS_EXTRACTING,
    PARSE_STATUS_DONE,
    PARSE_STATUS_FAILED,
    fetch_report_by_id,
    get_report_pdf_blob,
    get_report_source_text,
    save_pending_analysis,
    save_report_pdf_blob,
    update_parse_state,
)

MIN_EXTRACTED_CHARS = 200


def save_uploaded_pdf(report_id: int, file_storage) -> None:
    max_bytes = int(current_app.config.get("FINANCIAL_PDF_MAX_BYTES", 50 * 1024 * 1024))
    data = file_storage.read()
    if len(data) > max_bytes:
        raise ValueError(f"PDF 文件超过 {max_bytes // (1024 * 1024)}MB 限制")
    if not data[:4] == b"%PDF":
        raise ValueError("文件不是有效的 PDF")

    save_report_pdf_blob(report_id, data)
    update_parse_state(report_id, status="idle", progress=0, message="PDF 已上传")


def extract_text_from_pdf(source: Union[bytes, str]) -> Dict[str, Any]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("未安装 pymupdf，请执行 pip install pymupdf") from exc

    if isinstance(source, bytes):
        doc = fitz.open(stream=source, filetype="pdf")
    else:
        doc = fitz.open(source)
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


def run_text_analyze_job(app, report_id: int) -> None:
    """在后台线程中执行：粘贴原文 → DeepSeek Pro 结构化 → pending_extracted_json。"""

    def _worker():
        with app.app_context():
            _analyze_report_text(report_id)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def _analyze_report_text(report_id: int) -> None:
    report = fetch_report_by_id(report_id)
    if not report:
        return

    source_text = get_report_source_text(report_id)
    if not source_text:
        update_parse_state(
            report_id,
            status=PARSE_STATUS_FAILED,
            progress=0,
            error="原文为空，请先粘贴或保存财报解读文字",
            message="分析失败",
        )
        return

    try:
        update_parse_state(
            report_id,
            status=PARSE_STATUS_AI,
            progress=20,
            message="DeepSeek 正在分析财报…",
            error=None,
        )

        from app.services.settings import get_ai_financial_parse_model

        result = extract_from_financial_text(
            report["ticker"],
            report["fiscal_period"],
            report["title"],
            source_text,
            model=get_ai_financial_parse_model(),
        )
        if result.get("error"):
            update_parse_state(
                report_id,
                status=PARSE_STATUS_FAILED,
                progress=20,
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
            message="分析完成，请确认结构化结果",
        )
    except Exception as exc:
        update_parse_state(
            report_id,
            status=PARSE_STATUS_FAILED,
            progress=0,
            error=str(exc),
            message="分析失败",
        )


def _parse_report(report_id: int) -> None:
    report = fetch_report_by_id(report_id)
    if not report:
        return

    if not report.get("has_pdf"):
        update_parse_state(
            report_id,
            status=PARSE_STATUS_FAILED,
            progress=0,
            error="PDF 不存在",
            message="解析失败",
        )
        return

    pdf_bytes = get_report_pdf_blob(report_id)
    if not pdf_bytes:
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
        extracted_meta = extract_text_from_pdf(pdf_bytes)
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
