from datetime import datetime, timedelta

from flask import current_app

from app.database import get_db
from app.services.feishu import push_feishu_message
from app.services.quotes import fetch_us_quotes

ALERT_COOLDOWN_HOURS = 12


def _alert_is_due(last_triggered_at: str | None) -> bool:
    if not last_triggered_at:
        return True
    try:
        last = datetime.fromisoformat(last_triggered_at)
    except ValueError:
        return True
    return datetime.now() - last >= timedelta(hours=ALERT_COOLDOWN_HOURS)


def _price_reached(current: float, target: float, direction: str) -> bool:
    if direction == "above":
        return current >= target
    return current <= target


def _direction_label(direction: str) -> str:
    return "涨至/涨破" if direction == "above" else "跌至/跌破"


def check_asset_price_alerts():
    """每分钟检查美股价格提醒，触发后 12 小时内不再重复提醒。"""
    db = get_db()
    rows = db.execute(
        """
        SELECT a.id AS alert_id, a.target_price, a.direction, a.note, a.last_triggered_at,
               s.id AS asset_id, s.ticker, s.exchange, t.title AS theme_title
        FROM theme_asset_price_alerts a
        JOIN theme_assets s ON a.asset_id = s.id
        JOIN themes t ON s.theme_id = t.id
        WHERE s.exchange = 'US'
        """
    ).fetchall()

    if not rows:
        return

    due_rows = [r for r in rows if _alert_is_due(r["last_triggered_at"])]
    if not due_rows:
        return

    tickers = sorted({r["ticker"].upper() for r in due_rows})
    quotes = fetch_us_quotes(tickers)
    if not quotes:
        print("价格监控：未获取到行情，跳过本轮检查。")
        return

    messages = []
    now_iso = datetime.now().isoformat(timespec="seconds")

    for row in due_rows:
        ticker = row["ticker"].upper()
        current = quotes.get(ticker)
        if current is None:
            continue
        if not _price_reached(current, row["target_price"], row["direction"]):
            continue

        note_line = f"📎 备注：{row['note']}\n" if row["note"] else ""
        messages.append(
            f"📌 主题：{row['theme_title']}\n"
            f"📈 标的：{ticker} ({row['exchange']})\n"
            f"💰 现价：${current:.2f}\n"
            f"🎯 触发：{_direction_label(row['direction'])} ${row['target_price']:.2f}\n"
            f"{note_line}"
            f"⏳ 12 小时内不再重复提醒此价位"
        )
        db.execute(
            "UPDATE theme_asset_price_alerts SET last_triggered_at = ? WHERE id = ?",
            (now_iso, row["alert_id"]),
        )

    if not messages:
        return

    db.commit()
    final_content = "🎯 股价到达提醒\n\n" + "\n\n---\n\n".join(messages)

    receiver_id = current_app.config.get("FEISHU_ALERT_RECEIVER_ID")
    receiver_type = current_app.config.get("FEISHU_ALERT_RECEIVER_TYPE")

    if not receiver_id:
        print("未配置 FEISHU_ALERT_RECEIVER_ID，无法发送飞书消息。内容如下：\n", final_content)
        return

    try:
        push_feishu_message(receiver_type, receiver_id, final_content)
        print(f"已成功发送 {len(messages)} 条股价提醒至飞书")
    except Exception as e:
        print(f"调用飞书主动推送失败: {e}")
