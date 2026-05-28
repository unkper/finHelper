"""财报发布提前 X 天飞书提醒。"""
from datetime import date, timedelta

from flask import current_app

from app.database import get_db
from app.services.earnings_calendar import build_earnings_payload, fetch_tracked_us_tickers
from app.services.feishu import push_feishu_message
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


def check_earnings_reminders() -> None:
    if not is_earnings_remind_enabled():
        return

    remind_days = get_earnings_remind_days_before()
    horizon = max(remind_days + 14, get_earnings_horizon_days())
    today = date.today()
    today_str = today.isoformat()
    target_report_date = (today + timedelta(days=remind_days)).isoformat()

    tracked = set(fetch_tracked_us_tickers())
    if not tracked:
        return

    payload = build_earnings_payload(horizon_days=horizon, force_refresh=False)
    events = payload.get("events") or []

    due = [
        e for e in events
        if e.get("report_date") == target_report_date
        and e.get("ticker") in tracked
    ]
    if not due:
        return

    db = get_db()
    messages = []
    for event in due:
        ticker = event["ticker"]
        report_date = event["report_date"]
        if _already_reminded(db, ticker, report_date, remind_days, today_str):
            continue

        time_hint = event.get("report_time") or "时间待定"
        eps_est = event.get("eps_estimate")
        eps_line = f"\nEPS 预估：{eps_est:.2f}" if eps_est is not None else ""
        messages.append(
            f"📊 财报提醒 · {ticker}\n"
            f"发布日：{report_date}（{time_hint}）\n"
            f"今日为提前 {remind_days} 天提醒{eps_line}"
        )
        _mark_reminded(db, ticker, report_date, remind_days, today_str)

    if not messages:
        return

    db.commit()

    receiver_id = current_app.config.get("FEISHU_ALERT_RECEIVER_ID")
    receiver_type = current_app.config.get("FEISHU_ALERT_RECEIVER_TYPE")
    final_content = "📅 财报日历提醒\n\n" + "\n\n---\n\n".join(messages)

    if not receiver_id:
        print("未配置 FEISHU_ALERT_RECEIVER_ID，无法发送财报提醒。内容如下：\n", final_content)
        return

    try:
        push_feishu_message(receiver_type, receiver_id, final_content)
        print(f"已成功发送 {len(messages)} 条财报提醒至飞书")
    except Exception as exc:
        print(f"财报飞书推送失败: {exc}")
