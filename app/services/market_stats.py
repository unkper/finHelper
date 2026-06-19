"""美股市值、股本等基本面行情（FMP quote 扩展字段）。"""
from typing import Any, Dict, List, Optional

from flask import current_app

from app.services.quote_client import http_get_json, parse_price
from app.services.quotes import fetch_us_quotes

FMP_QUOTE_URL = "https://financialmodelingprep.com/stable/quote"


def _parse_positive(value: Any) -> Optional[float]:
    parsed = parse_price(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def fetch_us_market_stats(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    返回 ticker -> {price, market_cap, shares_outstanding, pe, eps, source}。
    无 FMP Key 时仅填充 price（来自统一行情链）。
    """
    tickers = [(t or "").strip().upper() for t in tickers if (t or "").strip()]
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        return {}

    result: Dict[str, Dict[str, Any]] = {
        symbol: {
            "price": None,
            "market_cap": None,
            "shares_outstanding": None,
            "pe": None,
            "eps": None,
            "source": "none",
        }
        for symbol in tickers
    }

    prices = fetch_us_quotes(tickers)
    for symbol, price in prices.items():
        if symbol in result:
            result[symbol]["price"] = price
            if result[symbol]["source"] == "none":
                result[symbol]["source"] = "quote"

    api_key = current_app.config.get("FMP_API_KEY", "")
    if not api_key:
        return result

    payload = http_get_json(
        FMP_QUOTE_URL,
        {"symbol": ",".join(tickers), "apikey": api_key},
    )
    if not isinstance(payload, list):
        return result

    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = (item.get("symbol") or "").upper()
        if symbol not in result:
            continue
        row = result[symbol]
        price = _parse_positive(item.get("price")) or row.get("price")
        market_cap = _parse_positive(item.get("marketCap"))
        shares = _parse_positive(item.get("sharesOutstanding"))
        pe = _parse_positive(item.get("pe"))
        eps = parse_price(item.get("eps"))
        if price is not None:
            row["price"] = price
        if market_cap is not None:
            row["market_cap"] = market_cap
        if shares is not None:
            row["shares_outstanding"] = shares
        if pe is not None:
            row["pe"] = pe
        if eps is not None:
            row["eps"] = eps
        row["source"] = "fmp"
    return result
