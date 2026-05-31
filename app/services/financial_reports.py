"""投研财报分析报告 CRUD。"""
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.database import get_db
from app.services.financial_period import normalize_fiscal_period

# 列表/详情元数据查询不 SELECT pdf_blob，避免分页时加载大文件
_REPORT_LIST_COLUMNS = """
    id, ticker, fiscal_period, report_date, title, source_text,
    extracted_json, ai_summary, theme_id, source_type, pdf_path,
    parse_status, parse_progress, parse_message, parse_error,
    pending_extracted_json, created_at, updated_at,
    (pdf_blob IS NOT NULL) AS has_pdf_blob
"""

PARSE_STATUS_IDLE = "idle"
PARSE_STATUS_EXTRACTING = "extracting_text"
PARSE_STATUS_AI = "ai_analyzing"
PARSE_STATUS_DONE = "done"
PARSE_STATUS_FAILED = "failed"

SOURCE_PASTE = "paste"
SOURCE_PDF = "pdf"
REPORTS_PAGE_SIZE = 5


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_extracted(raw: str | None) -> Dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _row_get(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _report_row_has_pdf(row) -> bool:
    if _row_get(row, "pdf_blob") is not None:
        return True
    if _row_get(row, "has_pdf_blob"):
        return True
    return bool(_row_get(row, "pdf_path"))


def serialize_report(row) -> Dict[str, Any]:
    extracted = _parse_extracted(row["extracted_json"])
    pending = _parse_extracted(_row_get(row, "pending_extracted_json"))
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "fiscal_period": row["fiscal_period"],
        "report_date": row["report_date"],
        "title": row["title"],
        "source_text": row["source_text"] or "",
        "source_type": _row_get(row, "source_type", SOURCE_PASTE),
        "pdf_path": _row_get(row, "pdf_path"),
        "has_pdf": _report_row_has_pdf(row),
        "parse_status": _row_get(row, "parse_status", PARSE_STATUS_IDLE),
        "parse_progress": int(_row_get(row, "parse_progress") or 0),
        "parse_message": _row_get(row, "parse_message") or "",
        "parse_error": _row_get(row, "parse_error"),
        "extracted": extracted,
        "pending_extracted": pending,
        "has_pending": pending is not None,
        "has_analysis": extracted is not None,
        "ai_summary": row["ai_summary"],
        "theme_id": row["theme_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_all_reports(ticker: str | None = None) -> List[Dict[str, Any]]:
    db = get_db()
    if ticker:
        rows = db.execute(
            f"""
            SELECT {_REPORT_LIST_COLUMNS} FROM financial_reports
            WHERE ticker = ?
            ORDER BY updated_at DESC, fiscal_period DESC
            """,
            (ticker.strip().upper(),),
        ).fetchall()
    else:
        rows = db.execute(
            f"""
            SELECT {_REPORT_LIST_COLUMNS} FROM financial_reports
            ORDER BY updated_at DESC, fiscal_period DESC
            """
        ).fetchall()
    return [serialize_report(row) for row in rows]


def _reports_where_clause(
    ticker: str | None,
    search: str | None,
) -> tuple[str, list[Any]]:
    conditions = ["1=1"]
    params: list[Any] = []
    if ticker:
        conditions.append("ticker = ?")
        params.append(ticker.strip().upper())
    term = (search or "").strip()
    if term:
        like = f"%{term.upper()}%"
        conditions.append(
            "(UPPER(ticker) LIKE ? OR UPPER(title) LIKE ? OR UPPER(fiscal_period) LIKE ?)"
        )
        params.extend([like, like, like])
    return " AND ".join(conditions), params


def fetch_reports_page(
    *,
    ticker: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = REPORTS_PAGE_SIZE,
) -> Dict[str, Any]:
    per_page = max(1, min(int(per_page), REPORTS_PAGE_SIZE))
    page = max(1, int(page))
    where_sql, params = _reports_where_clause(ticker, search)
    db = get_db()

    total_row = db.execute(
        f"SELECT COUNT(*) AS cnt FROM financial_reports WHERE {where_sql}",
        tuple(params),
    ).fetchone()
    total = int(total_row["cnt"]) if total_row else 0
    total_pages = math.ceil(total / per_page) if total else 0
    if total_pages and page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    rows = db.execute(
        f"""
        SELECT {_REPORT_LIST_COLUMNS} FROM financial_reports
        WHERE {where_sql}
        ORDER BY updated_at DESC, fiscal_period DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (per_page, offset),
    ).fetchall()

    return {
        "reports": [serialize_report(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def fetch_report_by_id(report_id: int) -> Dict[str, Any] | None:
    db = get_db()
    row = db.execute(
        f"SELECT {_REPORT_LIST_COLUMNS} FROM financial_reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    return serialize_report(row) if row else None


def save_report_pdf_blob(report_id: int, data: bytes) -> None:
    db = get_db()
    row = db.execute(
        "SELECT id FROM financial_reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not row:
        raise ValueError("报告不存在")
    db.execute(
        """
        UPDATE financial_reports
        SET pdf_blob = ?, pdf_path = NULL, updated_at = ?
        WHERE id = ?
        """,
        (data, _now_iso(), report_id),
    )
    db.commit()


def get_report_pdf_blob(report_id: int) -> bytes | None:
    db = get_db()
    row = db.execute(
        "SELECT pdf_blob, pdf_path FROM financial_reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not row:
        return None
    blob = _row_get(row, "pdf_blob")
    if blob is not None:
        return bytes(blob)
    pdf_path = _row_get(row, "pdf_path")
    if pdf_path:
        path = Path(pdf_path)
        if path.is_file():
            return path.read_bytes()
    return None


def fetch_ticker_extracted_for_charts(ticker: str) -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT id, fiscal_period, extracted_json, ai_summary
        FROM financial_reports
        WHERE ticker = ? AND extracted_json IS NOT NULL AND extracted_json != ''
        ORDER BY id ASC
        """,
        (ticker.strip().upper(),),
    ).fetchall()
    result = []
    for row in rows:
        ext = _parse_extracted(row["extracted_json"])
        if ext:
            result.append({
                "id": row["id"],
                "fiscal_period": row["fiscal_period"],
                "extracted": ext,
                "ai_summary": row["ai_summary"],
            })
    return result


def create_financial_report(
    ticker: str,
    fiscal_period: str,
    title: str,
    source_text: str = "",
    report_date: str | None = None,
    theme_id: int | None = None,
    *,
    source_type: str = SOURCE_PASTE,
) -> int:
    db = get_db()
    ticker = ticker.strip().upper()
    fiscal_period = normalize_fiscal_period(fiscal_period)
    title = title.strip() or f"{ticker} {fiscal_period} 财报分析"
    source_text = (source_text or "").strip()
    if not ticker or not fiscal_period:
        raise ValueError("ticker 与财季不能为空")
    if source_type == SOURCE_PASTE and not source_text:
        raise ValueError("粘贴模式下原文不能为空")

    now = _now_iso()
    cursor = db.execute(
        """
        INSERT INTO financial_reports
            (ticker, fiscal_period, report_date, title, source_text, theme_id,
             source_type, parse_status, parse_progress, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            ticker, fiscal_period, report_date, title, source_text, theme_id,
            source_type, PARSE_STATUS_IDLE, now, now,
        ),
    )
    db.commit()
    return int(cursor.lastrowid)


def _ensure_unique_ticker_period(
    db,
    ticker: str,
    fiscal_period: str,
    exclude_report_id: int,
) -> None:
    dup = db.execute(
        """
        SELECT id FROM financial_reports
        WHERE ticker = ? AND fiscal_period = ? AND id != ?
        """,
        (ticker, fiscal_period, exclude_report_id),
    ).fetchone()
    if dup:
        raise ValueError(f"已存在 {ticker} · {fiscal_period} 的报告，请修改财季或标的")


def update_financial_report_meta(
    report_id: int,
    *,
    ticker: str | None = None,
    title: str | None = None,
    source_text: str | None = None,
    fiscal_period: str | None = None,
    report_date: str | None = None,
) -> None:
    db = get_db()
    row = db.execute(
        "SELECT ticker, fiscal_period FROM financial_reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not row:
        raise ValueError("报告不存在")

    new_ticker = row["ticker"]
    new_period = row["fiscal_period"]
    if ticker is not None:
        new_ticker = ticker.strip().upper()
        if not new_ticker:
            raise ValueError("ticker 不能为空")
    if fiscal_period is not None:
        new_period = normalize_fiscal_period(fiscal_period)

    _ensure_unique_ticker_period(db, new_ticker, new_period, report_id)

    fields = []
    values = []
    if ticker is not None:
        fields.append("ticker = ?")
        values.append(new_ticker)
    if fiscal_period is not None:
        fields.append("fiscal_period = ?")
        values.append(new_period)
    if title is not None:
        title_val = title.strip() or f"{new_ticker} {new_period} 财报分析"
        fields.append("title = ?")
        values.append(title_val)
    if source_text is not None:
        fields.append("source_text = ?")
        values.append(source_text.strip())
    if report_date is not None:
        fields.append("report_date = ?")
        if isinstance(report_date, str):
            values.append(report_date.strip() or None)
        else:
            values.append(report_date)
    if not fields:
        return

    fields.append("updated_at = ?")
    values.append(_now_iso())
    values.append(report_id)
    db.execute(
        f"UPDATE financial_reports SET {', '.join(fields)} WHERE id = ?",
        tuple(values),
    )
    db.commit()


def update_parse_state(
    report_id: int,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
    source_text: str | None = None,
    pdf_path: str | None = None,
) -> None:
    db = get_db()
    fields = []
    values = []
    if status is not None:
        fields.append("parse_status = ?")
        values.append(status)
    if progress is not None:
        fields.append("parse_progress = ?")
        values.append(max(0, min(100, int(progress))))
    if message is not None:
        fields.append("parse_message = ?")
        values.append(message)
    if error is not None:
        fields.append("parse_error = ?")
        values.append(error)
    if source_text is not None:
        fields.append("source_text = ?")
        values.append(source_text)
    if pdf_path is not None:
        fields.append("pdf_path = ?")
        values.append(pdf_path)
    if not fields:
        return
    fields.append("updated_at = ?")
    values.append(_now_iso())
    values.append(report_id)
    db.execute(
        f"UPDATE financial_reports SET {', '.join(fields)} WHERE id = ?",
        tuple(values),
    )
    db.commit()


def save_pending_analysis(
    report_id: int,
    extracted: Dict[str, Any],
    ai_summary: str | None = None,
) -> None:
    db = get_db()
    db.execute(
        """
        UPDATE financial_reports
        SET pending_extracted_json = ?, parse_status = ?, parse_progress = 100,
            parse_message = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(extracted, ensure_ascii=False),
            PARSE_STATUS_DONE,
            "解析完成，请确认结构化结果",
            _now_iso(),
            report_id,
        ),
    )
    if ai_summary:
        db.execute(
            "UPDATE financial_reports SET ai_summary = ? WHERE id = ?",
            (ai_summary.strip(), report_id),
        )
    db.commit()


def get_pending_extracted(report_id: int) -> Dict[str, Any] | None:
    db = get_db()
    row = db.execute(
        "SELECT pending_extracted_json FROM financial_reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not row:
        return None
    return _parse_extracted(row["pending_extracted_json"])


def clear_pending_extracted(report_id: int) -> None:
    db = get_db()
    db.execute(
        "UPDATE financial_reports SET pending_extracted_json = NULL WHERE id = ?",
        (report_id,),
    )
    db.commit()


def save_financial_report_analysis(
    report_id: int,
    extracted: Dict[str, Any],
    ai_summary: str | None = None,
) -> None:
    db = get_db()
    row = db.execute(
        "SELECT id FROM financial_reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if not row:
        raise ValueError("报告不存在")

    db.execute(
        """
        UPDATE financial_reports
        SET extracted_json = ?, ai_summary = ?, pending_extracted_json = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(extracted, ensure_ascii=False),
            (ai_summary or "").strip() or None,
            _now_iso(),
            report_id,
        ),
    )
    db.commit()


STALE_PARSE_IDLE_MINUTES = 30


def recover_stale_parse_jobs(max_idle_minutes: int = STALE_PARSE_IDLE_MINUTES) -> int:
    """将长时间无更新的进行中解析标为失败（服务重启或线程中断）。"""
    rows = get_db().execute(
        """
        SELECT id, updated_at FROM financial_reports
        WHERE parse_status IN (?, ?)
        """,
        (PARSE_STATUS_EXTRACTING, PARSE_STATUS_AI),
    ).fetchall()
    cutoff = datetime.now().timestamp() - max_idle_minutes * 60
    recovered = 0
    for row in rows:
        raw = row["updated_at"]
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw)).timestamp()
        except (TypeError, ValueError):
            continue
        if ts >= cutoff:
            continue
        update_parse_state(
            int(row["id"]),
            status=PARSE_STATUS_FAILED,
            progress=0,
            error="上次解析中断（超时或服务重启），请重新分析或重新解析 PDF",
            message="解析失败",
        )
        recovered += 1
    return recovered


def delete_financial_report(report_id: int) -> None:
    db = get_db()
    row = db.execute(
        "SELECT pdf_path FROM financial_reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    db.execute("DELETE FROM financial_reports WHERE id = ?", (report_id,))
    db.commit()
    if row and row["pdf_path"]:
        try:
            path = Path(row["pdf_path"])
            if path.is_file():
                path.unlink()
        except OSError:
            pass
