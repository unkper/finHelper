"""构建股票走势页所需的图表数据。"""
from typing import Any, Dict, List

from app.services.investment import fetch_tracked_assets_overview
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


def _calc_change_pct(series: List[Dict[str, Any]]) -> float | None:
    if len(series) < 2:
        return None
    first_close = series[0]["close"]
    last_close = series[-1]["close"]
    if not first_close:
        return None
    return round((last_close - first_close) / first_close * 100, 2)


def build_stock_chart_payload(force_refresh: bool = False) -> Dict[str, Any]:
    assets = fetch_tracked_assets_overview()
    if not assets:
        return {
            "assets": [],
            "summary": {
                "ticker_count": 0,
                "theme_link_count": 0,
                "eodhd_configured": eodhd.has_api_key(),
            },
            "macd_alerts": get_macd_alert_settings(),
        }

    us_tickers = [item["ticker"] for item in assets if item["exchange"] == "US"]
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

    payload_assets = []
    theme_link_count = 0
    for item in assets:
        ticker = item["ticker"]
        series = history_map.get(ticker, [])
        current_price = quotes.get(ticker)
        if current_price is None and series:
            current_price = series[-1]["close"]

        theme_link_count += len(item["themes"])
        use_candlestick = _series_has_ohlc(series)
        macd_info = analyze_macd_from_series(series)
        macd_signals = [
            {"type": s, "label": SIGNAL_LABELS.get(s, s)}
            for s in macd_info.get("signals", [])
        ]
        payload_assets.append({
            "ticker": ticker,
            "exchange": item["exchange"],
            "current_price": current_price,
            "change_pct": _calc_change_pct(series),
            "themes": item["themes"],
            "alerts": item["alerts"],
            "series": series,
            "chart_type": "candlestick" if use_candlestick else "line",
            "macd": {
                **macd_info,
                "signal_labels": macd_signals,
            },
        })

    payload_assets.sort(key=lambda row: row["ticker"])
    return {
        "assets": payload_assets,
        "summary": {
            "ticker_count": len(payload_assets),
            "theme_link_count": theme_link_count,
            "eodhd_configured": eodhd.has_api_key(),
        },
        "macd_alerts": get_macd_alert_settings(),
    }
