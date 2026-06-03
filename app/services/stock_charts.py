"""构建股票走势页所需的图表数据。"""
import math
from typing import Any, Dict, List, Tuple

from app.services.investment import fetch_tracked_assets_overview

DEFAULT_STOCKS_PER_PAGE = 8
MIN_STOCKS_PER_PAGE = 4
MAX_STOCKS_PER_PAGE = 24
from app.services.quote_cache import invalidate_daily_cache, invalidate_quote_cache
from app.services.macd import SIGNAL_LABELS, analyze_macd_from_series
from app.services.quote_providers import eodhd
from app.services.quotes import fetch_us_quotes
from app.services.settings import get_macd_alert_settings
from app.services.stock_history import fetch_daily_series_batch


def _series_has_ohlc(series: List[Dict[str, Any]]) -> bool:
    """EODHD 日 K 含 open/high/low 时可绘制蜡烛图。"""
    if len(series) < 2:
        return False
    for point in series:
        if (
            point.get("open") is None
            or point.get("high") is None
            or point.get("low") is None
        ):
            return False
    return True


def _calc_daily_change_pct(series: List[Dict[str, Any]]) -> float | None:
    """最近一个交易日的涨跌幅（相对前一交易日收盘价）。"""
    if len(series) < 2:
        return None
    prev_close = series[-2]["close"]
    last_close = series[-1]["close"]
    if not prev_close:
        return None
    return round((last_close - prev_close) / prev_close * 100, 2)


def _calc_period_change_pct(
    series: List[Dict[str, Any]],
    start_index: int = 0,
    end_index: int | None = None,
) -> float | None:
    """区间内涨跌幅：以区间首尾收盘价计算。"""
    if not series:
        return None
    end_index = len(series) - 1 if end_index is None else end_index
    start_index = max(0, min(start_index, len(series) - 1))
    end_index = max(0, min(end_index, len(series) - 1))
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    first_close = series[start_index]["close"]
    last_close = series[end_index]["close"]
    if not first_close:
        return None
    return round((last_close - first_close) / first_close * 100, 2)


def normalize_stocks_pagination(
    page: int | str | None,
    per_page: int | str | None,
) -> Tuple[int, int]:
    try:
        page_num = int(page) if page is not None else 1
    except (TypeError, ValueError):
        page_num = 1
    try:
        size = int(per_page) if per_page is not None else DEFAULT_STOCKS_PER_PAGE
    except (TypeError, ValueError):
        size = DEFAULT_STOCKS_PER_PAGE
    page_num = max(1, page_num)
    size = max(MIN_STOCKS_PER_PAGE, min(MAX_STOCKS_PER_PAGE, size))
    return page_num, size


def paginate_asset_list(
    assets: List[Dict[str, Any]],
    page: int,
    per_page: int,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """返回当前页标的、总页数、校正后的页码。"""
    total = len(assets)
    if total == 0:
        return [], 0, 1
    total_pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    return assets[start : start + per_page], total_pages, page


def _asset_chart_row(
    item: Dict[str, Any],
    *,
    quotes: Dict[str, float],
    history_map: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    ticker = item["ticker"]
    series = history_map.get(ticker, [])
    current_price = quotes.get(ticker)
    if current_price is None and series:
        current_price = series[-1]["close"]

    use_candlestick = _series_has_ohlc(series)
    macd_info = analyze_macd_from_series(series)
    macd_signals = [
        {"type": s, "label": SIGNAL_LABELS.get(s, s)}
        for s in macd_info.get("signals", [])
    ]
    return {
        "ticker": ticker,
        "exchange": item["exchange"],
        "current_price": current_price,
        "change_pct": _calc_daily_change_pct(series),
        "themes": item["themes"],
        "alerts": item["alerts"],
        "series": series,
        "chart_type": "candlestick" if use_candlestick else "line",
        "macd": {
            **macd_info,
            "signal_labels": macd_signals,
        },
    }


def build_stock_chart_payload(
    force_refresh: bool = False,
    *,
    page: int = 1,
    per_page: int = DEFAULT_STOCKS_PER_PAGE,
    query: str = "",
) -> Dict[str, Any]:
    page, per_page = normalize_stocks_pagination(page, per_page)
    assets = fetch_tracked_assets_overview()
    assets.sort(key=lambda row: row["ticker"])

    q = (query or "").strip().upper()
    if q:
        assets = [item for item in assets if q in item["ticker"].upper()]

    theme_link_count = sum(len(item["themes"]) for item in assets)
    total_tickers = len(assets)

    if not assets:
        return {
            "assets": [],
            "summary": {
                "ticker_count": 0,
                "theme_link_count": 0,
                "eodhd_configured": eodhd.has_api_key(),
                "page": 1,
                "per_page": per_page,
                "total_pages": 0,
                "filtered": bool(q),
            },
            "macd_alerts": get_macd_alert_settings(),
        }

    page_assets, total_pages, page = paginate_asset_list(assets, page, per_page)

    us_tickers = [
        item["ticker"] for item in page_assets if item["exchange"] == "US"
    ]
    if force_refresh and us_tickers:
        invalidate_daily_cache(us_tickers)
        invalidate_quote_cache(us_tickers)

    quotes = (
        fetch_us_quotes(us_tickers, use_cache=True, force_refresh=force_refresh)
        if us_tickers else {}
    )
    history_map = (
        fetch_daily_series_batch(us_tickers, use_cache=True, force_refresh=force_refresh)
        if us_tickers else {}
    )

    payload_assets = [
        _asset_chart_row(item, quotes=quotes, history_map=history_map)
        for item in page_assets
    ]

    return {
        "assets": payload_assets,
        "summary": {
            "ticker_count": total_tickers,
            "theme_link_count": theme_link_count,
            "eodhd_configured": eodhd.has_api_key(),
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "page_count": len(payload_assets),
            "filtered": bool(q),
        },
        "macd_alerts": get_macd_alert_settings(),
    }
