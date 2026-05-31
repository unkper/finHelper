from datetime import datetime, timedelta

from app.database import get_db
from app.services.notification import (
    PRIORITY_PRICE,
    AlertEvent,
    CollectResult,
)
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


def collect_price_alerts() -> CollectResult:
    """收集触发的股价提醒，推送成功后再写入 last_triggered_at。"""
    db = get_db()
    rows = db.execute(
        """
        SELECT a.id AS alert_id, a.target_price, a.direction, a.note, a.last_triggered_at,
               s.id AS asset_id, s.ticker, s.exchange, t.title AS theme_title
        FROM theme_asset_price_alerts a
        JOIN theme_assets s ON a.asset_id = s.id
        JOIN themes t ON s.theme_id = t.id
        WHERE s.exchange = 'US'
          AND t.archived_at IS NULL
          AND COALESCE(a.alert_type, 'price') = 'price'
        """
    ).fetchall()

    if not rows:
        return CollectResult()

    due_rows = [r for r in rows if _alert_is_due(r["last_triggered_at"])]
    if not due_rows:
        return CollectResult()

    tickers = sorted({r["ticker"].upper() for r in due_rows})
    quotes = fetch_us_quotes(tickers)
    if not quotes:
        print("价格监控：未获取到行情，跳过本轮检查。")
        return CollectResult()

    events: list[AlertEvent] = []
    pending_updates: list[tuple[str, int]] = []
    now_iso = datetime.now().isoformat(timespec="seconds")

    for row in due_rows:
        ticker = row["ticker"].upper()
        current = quotes.get(ticker)
        if current is None:
            continue
        if not _price_reached(current, row["target_price"], row["direction"]):
            continue

        note_line = f"📎 备注：{row['note']}\n" if row["note"] else ""
        body = (
            f"📌 主题：{row['theme_title']}\n"
            f"📈 标的：{ticker} ({row['exchange']})\n"
            f"💰 现价：${current:.2f}\n"
            f"🎯 触发：{_direction_label(row['direction'])} ${row['target_price']:.2f}\n"
            f"{note_line}"
            f"⏳ 12 小时内不再重复提醒此价位"
        )
        events.append(
            AlertEvent(
                priority=PRIORITY_PRICE,
                category="price",
                body=body,
                sort_key=(row["theme_title"], ticker),
            )
        )
        pending_updates.append((now_iso, row["alert_id"]))

    if not events:
        return CollectResult()

    def apply_marks() -> None:
        for triggered_at, alert_id in pending_updates:
            db.execute(
                "UPDATE theme_asset_price_alerts SET last_triggered_at = ? WHERE id = ?",
                (triggered_at, alert_id),
            )

    return CollectResult(events=events, apply_marks=apply_marks)


def check_asset_price_alerts():
    """兼容旧调用；实际逻辑已并入统一 digest。"""
    from app.services.notification import run_monitor_digest
    run_monitor_digest()
