"""全局价位告警列表与批量删除。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.database import get_db
from app.services.quotes import fetch_us_quotes
from app.services.settings import get_price_alert_cooldown_hours, get_price_alert_settings


def _price_reached(current: float, target: float, direction: str) -> bool:
    if direction == "above":
        return current >= target
    return current <= target


def fetch_all_price_alerts(
    *,
    query: str | None = None,
    theme_id: int | None = None,
    include_quotes: bool = True,
) -> List[Dict[str, Any]]:
    db = get_db()
    sql = """
        SELECT
            a.id AS alert_id,
            a.target_price,
            a.direction,
            a.note,
            a.last_triggered_at,
            s.id AS asset_id,
            s.ticker,
            s.exchange,
            t.id AS theme_id,
            t.title AS theme_title,
            ia.name AS assistant_name
        FROM theme_asset_price_alerts a
        JOIN theme_assets s ON a.asset_id = s.id
        JOIN themes t ON s.theme_id = t.id
        JOIN investment_assistants ia ON t.assistant_id = ia.id
        WHERE t.archived_at IS NULL
          AND s.exchange = 'US'
          AND COALESCE(a.alert_type, 'price') = 'price'
    """
    params: List[Any] = []
    q = (query or "").strip()
    if theme_id is not None:
        sql += " AND t.id = ?"
        params.append(theme_id)
    if q:
        sql += " AND (UPPER(s.ticker) LIKE ? OR t.title LIKE ?)"
        like_ticker = f"%{q.upper()}%"
        like_title = f"%{q}%"
        params.extend([like_ticker, like_title])
    sql += " ORDER BY s.ticker ASC, a.target_price ASC"

    rows = db.execute(sql, tuple(params)).fetchall()
    alerts = [dict(row) for row in rows]

    if include_quotes and alerts:
        tickers = sorted({row["ticker"].upper() for row in alerts})
        quotes = fetch_us_quotes(tickers)
        for item in alerts:
            ticker = item["ticker"].upper()
            current = quotes.get(ticker)
            item["current_price"] = round(float(current), 2) if current is not None else None
            if current is not None:
                item["is_triggered"] = _price_reached(
                    float(current),
                    float(item["target_price"]),
                    item["direction"],
                )
            else:
                item["is_triggered"] = False
    else:
        for item in alerts:
            item["current_price"] = None
            item["is_triggered"] = False

    return alerts


def get_price_alert_summary(alerts: List[Dict[str, Any]] | None = None) -> Dict[str, int]:
    if alerts is None:
        alerts = fetch_all_price_alerts(include_quotes=False)
    tickers = {row["ticker"].upper() for row in alerts}
    themes = {row["theme_id"] for row in alerts}
    triggered = sum(1 for row in alerts if row.get("is_triggered"))
    return {
        "alert_count": len(alerts),
        "ticker_count": len(tickers),
        "theme_count": len(themes),
        "triggered_count": triggered,
    }


def delete_price_alerts(alert_ids: List[int]) -> int:
    ids = [int(i) for i in alert_ids if i is not None]
    if not ids:
        return 0
    db = get_db()
    placeholders = ",".join("?" for _ in ids)
    cursor = db.execute(
        f"""
        DELETE FROM theme_asset_price_alerts
        WHERE id IN ({placeholders})
          AND COALESCE(alert_type, 'price') = 'price'
        """,
        tuple(ids),
    )
    db.commit()
    return cursor.rowcount


def build_price_alerts_payload(
    *,
    query: str | None = None,
    theme_id: int | None = None,
) -> Dict[str, Any]:
    alerts = fetch_all_price_alerts(query=query, theme_id=theme_id)
    return {
        "alerts": alerts,
        "summary": get_price_alert_summary(alerts),
        "settings": get_price_alert_settings(),
        "cooldown_hours": get_price_alert_cooldown_hours(),
    }
