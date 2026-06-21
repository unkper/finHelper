"""SEC Excel 上传、解析与后台任务。"""
import threading
from typing import Any, Dict

from flask import current_app

from app.services.financial_reports import (
    PARSE_STATUS_DONE,
    PARSE_STATUS_FAILED,
    PARSE_STATUS_EXTRACTING,
    SOURCE_SEC_XLS,
    fetch_report_by_id,
    get_report_pdf_blob,
    save_pending_analysis,
    save_report_pdf_blob,
    update_financial_report_meta,
    update_parse_state,
)
from app.services.sec_filing_parser import parse_sec_filing

ALLOWED_EXTENSIONS = (".xls", ".xlsx")


def _validate_extension(filename: str) -> str:
    lower = (filename or "").lower()
    for ext in ALLOWED_EXTENSIONS:
        if lower.endswith(ext):
            return ext
    raise ValueError("仅支持 SEC Excel（.xls / .xlsx）")


def save_uploaded_sec_xls(report_id: int, file_storage) -> None:
    max_bytes = int(current_app.config.get("FINANCIAL_PDF_MAX_BYTES", 50 * 1024 * 1024))
    filename = file_storage.filename or "filing.xls"
    _validate_extension(filename)
    data = file_storage.read()
    if len(data) > max_bytes:
        raise ValueError(f"文件超过 {max_bytes // (1024 * 1024)}MB 限制")
    if len(data) < 100:
        raise ValueError("文件过小，不是有效的 Excel 财报")

    save_report_pdf_blob(report_id, data)
    update_parse_state(report_id, status="idle", progress=0, message="SEC Excel 已上传")


def parse_sec_bytes(
    data: bytes,
    filename: str = "",
    *,
    ticker: str | None = None,
) -> Dict[str, Any]:
    return parse_sec_filing(data, filename, ticker=ticker)


def run_sec_parse_job(app, report_id: int) -> None:
    def _worker():
        with app.app_context():
            _parse_report_sec(report_id)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def _parse_report_sec(report_id: int) -> None:
    report = fetch_report_by_id(report_id)
    if not report:
        return

    blob = get_report_pdf_blob(report_id)
    if not blob:
        update_parse_state(
            report_id,
            status=PARSE_STATUS_FAILED,
            progress=0,
            error="SEC Excel 文件不存在",
            message="解析失败",
        )
        return

    try:
        update_parse_state(
            report_id,
            status=PARSE_STATUS_EXTRACTING,
            progress=20,
            message="正在解析 SEC Excel…",
            error=None,
        )
        result = parse_sec_filing(
            blob,
            filename=report.get("title") or f"report_{report_id}.xls",
            ticker=report.get("ticker"),
        )
        extracted = result["extracted"]
        if not extracted.get("periods"):
            raise ValueError("未能识别有效财季与三表数据")

        meta_updates = {}
        if result.get("suggested_fiscal_period"):
            meta_updates["fiscal_period"] = result["suggested_fiscal_period"]
        if result.get("suggested_report_date"):
            meta_updates["report_date"] = result["suggested_report_date"]
        if result.get("suggested_title") and not report.get("title"):
            meta_updates["title"] = result["suggested_title"]
        if meta_updates:
            update_financial_report_meta(report_id, **meta_updates)

        save_pending_analysis(
            report_id,
            extracted,
            extracted.get("ai_summary") or None,
        )
        update_parse_state(
            report_id,
            status=PARSE_STATUS_DONE,
            progress=100,
            message="SEC 解析完成，请确认结构化结果",
            source_text=result.get("source_text_summary") or "",
        )
    except Exception as exc:
        update_parse_state(
            report_id,
            status=PARSE_STATUS_FAILED,
            progress=0,
            error=str(exc),
            message="SEC 解析失败",
        )
