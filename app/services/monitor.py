from datetime import date, timedelta
from app.database import get_db

from datetime import date, timedelta
from flask import current_app
from app.database import get_db
from app.services.feishu import push_feishu_message


def check_upcoming_milestones():
    """扫描即将到来的投资时间线节点，并推送到飞书"""
    db = get_db()
    today = date.today()
    # 设定提前 3 天预警，以及当天预警
    target_date_3_days = (today + timedelta(days=3)).isoformat()
    today_str = today.isoformat()

    # 联表查询：查出所有未完成（is_completed = 0）的节点以及对应的主题名
    rows = db.execute(
        """
        SELECT m.id, m.event_date, m.description, t.title as theme_title, t.id as theme_id
        FROM theme_milestones m
        JOIN themes t ON m.theme_id = t.id
        WHERE m.is_completed = 0 AND (m.event_date = ? OR m.event_date = ?)
        """,
        (today_str, target_date_3_days)
    ).fetchall()

    if not rows:
        print("今日无即将到来的投资时间线节点。")
        return

    # 组装告警信息卡片内容
    messages = []
    for row in rows:
        day_diff = (date.fromisoformat(row["event_date"]) - today).days
        time_tag = "【就是今天】" if day_diff == 0 else f"【还有 {day_diff} 天】"

        msg = f"📌 主题：{row['theme_title']}\n" \
              f"⏱️ 节点：{time_tag} {row['event_date']}\n" \
              f"📝 描述：{row['description']}"
        messages.append(msg)

    # 拼接最终的富文本字符串
    final_content = "⏳ 投资时间线预警\n\n" + "\n\n---\n\n".join(messages)

    # 获取接收者配置
    receiver_id = current_app.config.get("FEISHU_ALERT_RECEIVER_ID")
    receiver_type = current_app.config.get("FEISHU_ALERT_RECEIVER_TYPE")

    if not receiver_id:
        print("未配置 FEISHU_ALERT_RECEIVER_ID，无法发送飞书消息。内容如下：\n", final_content)
        return

    # 调用我们搭好的基建！
    try:
        push_feishu_message(receiver_type, receiver_id, final_content)
        print(f"已成功发送 {len(rows)} 条里程碑预警至飞书")
    except Exception as e:
        print(f"调用飞书主动推送失败: {e}")