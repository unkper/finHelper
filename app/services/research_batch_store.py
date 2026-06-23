"""投研批量 FMP 任务 CRUD。"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.database import get_db

BATCH_STATUS_PENDING = "pending"
BATCH_STATUS_RUNNING = "running"
BATCH_STATUS_DONE = "done"
BATCH_STATUS_FAILED = "failed"

ITEM_STATUS_PENDING = "pending"
ITEM_STATUS_SUCCESS = "success"
ITEM_STATUS_SKIPPED = "skipped"
ITEM_STATUS_FAILED = "failed"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_batch_job(ticker: str, target_count: int = 4) -> int:
    db = get_db()
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("ticker 不能为空")
    target_count = max(1, min(int(target_count), 12))
    now = _now_iso()
    cursor = db.execute(
        """
        INSERT INTO research_batch_jobs
            (ticker, target_count, status, progress, message, created_at, updated_at)
        VALUES (?, ?, ?, 0, ?, ?, ?)
        """,
        (symbol, target_count, BATCH_STATUS_PENDING, "等待开始", now, now),
    )
    db.commit()
    return int(cursor.lastrowid)


def update_batch_job(
    job_id: int,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
) -> None:
    db = get_db()
    fields = ["updated_at = ?"]
    params: List[Any] = [_now_iso()]
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if progress is not None:
        fields.append("progress = ?")
        params.append(progress)
    if message is not None:
        fields.append("message = ?")
        params.append(message)
    if error is not None:
        fields.append("error = ?")
        params.append(error)
    params.append(job_id)
    db.execute(
        f"UPDATE research_batch_jobs SET {', '.join(fields)} WHERE id = ?",
        params,
    )
    db.commit()


def add_batch_job_item(job_id: int, fmp_year: int, fmp_period: str) -> int:
    db = get_db()
    now = _now_iso()
    cursor = db.execute(
        """
        INSERT INTO research_batch_job_items
            (job_id, fmp_year, fmp_period, status, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_id, int(fmp_year), fmp_period.strip().upper(), ITEM_STATUS_PENDING, now),
    )
    db.commit()
    return int(cursor.lastrowid)


def update_batch_job_item(
    item_id: int,
    *,
    status: str,
    fiscal_period: str | None = None,
    report_id: int | None = None,
    error: str | None = None,
) -> None:
    db = get_db()
    fields = ["status = ?", "updated_at = ?"]
    params: List[Any] = [status, _now_iso()]
    if fiscal_period is not None:
        fields.append("fiscal_period = ?")
        params.append(fiscal_period)
    if report_id is not None:
        fields.append("report_id = ?")
        params.append(report_id)
    if error is not None:
        fields.append("error = ?")
        params.append(error)
    params.append(item_id)
    db.execute(
        f"UPDATE research_batch_job_items SET {', '.join(fields)} WHERE id = ?",
        params,
    )
    db.commit()


def fetch_batch_job(job_id: int) -> Optional[Dict[str, Any]]:
    db = get_db()
    row = db.execute(
        "SELECT * FROM research_batch_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not row:
        return None
    items = db.execute(
        """
        SELECT id, job_id, fmp_year, fmp_period, fiscal_period, report_id,
               status, error, updated_at
        FROM research_batch_job_items
        WHERE job_id = ?
        ORDER BY id ASC
        """,
        (job_id,),
    ).fetchall()
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "target_count": row["target_count"],
        "status": row["status"],
        "progress": row["progress"],
        "message": row["message"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "items": [dict(item) for item in items],
    }


def list_recent_batch_jobs(limit: int = 10) -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT id, ticker, target_count, status, progress, message, error,
               created_at, updated_at
        FROM research_batch_jobs
        ORDER BY id DESC
        LIMIT ?
        """,
        (max(1, limit),),
    ).fetchall()
    return [dict(row) for row in rows]
