"""统一美股行情入口，按顺序尝试多个数据源并合并结果（带数据库缓存）。"""
from typing import Dict, List, Tuple, Callable

from app.services.quote_client import normalize_us_tickers
from app.services.quote_cache import (
    invalidate_quote_cache,
    read_cached_quotes,
    write_cached_quotes,
)
from app.services.quote_providers import alpha_vantage, eodhd, fmp

ProviderFn = Callable[[List[str]], Dict[str, float]]

PROVIDERS: Tuple[Tuple[str, ProviderFn], ...] = (
    ("fmp", fmp.fetch_us_quotes),
    ("alpha_vantage", alpha_vantage.fetch_us_quotes),
    ("eodhd", eodhd.fetch_us_quotes),
)


def _fetch_from_providers(tickers: List[str]) -> Dict[str, float]:
    quotes: Dict[str, float] = {}
    for name, provider in PROVIDERS:
        missing = [symbol for symbol in tickers if symbol not in quotes]
        if not missing:
            break
        try:
            fetched = provider(missing)
        except Exception as exc:
            print(f"行情源 {name} 异常: {exc}")
            continue
        if fetched:
            quotes.update(fetched)
    return quotes


def fetch_us_quotes(
    tickers: List[str],
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Dict[str, float]:
    """获取美股报价，优先读缓存，仅对缺失/过期 symbol 调用外部 API。"""
    symbols = normalize_us_tickers(tickers)
    if not symbols:
        return {}

    if force_refresh:
        invalidate_quote_cache(symbols)

    quotes: Dict[str, float] = {}
    if use_cache:
        quotes.update(read_cached_quotes(symbols))

    missing = [symbol for symbol in symbols if symbol not in quotes]
    if missing:
        fetched = _fetch_from_providers(missing)
        if fetched and use_cache:
            write_cached_quotes(fetched)
        quotes.update(fetched)

    still_missing = [symbol for symbol in symbols if symbol not in quotes]
    if still_missing and use_cache:
        quotes.update(read_cached_quotes(still_missing, allow_stale=True))

    return {symbol: quotes[symbol] for symbol in symbols if symbol in quotes}
