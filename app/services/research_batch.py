"""投研批量 FMP 拉取：最近 N 季 10-Q，跳过已有、失败递补。"""
import threading
import time
from typing import Any, Dict, List

from flask import current_app

from app.services.financial_reports import (
    PARSE_STATUS_DONE,
    SOURCE_SEC_FMP,
    create_financial_report,
    report_exists,
    save_pending_analysis,
    update_parse_state,
)
from app.services.fmp_sec_reports import fetch_and_parse_fmp_report, fetch_report_dates
from app.services.research_batch_store import (
    BATCH_STATUS_DONE,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_RUNNING,
    ITEM_STATUS_FAILED,
    ITEM_STATUS_SKIPPED,
    ITEM_STATUS_SUCCESS,
    add_batch_job_item,
    create_batch_job,
    fetch_batch_job,
    update_batch_job,
    update_batch_job_item,
)

_QUARTER_ORDER = {"Q4": 4, "Q3": 3, "Q2": 2, "Q1": 1}
_FETCH_DELAY_SEC = 0.5


def plan_quarter_candidates(dates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """仅 Q1–Q4，按财年+季度新→旧排序。"""
    rows = [
        row for row in dates
        if str(row.get("period") or "").upper() in _QUARTER_ORDER
    ]
    rows.sort(
        key=lambda r: (int(r["year"]), _QUARTER_ORDER[str(r["period"]).upper()]),
        reverse=True,
    )
    return rows


def start_batch_job(app, ticker: str, target_count: int = 4) -> int:
    job_id = create_batch_job(ticker, target_count)
    thread = threading.Thread(
        target=_run_batch_job,
        args=(app, job_id),
        daemon=True,
    )
    thread.start()
    return job_id


def _run_batch_job(app, job_id: int) -> None:
    with app.app_context():
        _execute_batch_job(job_id)


def _execute_batch_job(job_id: int) -> None:
    job = fetch_batch_job(job_id)
    if not job:
        return

    ticker = job["ticker"]
    target_count = int(job["target_count"])
    update_batch_job(
        job_id,
        status=BATCH_STATUS_RUNNING,
        progress=0,
        message="正在获取 FMP 报告期列表…",
        error=None,
    )

    try:
        dates = fetch_report_dates(ticker)
        candidates = plan_quarter_candidates(dates)
        if not candidates:
            update_batch_job(
                job_id,
                status=BATCH_STATUS_FAILED,
                message="无可用 10-Q 报告期",
                error="FMP 未返回季度报告",
            )
            return
    except Exception as exc:
        update_batch_job(
            job_id,
            status=BATCH_STATUS_FAILED,
            message="获取报告期失败",
            error=str(exc),
        )
        return

    success_new = 0
    total_tried = 0
    for candidate in candidates:
        if success_new >= target_count:
            break

        fmp_year = int(candidate["year"])
        fmp_period = str(candidate["period"]).upper()
        item_id = add_batch_job_item(job_id, fmp_year, fmp_period)
        total_tried += 1

        update_batch_job(
            job_id,
            progress=min(99, int(success_new / target_count * 100)),
            message=f"正在处理 FY{fmp_year} {fmp_period}…",
        )

        try:
            preview = fetch_and_parse_fmp_report(ticker, fmp_year, fmp_period)
            fiscal_period = preview.get("suggested_fiscal_period")
            if not fiscal_period:
                raise ValueError("无法解析日历季")

            if report_exists(ticker, fiscal_period):
                update_batch_job_item(
                    item_id,
                    status=ITEM_STATUS_SKIPPED,
                    fiscal_period=fiscal_period,
                    error="报告已存在",
                )
                continue

            report_id = create_financial_report(
                ticker,
                fiscal_period,
                preview.get("suggested_title") or f"{ticker} {fiscal_period} FMP",
                preview.get("source_text_summary") or "",
                preview.get("suggested_report_date"),
                source_type=SOURCE_SEC_FMP,
            )
            save_pending_analysis(
                report_id,
                preview["extracted"],
                preview["extracted"].get("ai_summary") or None,
            )
            update_parse_state(
                report_id,
                status=PARSE_STATUS_DONE,
                progress=100,
                message="FMP 解析完成，请确认结构化结果",
                source_text=preview.get("source_text_summary") or "",
            )
            update_batch_job_item(
                item_id,
                status=ITEM_STATUS_SUCCESS,
                fiscal_period=fiscal_period,
                report_id=report_id,
            )
            success_new += 1
        except Exception as exc:
            update_batch_job_item(
                item_id,
                status=ITEM_STATUS_FAILED,
                error=str(exc),
            )

        time.sleep(_FETCH_DELAY_SEC)

    final_status = BATCH_STATUS_DONE if success_new > 0 else BATCH_STATUS_FAILED
    update_batch_job(
        job_id,
        status=final_status,
        progress=100,
        message=(
            f"完成：新建 {success_new} 份，尝试 {total_tried} 个期次"
            if success_new > 0
            else f"未新建报告（尝试 {total_tried} 个期次）"
        ),
        error=None if success_new > 0 else "全部失败或均已存在",
    )
