"""财报日历：FMP 优先，EODHD 回退；含缓存与归一化。"""
import json
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from flask import current_app

from app.database import get_db
from app.services.investment import fetch_tracked_assets_overview
from app.services.quote_client import chunk_list, http_get_json, normalize_us_tickers
from app.services.quote_providers import eodhd

EODHD_EARNINGS_URL = "https://eodhd.com/api/calendar/earnings"
FMP_EARNINGS_URL = "https://financialmodelingprep.com/stable/earnings-calendar"
EODHD_SYMBOL_BATCH = 20
EODHD_BATCH_DELAY = 0.3
CACHE_TTL_HOURS = 6


def fetch_tracked_us_tickers() -> List[str]:
    assets = fetch_tracked_assets_overview()
    tickers = [
        item["ticker"].upper()
        for item in assets
        if item.get("exchange") == "US"
    ]
    return normalize_us_tickers(tickers)


def _has_fmp_key() -> bool:
    return bool(current_app.config.get("FMP_API_KEY", ""))


def is_earnings_api_configured() -> bool:
    return eodhd.has_api_key() or _has_fmp_key()


def _cache_key(from_date: str, to_date: str, tickers: List[str]) -> str:
    return f"{from_date}:{to_date}:{','.join(sorted(tickers))}"


