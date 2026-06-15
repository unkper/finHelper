"""外部 API 调用按日统计（EODHD / Alpha Vantage / FMP / DeepSeek）。"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.database import get_db

PROVIDERS = ("eodhd", "alpha_vantage", "fmp", "deepseek")

PROVIDER_LABELS: Dict[str, str] = {
    "eodhd": "EODHD",
    "alpha_vantage": "Alpha Vantage",
    "fmp": "FMP",
    "deepseek": "DeepSeek",
}


def infer_provider_from_url(url: str) -> Optional[str]:
    host = (urlparse(url).netloc or "").lower()
    if "eodhd.com" in host:
        return "eodhd"
    if "alphavantage.co" in host:
        return "alpha_vantage"
    if "financialmodelingprep.com" in host:
        return "fmp"
    return None


def record_api_call(provider: str, count: int = 1) -> None:
    if provider not in PROVIDERS or count <= 0:
        return
    try:
        usage_date = date.today().isoformat()
        db = get_db()
        db.execute(
            """
            INSERT INTO api_usage_daily (usage_date, provider, call_count)
            VALUES (?, ?, ?)
            ON CONFLICT(usage_date, provider) DO UPDATE SET
                call_count = call_count + excluded.call_count
            """,
            (usage_date, provider, count),
        )
        db.commit()
    except Exception:
        pass


def _date_range(start: date, end: date) -> List[str]:
    dates: List[str] = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _parse_usage_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _build_stats_payload(days: int, start_date: str, end_date: str, rows) -> Dict[str, Any]:
    start = _parse_usage_date(start_date)
    end = _parse_usage_date(end_date)
    if not start or not end or start > end:
        return _empty_stats(days if days > 0 else 7)

    dates = _date_range(start, end)
    matrix: Dict[str, Dict[str, int]] = {d: {p: 0 for p in PROVIDERS} for d in dates}
    totals: Dict[str, int] = {p: 0 for p in PROVIDERS}
    for row in rows:
        usage_date = row["usage_date"]
        provider = row["provider"]
        count = int(row["call_count"] or 0)
        if usage_date in matrix and provider in matrix[usage_date]:
            matrix[usage_date][provider] = count
        if provider in totals:
            totals[provider] += count

    series = {p: [matrix[d][p] for d in dates] for p in PROVIDERS}
    today = date.today().isoformat()
    today_total = sum(matrix.get(today, {}).values()) if today in matrix else 0
    period_total = sum(totals.values())

    return {
        "days": days,
        "all_time": days == 0,
        "providers": list(PROVIDERS),
        "provider_labels": dict(PROVIDER_LABELS),
        "dates": dates,
        "series": series,
        "totals": totals,
        "today_total": today_total,
        "period_total": period_total,
    }


def _fetch_all_usage_stats() -> Dict[str, Any]:
    db = get_db()
    bounds = db.execute(
        """
        SELECT MIN(usage_date) AS min_date, MAX(usage_date) AS max_date
        FROM api_usage_daily
        """
    ).fetchone()
    if not bounds or not bounds["min_date"]:
        return _empty_stats(7, all_time=True)

    start_date = bounds["min_date"]
    end_date = max(bounds["max_date"], date.today().isoformat())
    rows = db.execute(
        """
        SELECT usage_date, provider, call_count
        FROM api_usage_daily
        WHERE usage_date >= ? AND usage_date <= ?
        ORDER BY usage_date, provider
        """,
        (start_date, end_date),
    ).fetchall()
    return _build_stats_payload(0, start_date, end_date, rows)


def fetch_usage_stats(days: int = 30) -> Dict[str, Any]:
    if int(days) == 0:
        return _fetch_all_usage_stats()

    days = max(7, min(365, int(days)))
    end = date.today()
    start = end - timedelta(days=days - 1)
    start_date = start.isoformat()
    end_date = end.isoformat()

    db = get_db()
    rows = db.execute(
        """
        SELECT usage_date, provider, call_count
        FROM api_usage_daily
        WHERE usage_date >= ? AND usage_date <= ?
        ORDER BY usage_date, provider
        """,
        (start_date, end_date),
    ).fetchall()
    return _build_stats_payload(days, start_date, end_date, rows)


def _empty_stats(days: int, *, all_time: bool = False) -> Dict[str, Any]:
    if all_time or int(days) == 0:
        today = date.today().isoformat()
        dates = [today]
        effective_days = 0
    else:
        dates = _date_range(date.today() - timedelta(days=days - 1), date.today())
        effective_days = days
    series = {p: [0] * len(dates) for p in PROVIDERS}
    return {
        "days": effective_days,
        "all_time": all_time or int(days) == 0,
        "providers": list(PROVIDERS),
        "provider_labels": dict(PROVIDER_LABELS),
        "dates": dates,
        "series": series,
        "totals": {p: 0 for p in PROVIDERS},
        "today_total": 0,
        "period_total": 0,
    }
