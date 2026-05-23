from datetime import date, datetime, timedelta

from flask import current_app

from app.database import get_db
from app.services.feishu import push_feishu_message


def _mark_reminded(db, milestone_id: int, field: str) -> None:
    if field not in ("reminded_advance_at", "reminded_day_at"):
        raise ValueError(f"invalid remind field: {field}")
    db.execute(
        f"UPDATE theme_milestones SET {field} = ? WHERE id = ?",
        (date.today().isoformat(), milestone_id),
    )


def check_upcoming_milestones():
    """在节点设定的日期/时刻，通过飞书推送时间线提醒（当天 + 提前3天）。"""
    db = get_db()
    today = date.today()
    today_str = today.isoformat()
    advance_target_str = (today + timedelta(days=3)).isoformat()
    now_time = datetime.now().strftime("%H:%M")

    day_rows = db.execute(
        """
        SELECT m.id, m.event_date, m.description, m.reminder_time,
               t.title AS theme_title
        FROM theme_milestones m
        JOIN themes t ON m.theme_id = t.id
        WHERE m.is_completed = 0
          AND m.event_date = ?
          AND m.reminder_time = ?
          AND (m.reminded_day_at IS NULL OR m.reminded_day_at != ?)
        """,
        (today_str, now_time, today_str),
    ).fetchall()

    advance_rows = db.execute(
        """
        SELECT m.id, m.event_date, m.description, m.reminder_time,
               t.title AS theme_title
        FROM theme_milestones m
        JOIN themes t ON m.theme_id = t.id
        WHERE m.is_completed = 0
          AND m.event_date = ?
          AND m.reminder_time = ?
          AND (m.reminded_advance_at IS NULL OR m.reminded_advance_at != ?)
        """,
        (advance_target_str, now_time, today_str),
    ).fetchall()

    if not day_rows and not advance_rows:
        return

    messages = []
    for row in advance_rows:
        messages.append(
            f"📌 主题：{row['theme_title']}\n"
            f"⏱️ 节点：【还有 3 天】{row['event_date']} {row['reminder_time']}\n"
            f"📝 描述：{row['description']}"
        )
        _mark_reminded(db, row["id"], "reminded_advance_at")

    for row in day_rows:
        messages.append(
            f"📌 主题：{row['theme_title']}\n"
            f"⏱️ 节点：【就是今天】{row['event_date']} {row['reminder_time']}\n"
            f"📝 描述：{row['description']}"
        )
        _mark_reminded(db, row["id"], "reminded_day_at")

    db.commit()

    final_content = "⏳ 投资时间线提醒\n\n" + "\n\n---\n\n".join(messages)

    receiver_id = current_app.config.get("FEISHU_ALERT_RECEIVER_ID")
    receiver_type = current_app.config.get("FEISHU_ALERT_RECEIVER_TYPE")

    if not receiver_id:
        print("未配置 FEISHU_ALERT_RECEIVER_ID，无法发送飞书消息。内容如下：\n", final_content)
        return

    try:
        push_feishu_message(receiver_type, receiver_id, final_content)
        print(f"已成功发送 {len(messages)} 条里程碑提醒至飞书（{now_time}）")
    except Exception as e:
        print(f"调用飞书主动推送失败: {e}")
