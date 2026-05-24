"""Alpha Vantage 美股行情（现价批量 + 日 K 历史）。"""
import time
from typing import Dict, List, Set

from flask import current_app

from app.services.quote_client import chunk_list, http_get_json, parse_price

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
BULK_BATCH_SIZE = 100
GLOBAL_QUOTE_DELAY_SEC = 0.25
DAILY_SERIES_DELAY_SEC = 12.0  # 免费档约 5 次/分钟，批量拉历史时间隔


def _api_key() -> str:
    return current_app.config.get("ALPHA_VANTAGE_API_KEY", "")


def has_api_key() -> bool:
    return bool(_api_key())


def _is_throttled(payload: dict) -> bool:
    return bool(payload.get("Note") or payload.get("Information") or payload.get("Error Message"))


def _parse_bulk_payload(payload: dict, requested: Set[str]) -> Dict[str, float]:
    if not isinstance(payload, dict) or _is_throttled(payload):
        return {}

    quotes: Dict[str, float] = {}
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        symbol = (item.get("symbol") or "").upper()
        if symbol not in requested:
            continue
        price = parse_price(item.get("close")) or parse_price(item.get("extended_hours_quote"))
        if price is not None:
            quotes[symbol] = price
    return quotes


def _parse_daily_series(payload: dict) -> List[Dict[str, float | str]]:
    if not isinstance(payload, dict) or _is_throttled(payload):
        return []

    series_raw = payload.get("Time Series (Daily)") or {}
    points = []
    for bar_date, bar in series_raw.items():
        close = parse_price(bar.get("4. close"))
        if close is not None:
            points.append({"date": bar_date, "close": close})
    points.sort(key=lambda item: item["date"])
    return points


def fetch_us_daily_series(ticker: str) -> List[Dict[str, float | str]]:
    """使用 ALPHA_VANTAGE_API_KEY 拉取单标的日 K（function=TIME_SERIES_DAILY）。"""
    api_key = _api_key()
    symbol = (ticker or "").strip().upper()
    if not api_key or not symbol:
        return []

    payload = http_get_json(
        ALPHA_VANTAGE_URL,
        {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
            "datatype": "json",
            "apikey": api_key,
        },
    )
    series = _parse_daily_series(payload)
    if not series and isinstance(payload, dict) and _is_throttled(payload):
        print(f"Alpha Vantage 日 K 限频或未授权: {symbol} -> {payload.get('Note') or payload.get('Information')}")
    return series


def daily_series_batch_delay() -> float:
    """批量拉历史时的请求间隔（秒）。"""
    return DAILY_SERIES_DELAY_SEC if has_api_key() else 0.3


def _fetch_bulk_batch(symbols: List[str], api_key: str) -> Dict[str, float]:
    payload = http_get_json(
        ALPHA_VANTAGE_URL,
        {
            "function": "REALTIME_BULK_QUOTES",
            "symbol": ",".join(symbols),
            "datatype": "json",
            "apikey": api_key,
        },
    )
    if not isinstance(payload, dict):
        return {}
    return _parse_bulk_payload(payload, set(symbols))


def _fetch_global_quote(symbol: str, api_key: str) -> float | None:
    payload = http_get_json(
        ALPHA_VANTAGE_URL,
        {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "datatype": "json",
            "apikey": api_key,
        },
    )
    if not isinstance(payload, dict) or _is_throttled(payload):
        return None

    quote = payload.get("Global Quote") or {}
    return parse_price(quote.get("05. price"))


def fetch_us_quotes(tickers: List[str]) -> Dict[str, float]:
    api_key = _api_key()
    if not api_key or not tickers:
        return {}

    quotes: Dict[str, float] = {}
    for batch in chunk_list(tickers, BULK_BATCH_SIZE):
        quotes.update(_fetch_bulk_batch(batch, api_key))

    missing = [symbol for symbol in tickers if symbol not in quotes]
    for index, symbol in enumerate(missing):
        if index > 0:
            time.sleep(GLOBAL_QUOTE_DELAY_SEC)
        price = _fetch_global_quote(symbol, api_key)
        if price is not None:
            quotes[symbol] = price

    return quotes
