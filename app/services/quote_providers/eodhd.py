"""EOD Historical Data (EODHD) 美股行情（实时价批量 + 日 K 历史）。"""
import json
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from flask import current_app

from app.services.api_usage import record_api_call

from app.services.quote_client import chunk_list, normalize_us_tickers, parse_price

EODHD_BASE = "https://eodhd.com/api"
REALTIME_BATCH_SIZE = 15
REALTIME_BATCH_DELAY_SEC = 0.25
DAILY_LOOKBACK_DAYS = 180
_FEATURE_COOLDOWN_SEC = 24 * 3600

# 套餐不含某接口时（如 403），冷却期内不再请求以免刷屏
_FEATURE_COOLDOWN_UNTIL: Dict[str, float] = {}


def _api_key() -> str:
    return current_app.config.get("EODHD_API_KEY", "")


def has_api_key() -> bool:
    return bool(_api_key())


def _feature_on_cooldown(feature: str) -> bool:
    until = _FEATURE_COOLDOWN_UNTIL.get(feature, 0)
    return time.time() < until


def _set_feature_cooldown(feature: str) -> None:
    _FEATURE_COOLDOWN_UNTIL[feature] = time.time() + _FEATURE_COOLDOWN_SEC


def _http_get_json(path: str, params: Dict[str, str], *, feature: str = "") -> Any:
    """EODHD GET；403/401 时静默降级并进入冷却。"""
    if feature and _feature_on_cooldown(feature):
        return None

    full_url = f"{EODHD_BASE}/{path.lstrip('/')}?{urlencode(params)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    api_proxy = current_app.config.get("API_PROXY")
    record_api_call("eodhd")
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
        print(f"Quote HTTP 请求失败: {full_url} -> HTTP Error {exc.code}: {exc.reason}")
        return None
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"Quote HTTP 请求失败: {full_url} -> {exc}")
        return None


def to_eodhd_symbol(ticker: str) -> str:
    symbol = (ticker or "").strip().upper()
    if not symbol:
        return ""
    if "." in symbol:
        return symbol
    return f"{symbol}.US"


def from_eodhd_symbol(code: str) -> str:
    return (code or "").split(".")[0].upper()


def _parse_realtime_payload(payload, requested: Set[str]) -> Dict[str, float]:
    quotes: Dict[str, float] = {}
    items: List[dict] = []
    if isinstance(payload, list):
        items = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict) and payload.get("close") is not None:
        items = [payload]

    for item in items:
        code = item.get("code") or ""
        ticker = from_eodhd_symbol(code)
        if requested and ticker not in requested:
            continue
        price = parse_price(item.get("close"))
        if ticker and price is not None:
            quotes[ticker] = price
    return quotes


def fetch_us_quotes(tickers: List[str]) -> Dict[str, float]:
    """EODHD 实时/延迟价，支持 s= 参数一次请求多标的。"""
    api_key = _api_key()
    symbols = normalize_us_tickers(tickers)
    if not api_key or not symbols:
        return {}

    quotes: Dict[str, float] = {}
    eodhd_symbols = [to_eodhd_symbol(symbol) for symbol in symbols]
    batches = chunk_list(eodhd_symbols, REALTIME_BATCH_SIZE)
    for index, batch in enumerate(batches):
        if index > 0:
            time.sleep(REALTIME_BATCH_DELAY_SEC)

        first = batch[0]
        params = {"api_token": api_key, "fmt": "json"}
        if len(batch) > 1:
            params["s"] = ",".join(batch[1:])

        payload = _http_get_json(f"real-time/{first}", params)
        if payload is None:
            continue

        batch_requested = {from_eodhd_symbol(item) for item in batch}
        quotes.update(_parse_realtime_payload(payload, batch_requested))

    return quotes


