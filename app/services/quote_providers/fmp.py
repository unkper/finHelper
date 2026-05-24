"""Financial Modeling Prep 美股行情。"""
from typing import Dict, List

from flask import current_app

from app.services.quote_client import http_get_json, parse_price

FMP_QUOTE_URL = "https://financialmodelingprep.com/stable/quote"


def fetch_us_quotes(tickers: List[str]) -> Dict[str, float]:
    api_key = current_app.config.get("FMP_API_KEY", "")
    if not api_key or not tickers:
        return {}

    payload = http_get_json(
        FMP_QUOTE_URL,
        {"symbol": ",".join(tickers), "apikey": api_key},
    )
    if not isinstance(payload, list):
        return {}

    quotes: Dict[str, float] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        symbol = (item.get("symbol") or "").upper()
        price = parse_price(item.get("price"))
        if symbol and price is not None:
            quotes[symbol] = price
    return quotes
