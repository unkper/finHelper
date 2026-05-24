"""美股日 K 历史行情（含缓存；优先 EODHD，回退 Alpha Vantage / FMP）。"""
import time
from typing import Dict, List

from flask import current_app

from app.services.quote_client import http_get_json, parse_price, normalize_us_tickers
from app.services.quote_cache import (
    invalidate_daily_cache,
    read_cached_daily_series,
    write_cached_daily_series,
)
from app.services.quote_providers import alpha_vantage, eodhd

FMP_HISTORY_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"


def _fetch_fmp_daily(ticker: str) -> List[Dict[str, float | str]]:
    api_key = current_app.config.get("FMP_API_KEY", "")
    if not api_key:
        return []
    payload = http_get_json(
        FMP_HISTORY_URL,
        {"symbol": ticker, "apikey": api_key},
    )
    if not isinstance(payload, list):
        return []

    points = []
    for bar in payload:
        if not isinstance(bar, dict):
            continue
        bar_date = bar.get("date")
        close = parse_price(bar.get("close"))
        if bar_date and close is not None:
            points.append({"date": bar_date, "close": close})
    points.sort(key=lambda item: item["date"])
    return points[-120:]


def _batch_fetch_delay() -> float:
    if eodhd.has_api_key():
        return eodhd.daily_series_batch_delay()
    if alpha_vantage.has_api_key():
        return alpha_vantage.daily_series_batch_delay()
    return 0.3


def _fetch_daily_from_providers(ticker: str) -> List[Dict[str, float | str]]:
    """优先 EODHD，再 Alpha Vantage，最后 FMP。"""
    if eodhd.has_api_key():
        series = eodhd.fetch_us_daily_series(ticker)
        if series:
            return series

    if alpha_vantage.has_api_key():
        series = alpha_vantage.fetch_us_daily_series(ticker)
        if series:
            return series

    return _fetch_fmp_daily(ticker)


def fetch_daily_series(
    ticker: str,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> List[Dict[str, float | str]]:
    """获取单只股票日 K 收盘价序列（优先读缓存，再调 EODHD）。"""
    symbol = (ticker or "").strip().upper()
    if not symbol:
        return []

    if force_refresh:
        invalidate_daily_cache([symbol])

    if use_cache:
        cached = read_cached_daily_series(symbol)
        if cached:
            return cached

    series = _fetch_daily_from_providers(symbol)
    if series:
        if use_cache:
            write_cached_daily_series(symbol, series)
        return series

    if use_cache:
        stale = read_cached_daily_series(symbol, allow_stale=True)
        if stale:
            return stale
    return []


def fetch_daily_series_batch(
    tickers: List[str],
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Dict[str, List[Dict[str, float | str]]]:
    """批量获取日 K；命中缓存的不请求 API，未命中则逐个调外部数据源。"""
    result: Dict[str, List[Dict[str, float | str]]] = {}
    symbols = normalize_us_tickers(tickers)

    if force_refresh and symbols:
        invalidate_daily_cache(symbols)

    pending: List[str] = []
    for symbol in symbols:
        if use_cache:
            cached = read_cached_daily_series(symbol)
            if cached:
                result[symbol] = cached
                continue
        pending.append(symbol)

    delay = _batch_fetch_delay()
    for index, symbol in enumerate(pending):
        if index > 0 and delay > 0:
            time.sleep(delay)
        series = fetch_daily_series(symbol, use_cache=use_cache, force_refresh=False)
        if series:
            result[symbol] = series
        elif use_cache:
            stale = read_cached_daily_series(symbol, allow_stale=True)
            if stale:
                result[symbol] = stale

    return result
