"""Financial Modeling Prep 美股行情与辅助数据（主数据源）。"""
import json
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from flask import current_app

from app.services.api_usage import record_api_call
from app.services.quote_client import chunk_list, http_get_json, normalize_us_tickers, parse_price

FMP_BASE = "https://financialmodelingprep.com/stable"
FMP_QUOTE_URL = f"{FMP_BASE}/quote"
FMP_BATCH_QUOTE_URL = f"{FMP_BASE}/batch-quote"
FMP_HISTORY_URL = f"{FMP_BASE}/historical-price-eod/full"
FMP_STOCK_NEWS_URL = f"{FMP_BASE}/news/stock"
FMP_ECONOMIC_CALENDAR_URL = f"{FMP_BASE}/economic-calendar"

DAILY_LOOKBACK_DAYS = 180
REALTIME_BATCH_SIZE = 20
REALTIME_BATCH_DELAY_SEC = 0.15
_FEATURE_COOLDOWN_SEC = 24 * 3600
_FEATURE_COOLDOWN_UNTIL: Dict[str, float] = {}


def _api_key() -> str:
    return current_app.config.get("FMP_API_KEY", "") or ""


def has_api_key() -> bool:
    return bool(_api_key())


def _feature_on_cooldown(feature: str) -> bool:
    until = _FEATURE_COOLDOWN_UNTIL.get(feature, 0)
    return time.time() < until


def _set_feature_cooldown(feature: str) -> None:
    _FEATURE_COOLDOWN_UNTIL[feature] = time.time() + _FEATURE_COOLDOWN_SEC


def is_news_feature_on_cooldown() -> bool:
    return _feature_on_cooldown("news")


def is_economic_calendar_on_cooldown() -> bool:
    return _feature_on_cooldown("economic_calendar")


def _http_get_json(
    url: str,
    params: Dict[str, str],
    *,
    feature: str = "",
) -> Any:
    """FMP GET；403/401 时进入 feature 冷却。"""
    if feature and _feature_on_cooldown(feature):
        return None

    full_url = f"{url}?{urlencode(params)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    api_proxy = current_app.config.get("API_PROXY")
    record_api_call("fmp")
    try:
        if api_proxy:
            opener = build_opener(ProxyHandler({"http": api_proxy, "https": api_proxy}))
        else:
            opener = build_opener()
        request_obj = Request(full_url, headers=headers)
        with opener.open(request_obj, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            if feature:
                _set_feature_cooldown(feature)
            return None
        print(f"FMP HTTP 请求失败: {full_url} -> HTTP Error {exc.code}: {exc.reason}")
        return None
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"FMP HTTP 请求失败: {full_url} -> {exc}")
        return None


def _parse_quote_payload(payload: Any, requested: Optional[set] = None) -> Dict[str, float]:
    quotes: Dict[str, float] = {}
    if not isinstance(payload, list):
        return quotes
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = (item.get("symbol") or "").upper()
        if requested and symbol not in requested:
            continue
        price = parse_price(item.get("price"))
        if symbol and price is not None:
            quotes[symbol] = price
    return quotes


def fetch_us_quotes(tickers: List[str]) -> Dict[str, float]:
    """批量现价；优先 batch-quote，失败时回退 quote。"""
    api_key = _api_key()
    symbols = normalize_us_tickers(tickers)
    if not api_key or not symbols:
        return {}

    quotes: Dict[str, float] = {}
    batches = chunk_list(symbols, REALTIME_BATCH_SIZE)
    for index, batch in enumerate(batches):
        if index > 0:
            time.sleep(REALTIME_BATCH_DELAY_SEC)

        requested = set(batch)
        payload = _http_get_json(
            FMP_BATCH_QUOTE_URL,
            {"symbols": ",".join(batch), "apikey": api_key},
        )
        batch_quotes = _parse_quote_payload(payload, requested)
        if not batch_quotes:
            payload = http_get_json(
                FMP_QUOTE_URL,
                {"symbol": ",".join(batch), "apikey": api_key},
            )
            batch_quotes = _parse_quote_payload(payload, requested)
        quotes.update(batch_quotes)
    return quotes


