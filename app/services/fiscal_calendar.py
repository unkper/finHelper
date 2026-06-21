"""财季映射：日历季 YYYY-Qn 与公司财年 FY/Q（SEC 财报）。"""
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

from flask import current_app

from app.services.quote_client import http_get_json, parse_price

FMP_PROFILE_URL = "https://financialmodelingprep.com/stable/profile"

# 常见美股非自然年财年结束月（FMP 不可用时的回退）
_TICKER_FY_END_MONTH = {
    "MU": 8,
    "AAPL": 9,
    "MSFT": 6,
    "NVDA": 1,
    "ORCL": 5,
    "ADBE": 11,
    "COST": 8,
    "WMT": 1,
}


def calendar_period_from_date(d: date) -> str:
    """报告期末日期 → 日历季 YYYY-Qn。"""
    quarter = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{quarter}"


def _parse_date(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    text = str(raw).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text.replace("\n", " ").strip(), fmt).date()
        except ValueError:
            continue
    # "May 29, \n 2025" style
    cleaned = " ".join(text.split())
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def infer_filing_fy_fq(period_end: date, fy_end_month: int) -> Tuple[int, int]:
    """
    根据财年结束月推断 filing_fy / filing_fq。
    例：MU fy_end=8，2025-05-29 → FY2025 Q3。
    """
    fy_end_month = max(1, min(12, int(fy_end_month)))
    if period_end.month <= fy_end_month:
        filing_fy = period_end.year
    else:
        filing_fy = period_end.year + 1

    fy_start_month = (fy_end_month % 12) + 1
    month = period_end.month
    if month >= fy_start_month:
        months_since_start = month - fy_start_month
    else:
        months_since_start = month + 12 - fy_start_month
    filing_fq = months_since_start // 3 + 1
    return filing_fy, filing_fq


def _fy_end_from_fmp_profile(ticker: str) -> Optional[int]:
    api_key = current_app.config.get("FMP_API_KEY", "")
    if not api_key:
        return None
    payload = http_get_json(
        FMP_PROFILE_URL,
        {"symbol": ticker.strip().upper(), "apikey": api_key},
    )
    if isinstance(payload, list) and payload:
        row = payload[0]
    elif isinstance(payload, dict):
        row = payload
    else:
        return None
    raw = row.get("fiscalYearEnd") or row.get("fiscalYearEndMonth")
    if raw is None:
        return None
    text = str(raw).strip()
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    lower = text.lower()
    for name, num in month_names.items():
        if name in lower:
            return num
    parsed = parse_price(text)
    if parsed is not None and 1 <= int(parsed) <= 12:
        return int(parsed)
    return None


def resolve_fy_end_month(ticker: str | None) -> int:
    """优先 FMP profile，其次 ticker 映射表，默认 12（自然年）。"""
    symbol = (ticker or "").strip().upper()
    if symbol:
        try:
            month = _fy_end_from_fmp_profile(symbol)
            if month:
                return month
        except Exception:
            pass
        if symbol in _TICKER_FY_END_MONTH:
            return _TICKER_FY_END_MONTH[symbol]
    return 12


def build_period_context(
    period_end_raw: Any,
    *,
    ticker: str | None = None,
    fy_end_month: int | None = None,
) -> Dict[str, Any]:
    """从 period_end 生成 calendar_period、filing_fy、filing_fq。"""
    period_end = _parse_date(period_end_raw)
    if not period_end:
        raise ValueError("无法解析报告期末日期")
    fy_month = fy_end_month if fy_end_month is not None else resolve_fy_end_month(ticker)
    filing_fy, filing_fq = infer_filing_fy_fq(period_end, fy_month)
    return {
        "period_end": period_end.isoformat(),
        "calendar_period": calendar_period_from_date(period_end),
        "filing_fy": filing_fy,
        "filing_fq": filing_fq,
        "fiscal_year_end_month": fy_month,
    }
