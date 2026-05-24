"""EOD Historical Data (EODHD) 美股行情（实时价批量 + 日 K 历史）。"""
import time
from datetime import date, timedelta
from typing import Dict, List, Set

from flask import current_app

from app.services.quote_client import chunk_list, http_get_json, normalize_us_tickers, parse_price

EODHD_BASE = "https://eodhd.com/api"
REALTIME_BATCH_SIZE = 15
REALTIME_BATCH_DELAY_SEC = 0.25
DAILY_LOOKBACK_DAYS = 180


def _api_key() -> str:
    return current_app.config.get("EODHD_API_KEY", "")


def has_api_key() -> bool:
    return bool(_api_key())


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

        payload = http_get_json(f"{EODHD_BASE}/real-time/{first}", params)
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
    payload = http_get_json(
        f"{EODHD_BASE}/eod/{to_eodhd_symbol(symbol)}",
        {"api_token": api_key, "fmt": "json", "from": start, "order": "a"},
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