def _read_cache(cache_key: str) -> Optional[List[Dict[str, Any]]]:
    db = get_db()
    row = db.execute(
        "SELECT payload_json, fetched_at FROM earnings_calendar_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except ValueError:
        return None
    if datetime.now() - fetched > timedelta(hours=CACHE_TTL_HOURS):
        return None
    try:
        data = json.loads(row["payload_json"])
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def _write_cache(cache_key: str, events: List[Dict[str, Any]]) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO earnings_calendar_cache (cache_key, payload_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at
        """,
        (cache_key, json.dumps(events, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()


def _normalize_report_time(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    lower = text.lower()
    if lower in ("bmo", "before market open", "before_market_open", "am"):
        return "盘前"
    if lower in ("amc", "after market close", "after_market_close", "pm"):
        return "盘后"
    if "before" in lower:
        return "盘前"
    if "after" in lower:
        return "盘后"
    return text


def _ticker_from_eodhd_code(code: str) -> str:
    return (code or "").split(".")[0].upper()


def _parse_date_value(raw: Any) -> Optional[str]:
    if not raw:
        return None
    text = str(raw).strip()[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return None


def _enrich_events(events: List[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    enriched = []
    for item in events:
        report_date = item.get("report_date")
        if not report_date:
            continue
        try:
            report = date.fromisoformat(report_date)
        except ValueError:
            continue
        days_until = (report - today).days
        if days_until < 0:
            continue
        row = dict(item)
        row["days_until"] = days_until
        if days_until == 0:
            row["days_label"] = "今天"
        elif days_until == 1:
            row["days_label"] = "明天"
        else:
            row["days_label"] = f"还有 {days_until} 天"
        enriched.append(row)
    enriched.sort(key=lambda x: (x["report_date"], x.get("ticker", "")))
    return enriched


def _parse_eodhd_record(item: dict, allowed: Set[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    ticker = _ticker_from_eodhd_code(item.get("code") or item.get("symbol") or "")
    if not ticker or (allowed and ticker not in allowed):
        return None
    report_date = _parse_date_value(
        item.get("report_date") or item.get("date") or item.get("earnings_date")
    )
    if not report_date:
        return None
    eps_estimate = item.get("estimate") or item.get("eps_estimate") or item.get("epsEstimate")
    eps_actual = item.get("actual") or item.get("eps_actual") or item.get("eps")
    try:
        eps_estimate = float(eps_estimate) if eps_estimate is not None else None
    except (TypeError, ValueError):
        eps_estimate = None
    try:
        eps_actual = float(eps_actual) if eps_actual is not None else None
    except (TypeError, ValueError):
        eps_actual = None
    return {
        "ticker": ticker,
        "report_date": report_date,
        "report_time": _normalize_report_time(
            item.get("before_after_market") or item.get("time") or item.get("when")
        ),
        "fiscal_period": (item.get("period") or item.get("fiscal_period") or "").strip() or None,
        "eps_estimate": eps_estimate,
        "eps_actual": eps_actual,
    }


def _fetch_eodhd(
    from_date: str, to_date: str, tickers: List[str]
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    api_key = current_app.config.get("EODHD_API_KEY", "")
    if not api_key:
        return [], "missing_key"

    allowed = set(tickers)
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    eodhd_symbols = [eodhd.to_eodhd_symbol(t) for t in tickers]
    error_hint: Optional[str] = None

    for index, batch in enumerate(chunk_list(eodhd_symbols, EODHD_SYMBOL_BATCH)):
        if index > 0:
            time.sleep(EODHD_BATCH_DELAY)
        params = {
            "api_token": api_key,
            "fmt": "json",
            "from": from_date,
            "to": to_date,
            "symbols": ",".join(batch),
        }
        payload = http_get_json(EODHD_EARNINGS_URL, params)
        if payload is None:
            error_hint = error_hint or "request_failed"
            continue
        if isinstance(payload, dict) and payload.get("errors"):
            error_hint = "api_error"
            continue
        items = []
        if isinstance(payload, dict):
            items = payload.get("earnings") or []
        elif isinstance(payload, list):
            items = payload
        for raw in items:
            parsed = _parse_eodhd_record(raw, allowed)
            if parsed:
                key = (parsed["ticker"], parsed["report_date"])
                merged[key] = parsed

    if not merged and error_hint:
        return [], error_hint
    return list(merged.values()), None


def _parse_fmp_record(item: dict, allowed: Set[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    ticker = (item.get("symbol") or "").strip().upper()
    if not ticker or (allowed and ticker not in allowed):
        return None
    report_date = _parse_date_value(item.get("date") or item.get("reportDate"))
    if not report_date:
        return None
    eps_estimate = item.get("epsEstimated") or item.get("eps_estimate")
    eps_actual = item.get("eps") or item.get("eps_actual")
    try:
        eps_estimate = float(eps_estimate) if eps_estimate is not None else None
    except (TypeError, ValueError):
        eps_estimate = None
    try:
        eps_actual = float(eps_actual) if eps_actual is not None else None
    except (TypeError, ValueError):
        eps_actual = None
    return {
        "ticker": ticker,
        "report_date": report_date,
        "report_time": _normalize_report_time(item.get("time")),
        "fiscal_period": (item.get("fiscalDateEnding") or item.get("fiscal_period") or "").strip() or None,
        "eps_estimate": eps_estimate,
        "eps_actual": eps_actual,
    }


def _fetch_fmp(
    from_date: str, to_date: str, tickers: List[str]
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    api_key = current_app.config.get("FMP_API_KEY", "")
    if not api_key:
        return [], "missing_key"

    allowed = set(tickers)
    params = {"apikey": api_key, "from": from_date, "to": to_date}
    payload = http_get_json(FMP_EARNINGS_URL, params)
    if payload is None:
        return [], "request_failed"
    if isinstance(payload, dict) and payload.get("Error Message"):
        return [], "api_error"
    if not isinstance(payload, list):
        return [], "invalid_response"

    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for raw in payload:
        parsed = _parse_fmp_record(raw, allowed)
        if parsed:
            key = (parsed["ticker"], parsed["report_date"])
            merged[key] = parsed
    return list(merged.values()), None


def fetch_earnings_calendar(
    from_date: date,
    to_date: date,
    tickers: List[str],
    force_refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """
    拉取财报日历。返回 (events, provider, error_hint)。
    provider: eodhd | fmp | none
    """
    tickers = normalize_us_tickers(tickers)
    if not tickers:
        return [], "none", None

    from_str = from_date.isoformat()
    to_str = to_date.isoformat()
    cache_key = _cache_key(from_str, to_str, tickers)

    if not force_refresh:
        cached = _read_cache(cache_key)
        if cached is not None:
            return _enrich_events(cached, date.today()), "cache", None

    events: List[Dict[str, Any]] = []
    provider = "none"
    error_hint: Optional[str] = None

    if _has_fmp_key():
        events, error_hint = _fetch_fmp(from_str, to_str, tickers)
        if events:
            provider = "fmp"
        elif eodhd.has_api_key():
            eodhd_events, eodhd_err = _fetch_eodhd(from_str, to_str, tickers)
            events = eodhd_events
            error_hint = eodhd_err or error_hint
            if events:
                provider = "eodhd"
            else:
                provider = "fmp"
    elif eodhd.has_api_key():
        events, error_hint = _fetch_eodhd(from_str, to_str, tickers)
        provider = "eodhd" if events else "eodhd"

    if events:
        _write_cache(cache_key, events)

    return _enrich_events(events, date.today()), provider, error_hint


def build_earnings_payload(horizon_days: int, force_refresh: bool = False) -> Dict[str, Any]:
    today = date.today()
    horizon = max(1, min(60, int(horizon_days)))
    to_date = today + timedelta(days=horizon)
    tickers = fetch_tracked_us_tickers()
    configured = is_earnings_api_configured()

    if not tickers:
        return {
            "events": [],
            "provider": "none",
            "configured": configured,
            "ticker_count": 0,
            "horizon_days": horizon,
            "from_date": today.isoformat(),
            "to_date": to_date.isoformat(),
            "message": "暂无美股监控标的，请先在投资主题中添加标的。",
            "error_hint": None,
        }

    if not configured:
        return {
            "events": [],
            "provider": "none",
            "configured": False,
            "ticker_count": len(tickers),
            "horizon_days": horizon,
            "from_date": today.isoformat(),
            "to_date": to_date.isoformat(),
            "message": "未配置 FMP 或 EODHD API Key，无法拉取财报日历。",
            "error_hint": "missing_key",
        }

    events, provider, error_hint = fetch_earnings_calendar(
        today, to_date, tickers, force_refresh=force_refresh
    )
    message = None
    if not events:
        if error_hint == "api_error":
            message = "API 返回错误（FMP/EODHD 财报接口可能不可用，请检查 Key 与套餐）。"
        elif error_hint == "request_failed":
            message = "请求财报数据失败，请稍后重试。"
        else:
            message = f"未来 {horizon} 天内暂无已跟踪标的的财报安排。"

    return {
        "events": events,
        "provider": provider,
        "configured": True,
        "ticker_count": len(tickers),
        "horizon_days": horizon,
        "from_date": today.isoformat(),
        "to_date": to_date.isoformat(),
        "message": message,
        "error_hint": error_hint,
    }
