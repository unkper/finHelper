"""MACD 金叉/死叉监控：零轴上方金叉、零轴下方死叉。"""
from datetime import datetime

from app.database import get_db
from app.services.macd import SIGNAL_LABELS, analyze_macd_from_series
from app.services.notification import PRIORITY_MACD, AlertEvent, CollectResult
from app.services.settings import (
    is_macd_alert_death_cross_below_zero_enabled,
    is_macd_alert_golden_cross_above_zero_enabled,
)
from app.services.stock_history import fetch_daily_series_batch


def _fetch_tracked_us_tickers() -> list[str]:
    db = get_db()
    rows = db.execute(
        """
        SELECT DISTINCT UPPER(s.ticker) AS ticker
        FROM theme_assets s
        JOIN themes t ON s.theme_id = t.id
        WHERE s.exchange = 'US'
          AND t.archived_at IS NULL
        ORDER BY ticker
        """
    ).fetchall()
    return [row["ticker"] for row in rows]


def _get_last_signal_date(ticker: str, signal_type: str) -> str | None:
    db = get_db()
    row = db.execute(
        """
        SELECT last_signal_date FROM stock_macd_alert_state
        WHERE ticker = ? AND signal_type = ?
        """,
        (ticker, signal_type),
    ).fetchone()
    return row["last_signal_date"] if row else None


def _mark_signal_sent(db, ticker: str, signal_type: str, bar_date: str) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    db.execute(
        """
        INSERT INTO stock_macd_alert_state (ticker, signal_type, last_signal_date, last_triggered_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker, signal_type) DO UPDATE SET
            last_signal_date = excluded.last_signal_date,
            last_triggered_at = excluded.last_triggered_at
        """,
        (ticker, signal_type, bar_date, now_iso),
    )


def collect_macd_alerts() -> CollectResult:
    """收集 MACD 信号提醒，推送成功后再写入去重状态。"""
    enabled_types = []
    if is_macd_alert_golden_cross_above_zero_enabled():
        enabled_types.append("golden_cross_above_zero")
    if is_macd_alert_death_cross_below_zero_enabled():
        enabled_types.append("death_cross_below_zero")
    if not enabled_types:
        return CollectResult()

    tickers = _fetch_tracked_us_tickers()
    if not tickers:
        return CollectResult()

    history_map = fetch_daily_series_batch(tickers, use_cache=True)
    events: list[AlertEvent] = []
    pending_marks: list[tuple[str, str, str]] = []
    db = get_db()

    for ticker in tickers:
        series = history_map.get(ticker, [])
        analysis = analyze_macd_from_series(series)
        if not analysis["ready"] or not analysis["signals"]:
            continue

        bar_date = analysis["bar_date"]
        for signal_type in analysis["signals"]:
            if signal_type not in enabled_types:
                continue
            if _get_last_signal_date(ticker, signal_type) == bar_date:
                continue

            label = SIGNAL_LABELS.get(signal_type, signal_type)
            body = (
                f"📌 标的：{ticker} (US)\n"
                f"📊 信号：{label}\n"
                f"📅 K 线日期：{bar_date}\n"
                f"DIF：{analysis['dif']:.4f}  DEA：{analysis['dea']:.4f}\n"
                f"💡 DIF 与 DEA 在零轴{'上方' if signal_type == 'golden_cross_above_zero' else '下方'}形成"
                f"{'金叉（看涨）' if signal_type == 'golden_cross_above_zero' else '死叉（看跌）'}"
            )
            events.append(
                AlertEvent(
                    priority=PRIORITY_MACD,
                    category="macd",
                    body=body,
                    sort_key=(ticker, signal_type, bar_date),
                )
            )
            pending_marks.append((ticker, signal_type, bar_date))

    if not events:
        return CollectResult()

    def apply_marks() -> None:
        for ticker, signal_type, bar_date in pending_marks:
            _mark_signal_sent(db, ticker, signal_type, bar_date)

    return CollectResult(events=events, apply_marks=apply_marks)


def check_macd_alerts() -> None:
    """兼容旧调用；实际逻辑已并入统一 digest。"""
    from app.services.notification import run_monitor_digest
    run_monitor_digest()
