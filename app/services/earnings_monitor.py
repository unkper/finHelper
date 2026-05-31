"""财报发布提前 X 天飞书提醒。"""
from datetime import date, timedelta

from app.database import get_db
from app.services.earnings_calendar import build_earnings_payload, fetch_tracked_us_tickers
from app.services.notification import PRIORITY_EARNINGS, AlertEvent, CollectResult
from app.services.settings import (
    get_earnings_horizon_days,
    get_earnings_remind_days_before,
    is_earnings_remind_enabled,
)


def _already_reminded(
    db,
    ticker: str,
    report_date: str,
    remind_days_before: int,
    today_str: str,
) -> bool:
    row = db.execute(
        """
        SELECT reminded_on FROM earnings_reminder_log
        WHERE ticker = ? AND report_date = ? AND remind_days_before = ?
        """,
        (ticker, report_date, remind_days_before),
    ).fetchone()
    return row is not None and row["reminded_on"] == today_str


def _mark_reminded(db, ticker: str, report_date: str, remind_days_before: int, today_str: str) -> None:
    db.execute(
        """
        INSERT INTO earnings_reminder_log (ticker, report_date, remind_days_before, reminded_on)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker, report_date, remind_days_before) DO UPDATE SET
            reminded_on = excluded.reminded_on
        """,
        (ticker, report_date, remind_days_before, today_str),
    )


def collect_earnings_alerts() -> CollectResult:
    """收集财报提前提醒，推送成功后再写入去重日志。"""
    from app.services.features import is_earnings_enabled
    if not is_earnings_enabled():
        return CollectResult()
    if not is_earnings_remind_enabled():
        return CollectResult()

    remind_days = get_earnings_remind_days_before()
    horizon = max(remind_days + 14, get_earnings_horizon_days())
    today = date.today()
    today_str = today.isoformat()
    target_report_date = (today + timedelta(days=remind_days)).isoformat()

    tracked = set(fetch_tracked_us_tickers())
    if not tracked:
        return CollectResult()

    payload = build_earnings_payload(horizon_days=horizon, force_refresh=False)
    events_data = payload.get("events") or []

    due = [
        e for e in events_data
        if e.get("report_date") == target_report_date
        and e.get("ticker") in tracked
    ]
    if not due:
        return CollectResult()

    db = get_db()
    alert_events: list[AlertEvent] = []
    pending_marks: list[tuple[str, str, int]] = []

    for event in due:
        ticker = event["ticker"]
        report_date = event["report_date"]
        if _already_reminded(db, ticker, report_date, remind_days, today_str):
            continue

        time_hint = event.get("report_time") or "时间待定"
        eps_est = event.get("eps_estimate")
        eps_line = f"\nEPS 预估：{eps_est:.2f}" if eps_est is not None else ""
        body = (
            f"📊 财报提醒 · {ticker}\n"
            f"发布日：{report_date}（{time_hint}）\n"
            f"今日为提前 {remind_days} 天提醒{eps_line}"
        )
        alert_events.append(
            AlertEvent(
                priority=PRIORITY_EARNINGS,
                category="earnings",
                body=body,
                sort_key=(ticker, report_date),
            )
        )
        pending_marks.append((ticker, report_date, remind_days))

    if not alert_events:
        return CollectResult()

    def apply_marks() -> None:
        for ticker, report_date, days_before in pending_marks:
            _mark_reminded(db, ticker, report_date, days_before, today_str)

    return CollectResult(events=alert_events, apply_marks=apply_marks)


def check_earnings_reminders() -> None:
    """兼容旧调用；实际逻辑已并入统一 digest。"""
    from app.services.notification import run_monitor_digest
    run_monitor_digest()
