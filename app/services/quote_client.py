"""股票行情请求的通用工具。"""
import json
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from flask import current_app

from app.services.api_usage import infer_provider_from_url, record_api_call


def normalize_us_tickers(tickers: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for raw in tickers:
        symbol = (raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)
    return result


def chunk_list(items: List[str], size: int) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def http_get_json(url: str, params: Optional[Dict[str, str]] = None) -> Any:
    full_url = f"{url}?{urlencode(params)}" if params else url
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    api_proxy = current_app.config.get("API_PROXY")
    provider = infer_provider_from_url(full_url)
    if provider:
        record_api_call(provider)
    try:
        if api_proxy:
            opener = build_opener(ProxyHandler({"http": api_proxy, "https": api_proxy}))
        else:
            opener = build_opener()
        request_obj = Request(full_url, headers=headers)
        with opener.open(request_obj, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"Quote HTTP 请求失败: {full_url} -> {exc}")
        return None


def parse_price(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
