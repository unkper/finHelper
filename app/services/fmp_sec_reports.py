"""FMP SEC 10-Q/10-K 财报 dates + JSON 拉取。"""
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import current_app

from app.database import get_db
from app.services.fmp_report_mapper import parse_fmp_report_json, preview_calendar_period
from app.services.quote_client import http_get_json

FMP_BASE = "https://financialmodelingprep.com/stable"
_DATES_URL = f"{FMP_BASE}/financial-reports-dates"
_JSON_URL = f"{FMP_BASE}/financial-reports-json"

_VALID_PERIODS = frozenset({"Q1", "Q2", "Q3", "Q4", "FY"})
_DATES_CACHE: Dict[str, Dict[str, Any]] = {}
_DATES_CACHE_TTL_SEC = 24 * 3600
_JSON_CACHE_TTL_SEC = 7 * 24 * 3600


def _cache_get_json(ticker: str, year: int | str, period: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    row = db.execute(
        """
        SELECT payload_json, fetched_at FROM fmp_report_json_cache
        WHERE ticker = ? AND fmp_year = ? AND fmp_period = ?
        """,
        (ticker.strip().upper(), int(year), str(period).upper()),
    ).fetchone()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
        if (datetime.now() - fetched).total_seconds() > _JSON_CACHE_TTL_SEC:
            return None
        data = json.loads(row["payload_json"])
        return data if isinstance(data, dict) else None
    except (ValueError, json.JSONDecodeError):
        return None


def _cache_set_json(ticker: str, year: int | str, period: str, payload: Dict[str, Any]) -> None:
    db = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        """
        INSERT INTO fmp_report_json_cache (ticker, fmp_year, fmp_period, payload_json, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticker, fmp_year, fmp_period) DO UPDATE SET
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at
        """,
        (
            ticker.strip().upper(),
            int(year),
            str(period).upper(),
            json.dumps(payload, ensure_ascii=False),
            now,
        ),
    )
    db.commit()


def _api_key() -> str:
    return current_app.config.get("FMP_API_KEY", "") or ""


def require_api_key() -> str:
    key = _api_key()
    if not key:
        raise ValueError("未配置 FMP_API_KEY，无法拉取 SEC 财报")
    return key


def fetch_report_dates(ticker: str) -> List[Dict[str, Any]]:
    """GET /stable/financial-reports-dates。"""
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("ticker 不能为空")

    cache_key = symbol
    cached = _DATES_CACHE.get(cache_key)
    if cached and time.time() - cached["ts"] < _DATES_CACHE_TTL_SEC:
        return list(cached["rows"])

    api_key = require_api_key()
    payload = http_get_json(_DATES_URL, {"symbol": symbol, "apikey": api_key})
    if not isinstance(payload, list):
        raise ValueError("FMP 未返回可用报告期列表")

    rows: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        year = item.get("fiscalYear") or item.get("year")
        period = str(item.get("period") or "").strip().upper()
        if year is None or period not in _VALID_PERIODS:
            continue
        rows.append({
            "symbol": symbol,
            "year": int(year),
            "period": period,
            "form_type": "10-K" if period == "FY" else "10-Q",
        })

    _DATES_CACHE[cache_key] = {"ts": time.time(), "rows": rows}
    return rows


def fetch_report_json(ticker: str, year: int | str, period: str) -> Dict[str, Any]:
    """GET /stable/financial-reports-json。"""
    symbol = ticker.strip().upper()
    period_code = str(period or "").strip().upper()
    if period_code not in _VALID_PERIODS:
        raise ValueError("period 须为 Q1–Q4 或 FY")

    api_key = require_api_key()
    cached = _cache_get_json(symbol, year, period_code)
    if cached is not None:
        return cached
    payload = http_get_json(
        _JSON_URL,
        {
            "symbol": symbol,
            "year": str(int(year)),
            "period": period_code,
            "apikey": api_key,
        },
    )
    if not isinstance(payload, dict):
        raise ValueError("FMP 未返回有效财报 JSON")
    _cache_set_json(symbol, year, period_code, payload)
    return payload


def _period_label(year: int, period: str, form_type: str) -> str:
    if period == "FY":
        return f"FY{year} 年报 (10-K)"
    return f"FY{year} {period} ({form_type})"


def list_selectable_periods(
    ticker: str,
    *,
    preview: bool = False,
    preview_year: int | None = None,
    preview_period: str | None = None,
) -> List[Dict[str, Any]]:
    """
    返回可选 FMP 报告期。
    preview=True 且指定 year/period 时，拉取 JSON 填充 calendar_period。
    """
    symbol = ticker.strip().upper()
    dates = fetch_report_dates(symbol)
    results: List[Dict[str, Any]] = []

    for row in dates:
        year = row["year"]
        period = row["period"]
        form_type = row["form_type"]
        entry: Dict[str, Any] = {
            "year": year,
            "period": period,
            "form_type": form_type,
            "label": _period_label(year, period, form_type),
            "calendar_period": None,
            "filing_fy": year if period != "FY" else None,
            "filing_fq": None if period == "FY" else period.replace("Q", ""),
        }
        if period != "FY":
            try:
                entry["filing_fq"] = int(period[1])
            except ValueError:
                entry["filing_fq"] = None

        if preview and preview_year == year and preview_period == period:
            try:
                payload = fetch_report_json(symbol, year, period)
                cal = preview_calendar_period(payload, ticker=symbol)
                if cal:
                    entry["calendar_period"] = cal
                    meta = payload.get("Cover Page")
                    if isinstance(meta, list):
                        from app.services.fmp_report_mapper import extract_cover_meta
                        cover = extract_cover_meta(payload)
                        if cover.get("period_end"):
                            entry["period_end"] = cover["period_end"]
            except Exception:
                pass

        results.append(entry)

    return results


def fetch_and_parse_fmp_report(
    ticker: str,
    year: int | str,
    period: str,
) -> Dict[str, Any]:
    """拉取 FMP JSON 并映射为 extracted_json。"""
    symbol = ticker.strip().upper()
    payload = fetch_report_json(symbol, year, period)
    return parse_fmp_report_json(
        payload,
        ticker=symbol,
        fmp_year=year,
        fmp_period=period,
    )
