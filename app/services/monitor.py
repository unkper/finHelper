from datetime import date, datetime, timedelta

from app.database import get_db
from app.services.notification import (
    PRIORITY_MILESTONE_ADVANCE,
    PRIORITY_MILESTONE_DAY,
    PRIORITY_MILESTONE_QUOTES,
    AlertEvent,
    CollectResult,
)
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


def collect_milestone_alerts() -> CollectResult:
    """收集里程碑提醒（当日/提前/附带行情），推送成功后再写入去重标记。"""
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
        return CollectResult()

    events: list[AlertEvent] = []
    advance_marks: list[int] = []
    day_marks: list[int] = []
    quote_milestone_ids: list[tuple[int, int]] = []

    for row in advance_rows:
        end = row["end_date"] or row["event_date"]
        range_hint = f"（提醒期 {row['event_date']} ~ {end}）" if end != row["event_date"] else ""
        body = (
            f"📌 主题：{row['theme_title']}\n"
            f"⏱️ 节点：【还有 3 天】{row['event_date']} {row['reminder_time']}{range_hint}\n"
            f"📝 描述：{row['description']}"
        )
        events.append(
            AlertEvent(
                priority=PRIORITY_MILESTONE_ADVANCE,
                category="milestone_advance",
                body=body,
                sort_key=(row["theme_title"], row["event_date"], row["description"]),
            )
        )
        advance_marks.append(row["id"])

    all_tickers: set[str] = set()
    for row in day_rows:
        for asset in _fetch_milestone_sync_assets(db, row["theme_id"], row["id"]):
            all_tickers.add(asset["ticker"].upper())
    quotes = fetch_us_quotes(sorted(all_tickers)) if all_tickers else {}

    for row in day_rows:
        label = _milestone_range_label(row["event_date"], row["end_date"], today_str)
        body = (
            f"📌 主题：{row['theme_title']}\n"
            f"⏱️ 节点：{label}{row['event_date']} {row['reminder_time']}\n"
            f"📝 描述：{row['description']}"
        )
        events.append(
            AlertEvent(
                priority=PRIORITY_MILESTONE_DAY,
                category="milestone_day",
                body=body,
                sort_key=(row["theme_title"], row["event_date"], row["description"]),
            )
        )
        day_marks.append(row["id"])

        assets = _fetch_milestone_sync_assets(db, row["theme_id"], row["id"])
        if assets:
            stock_lines = _build_theme_stock_lines(assets, quotes)
            if stock_lines:
                desc_short = row["description"]
                if len(desc_short) > 24:
                    desc_short = desc_short[:24] + "…"
                quote_body = (
                    f"📌 主题：{row['theme_title']}\n"
                    f"📈 随节点标的行情 · {desc_short}（{today_str} {now_time}）\n"
                    + "\n".join(stock_lines)
                )
                events.append(
                    AlertEvent(
                        priority=PRIORITY_MILESTONE_QUOTES,
                        category="milestone_quotes",
                        body=quote_body,
                        sort_key=(row["theme_title"], row["event_date"], desc_short),
                    )
                )
                quote_milestone_ids.append((row["id"], row["theme_id"]))

    if not events:
        return CollectResult()

    now_iso = datetime.now().isoformat(timespec="seconds")

    def apply_marks() -> None:
        for milestone_id in advance_marks:
            _mark_reminded(db, milestone_id, "reminded_advance_at")
        for milestone_id in day_marks:
            _mark_reminded(db, milestone_id, "reminded_day_at")
        for milestone_id, theme_id in quote_milestone_ids:
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
                (now_iso, milestone_id, theme_id),
            )

    return CollectResult(events=events, apply_marks=apply_marks)


def check_upcoming_milestones():
    """兼容旧调用；实际逻辑已并入统一 digest。"""
    from app.services.notification import run_monitor_digest
    run_monitor_digest()
