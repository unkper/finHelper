import json
from typing import Dict, List
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from flask import current_app

# 修改为新的稳定接口路径
FMP_QUOTE_URL = "https://financialmodelingprep.com/stable/quote"


def fetch_us_quotes(tickers: List[str]) -> Dict[str, float]:
    """批量获取美股实时报价，适配新版 stable 接口。"""
    api_key = current_app.config.get("FMP_API_KEY", "")
    symbols = [t.strip().upper() for t in tickers if t and t.strip()]

    if not api_key or not symbols:
        return {}

    # 注意：如果 /stable/quote 不支持批量参数，我们需要循环请求
    # 这里先假设它支持用逗号分隔，如果不行，请参考下方的“循环方案”
    symbols_str = ",".join(symbols)
    url = f"{FMP_QUOTE_URL}?symbol={symbols_str}&apikey={api_key}"

    # 增加更像浏览器的 User-Agent
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    }
    print(url)

    api_proxy = current_app.config.get("API_PROXY")

    try:
        if api_proxy:
            opener = build_opener(ProxyHandler({"http": api_proxy, "https": api_proxy}))
        else:
            opener = build_opener()

        request_obj = Request(url, headers=headers)
        with opener.open(request_obj, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"FMP 行情获取失败: {exc}")
        return {}

    # 适配返回数据结构
    # 有些新接口返回的是直接的列表，有些是嵌套结构，需根据实际返回微调
    if not isinstance(payload, list):
        return {}

    quotes: Dict[str, float] = {}
    for item in payload:
        symbol = (item.get("symbol") or "").upper()
        price = item.get("price")
        if symbol and price is not None:
            quotes[symbol] = float(price)
    return quotes