def fetch_us_daily_series(
    ticker: str,
    *,
    from_date: str | None = None,
) -> List[Dict[str, float | str]]:
    """日 K（含 OHLC），最近约 120 根。"""
    api_key = _api_key()
    symbol = (ticker or "").strip().upper()
    if not api_key or not symbol:
        return []

    if not from_date:
        from_date = (date.today() - timedelta(days=DAILY_LOOKBACK_DAYS)).isoformat()

    payload = _http_get_json(
        FMP_HISTORY_URL,
        {"symbol": symbol, "from": from_date, "apikey": api_key},
        feature="eod",
    )
    if not isinstance(payload, list):
        return []

    points: List[Dict[str, float | str]] = []
    for bar in payload:
        if not isinstance(bar, dict):
            continue
        bar_date = bar.get("date")
        close = parse_price(bar.get("close")) or parse_price(bar.get("adjClose"))
        open_ = parse_price(bar.get("open"))
        high = parse_price(bar.get("high"))
        low = parse_price(bar.get("low"))
        if not bar_date or close is None:
            continue
        point: Dict[str, float | str] = {"date": bar_date, "close": close}
        if open_ is not None and high is not None and low is not None:
            point["open"] = open_
            point["high"] = high
            point["low"] = low
        points.append(point)
    points.sort(key=lambda item: str(item["date"]))
    return points[-120:]


def daily_series_batch_delay() -> float:
    return REALTIME_BATCH_DELAY_SEC if has_api_key() else 0.3


def _normalize_news_item(item: dict, *, content_max: int = 300) -> Dict[str, Any]:
    text = (item.get("text") or item.get("content") or "").strip()
    if len(text) > content_max:
        text = text[: content_max - 1] + "…"
    symbol = (item.get("symbol") or "").strip().upper()
    tags = [symbol] if symbol else []
    site = str(item.get("site") or "").strip()
    if site and site not in tags:
        tags.append(site)
    return {
        "date": str(item.get("publishedDate") or item.get("date") or ""),
        "title": str(item.get("title") or "").strip(),
        "summary": text,
        "link": str(item.get("url") or item.get("link") or "").strip(),
        "tags": tags,
        "sentiment_label": "中性",
    }


def fetch_stock_news(
    symbol: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 8,
    page: int = 0,
) -> List[Dict[str, Any]]:
    """按 ticker 搜索股票新闻（FMP news/stock）。"""
    api_key = _api_key()
    ticker = (symbol or "").strip().upper()
    if not api_key or not ticker:
        return []

    params: Dict[str, str] = {
        "symbols": ticker,
        "page": str(max(0, page)),
        "limit": str(max(1, min(50, limit))),
        "apikey": api_key,
    }
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date

    payload = _http_get_json(FMP_STOCK_NEWS_URL, params, feature="news")
    if not isinstance(payload, list):
        return []

    result: List[Dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict) and item.get("title"):
            result.append(_normalize_news_item(item))
    return result


def fetch_economic_calendar(
    *,
    from_date: str,
    to_date: str,
    country: str | None = "US",
    limit: int = 30,
) -> List[Dict[str, str]]:
    """宏观数据发布日历。"""
    api_key = _api_key()
    if not api_key or not from_date or not to_date:
        return []

    params: Dict[str, str] = {
        "from": from_date,
        "to": to_date,
        "apikey": api_key,
    }
    payload = _http_get_json(
        FMP_ECONOMIC_CALENDAR_URL,
        params,
        feature="economic_calendar",
    )
    if not isinstance(payload, list):
        return []

    country_upper = (country or "").upper()
    result: List[Dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        item_country = str(item.get("country") or "").upper()
        if country_upper and item_country and item_country != country_upper:
            continue
        name = str(item.get("event") or item.get("name") or "").strip()
        if not name:
            continue
        actual = item.get("actual")
        estimate = item.get("estimate") or item.get("forecast")
        previous = item.get("previous")
        detail_parts = []
        if actual is not None and str(actual).strip():
            detail_parts.append(f"实际 {actual}")
        if estimate is not None and str(estimate).strip():
            detail_parts.append(f"预期 {estimate}")
        if previous is not None and str(previous).strip():
            detail_parts.append(f"前值 {previous}")
        result.append({
            "date": str(item.get("date") or "")[:10],
            "title": name,
            "country": str(item.get("country") or ""),
            "summary": "，".join(detail_parts) if detail_parts else "",
        })
        if len(result) >= limit:
            break
    return result