def fetch_us_daily_series(ticker: str) -> List[Dict[str, float | str]]:
    """EODHD 日 K 收盘价序列（/api/eod/{symbol}.US）。"""
    api_key = _api_key()
    symbol = (ticker or "").strip().upper()
    if not api_key or not symbol:
        return []

    start = (date.today() - timedelta(days=DAILY_LOOKBACK_DAYS)).isoformat()
    payload = _http_get_json(
        f"eod/{to_eodhd_symbol(symbol)}",
        {"api_token": api_key, "fmt": "json", "from": start, "order": "a"},
        feature="eod",
    )
    if not isinstance(payload, list):
        return []

    points = []
    for bar in payload:
        if not isinstance(bar, dict):
            continue
        bar_date = bar.get("date")
        close = parse_price(bar.get("adjusted_close")) or parse_price(bar.get("close"))
        open_ = parse_price(bar.get("open"))
        high = parse_price(bar.get("high"))
        low = parse_price(bar.get("low"))
        if not bar_date or close is None:
            continue
        point = {"date": bar_date, "close": close}
        if open_ is not None and high is not None and low is not None:
            point["open"] = open_
            point["high"] = high
            point["low"] = low
        points.append(point)
    points.sort(key=lambda item: item["date"])
    return points[-120:]


def daily_series_batch_delay() -> float:
    return REALTIME_BATCH_DELAY_SEC if has_api_key() else 0.3


def is_news_feature_on_cooldown() -> bool:
    return _feature_on_cooldown("news")


def _sentiment_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return "中性"
    try:
        polarity = float(raw.get("polarity", 0))
    except (TypeError, ValueError):
        return "中性"
    if polarity >= 0.2:
        return "偏正面"
    if polarity <= -0.2:
        return "偏负面"
    return "中性"


def _normalize_news_item(item: dict, *, content_max: int = 300) -> Dict[str, Any]:
    content = (item.get("content") or "").strip()
    if len(content) > content_max:
        content = content[: content_max - 1] + "…"
    tags_raw = item.get("tags") or []
    tags = [str(t).strip() for t in tags_raw if str(t).strip()] if isinstance(tags_raw, list) else []
    return {
        "date": str(item.get("date") or ""),
        "title": str(item.get("title") or "").strip(),
        "summary": content,
        "link": str(item.get("link") or "").strip(),
        "tags": tags,
        "sentiment_label": _sentiment_label(item.get("sentiment")),
    }


def fetch_financial_news(
    *,
    symbol: str | None = None,
    tag: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 8,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """EODHD 财经新闻（/api/news），需 s 或 t 之一。"""
    api_key = _api_key()
    if not api_key:
        return []
    if not symbol and not tag:
        return []

    params: Dict[str, str] = {
        "api_token": api_key,
        "fmt": "json",
        "limit": str(max(1, min(50, limit))),
        "offset": str(max(0, offset)),
    }
    if symbol:
        params["s"] = to_eodhd_symbol(symbol) if "." not in symbol else symbol
    if tag:
        params["t"] = tag.strip()
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date

    payload = _http_get_json("news", params, feature="news")
    if not isinstance(payload, list):
        return []

    result: List[Dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict) and item.get("title"):
            result.append(_normalize_news_item(item))
    return result


def fetch_economic_events(
    *,
    from_date: str,
    to_date: str,
    country: str | None = "US",
    limit: int = 30,
) -> List[Dict[str, str]]:
    """EODHD 宏观日历（/api/economic-events）；套餐不含时静默返回空列表。"""
    api_key = _api_key()
    if not api_key or not from_date or not to_date:
        return []
    if _feature_on_cooldown("economic_events"):
        return []

    params: Dict[str, str] = {
        "api_token": api_key,
        "fmt": "json",
        "from": from_date,
        "to": to_date,
        "limit": str(max(1, min(100, limit))),
    }
    if country:
        params["country"] = country

    payload = _http_get_json("economic-events", params, feature="economic_events")
    if not isinstance(payload, list):
        return []

    result: List[Dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("type") or item.get("event") or item.get("name") or "").strip()
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
            "date": str(item.get("date") or item.get("datetime") or ""),
            "title": name,
            "country": str(item.get("country") or ""),
            "summary": "，".join(detail_parts) if detail_parts else "",
        })
    return result
