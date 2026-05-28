from datetime import date, datetime, timedelta

from flask import current_app

from app.database import get_db
from app.services.feishu import push_feishu_message
from app.services.quotes import fetch_us_quotes


def _mark_reminded(db, milestone_id: int, field: str) -> None:
    if field not in ("reminded_advance_at", "reminded_day_at"):
        raise ValueError(f"invalid remind field: {field}")
    db.execute(
        f"UPDATE theme_milestones SET {field} = ? WHERE id = ?",
        (date.today().isoformat(), milestone_id),
    )


def _milestone_range_label(event_date: str, end_date: str | None, today_str: str) -> str:
    end = end_date or event_date
    if event_date == end:
        if today_str == event_date:
            return "【就是今天】"
        return f"【提醒期内 {today_str}】"
    return f"【提醒期内 {today_str}】{event_date} ~ {end} "


def _fetch_milestone_sync_assets(db, theme_id: int, milestone_id: int) -> list:
    rows = db.execute(
        """
        SELECT s.ticker, s.exchange
        FROM theme_asset_price_alerts a
        JOIN theme_assets s ON a.asset_id = s.id
        JOIN themes t ON s.theme_id = t.id
        WHERE s.theme_id = ?
          AND t.archived_at IS NULL
          AND a.alert_type = 'milestone'
          AND s.exchange = 'US'
          AND (a.milestone_id = ? OR a.milestone_id IS NULL)
        ORDER BY s.ticker
        """,
        (theme_id, milestone_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _build_theme_stock_lines(assets: list, quotes: dict) -> list[str]:
    lines = []
    for asset in assets:
        ticker = asset["ticker"].upper()
        price = quotes.get(ticker)
        if price is None:
            lines.append(f"  · {ticker}：现价不可用")
        else:
            lines.append(f"  · {ticker}：${price:.2f}")
    return lines


def check_upcoming_milestones():
    """在节点时间范围内按设定时刻推送飞书提醒（每天一次）；开始日前 3 天额外提醒。"""
    db = get_db()
    today = date.today()
    today_str = today.isoformat()
    advance_target_str = (today + timedelta(days=3)).isoformat()
    now_time = datetime.now().strftime("%H:%M")

    day_rows = db.execute(
        """
        SELECT m.id, m.theme_id, m.event_date, m.end_date, m.description, m.reminder_time,
               t.title AS theme_title
        FROM theme_milestones m
        JOIN themes t ON m.theme_id = t.id
        WHERE m.is_completed = 0
          AND t.archived_at IS NULL
          AND ? >= m.event_date
          AND ? <= COALESCE(m.end_date, m.event_date)
          AND m.reminder_time = ?
          AND (m.reminded_day_at IS NULL OR m.reminded_day_at != ?)
        """,
        (today_str, today_str, now_time, today_str),
    ).fetchall()

    advance_rows = db.execute(
        """
        SELECT m.id, m.theme_id, m.event_date, m.end_date, m.description, m.reminder_time,
               t.title AS theme_title
        FROM theme_milestones m
        JOIN themes t ON m.theme_id = t.id
        WHERE m.is_completed = 0
          AND t.archived_at IS NULL
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
        end = row["end_date"] or row["event_date"]
        range_hint = f"（提醒期 {row['event_date']} ~ {end}）" if end != row["event_date"] else ""
        messages.append(
            f"📌 主题：{row['theme_title']}\n"
            f"⏱️ 节点：【还有 3 天】{row['event_date']} {row['reminder_time']}{range_hint}\n"
            f"📝 描述：{row['description']}"
        )
        _mark_reminded(db, row["id"], "reminded_advance_at")

    all_tickers: set[str] = set()
    for row in day_rows:
        for asset in _fetch_milestone_sync_assets(db, row["theme_id"], row["id"]):
            all_tickers.add(asset["ticker"].upper())
    quotes = fetch_us_quotes(sorted(all_tickers)) if all_tickers else {}

    for row in day_rows:
        label = _milestone_range_label(row["event_date"], row["end_date"], today_str)
        messages.append(
            f"📌 主题：{row['theme_title']}\n"
            f"⏱️ 节点：{label}{row['event_date']} {row['reminder_time']}\n"
            f"📝 描述：{row['description']}"
        )
        _mark_reminded(db, row["id"], "reminded_day_at")

        assets = _fetch_milestone_sync_assets(db, row["theme_id"], row["id"])
        if assets:
            stock_lines = _build_theme_stock_lines(assets, quotes)
            if stock_lines:
                desc_short = row["description"]
                if len(desc_short) > 24:
                    desc_short = desc_short[:24] + "…"
                messages.append(
                    f"📌 主题：{row['theme_title']}\n"
                    f"📈 随节点标的行情 · {desc_short}（{today_str} {now_time}）\n"
                    + "\n".join(stock_lines)
                )
            now_iso = datetime.now().isoformat(timespec="seconds")
            db.execute(
                """
                UPDATE theme_asset_price_alerts
                SET last_triggered_at = ?
                WHERE alert_type = 'milestone'
                  AND (milestone_id = ? OR milestone_id IS NULL)
                  AND asset_id IN (
                    SELECT id FROM theme_assets WHERE theme_id = ?
                  )
                """,
                (now_iso, row["id"], row["theme_id"]),
            )

    if not messages:
        return

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
