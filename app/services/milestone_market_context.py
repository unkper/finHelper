"""时间线评分：大盘基准、FMP/EODHD 资讯与证据充分度判断。"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from app.services.quote_providers import eodhd, fmp
from app.services.quotes import fetch_us_quotes
from app.services.stock_history import fetch_daily_series

BENCHMARK_TICKERS = ("SPY", "QQQ")
_NEWS_CONTENT_MAX = 300
_NEWS_LIMIT = 6
_EVENT_NEWS_DAYS = 7
_MACRO_CALENDAR_PADDING_DAYS = 2

_MACRO_KEYWORDS = re.compile(
    r"ism|cpi|ppi|pmi|非农|nonfarm|fomc|fed|gdp|通胀|通缩|利率|降息|加息|"
    r"宏观|大盘|指数|标普|纳指|道指|treasury|yield|就业|失业率|零售|"
    r"制造业|服务业|经济数据|央行",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z]{2,8}|[\u4e00-\u9fff]{2,6}")
_HAS_DIGIT_RE = re.compile(r"\d")

_SCORING_BASIS_PREFIX = {
    "theme": "[主题]",
    "market": "[大盘/宏观]",
    "mixed": "[综合]",
}


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _price_on_or_before(series: List[Dict[str, Any]], target_date: str) -> Optional[float]:
    price = None
    for bar in series:
        bar_date = str(bar.get("date") or "")
        if bar_date and bar_date <= target_date:
            close = bar.get("close")
            if close is not None:
                price = float(close)
    return price


def build_market_dynamics(event_date: str) -> List[Dict[str, Any]]:
    """标普/纳指自事件日至最新的涨跌幅。"""
    quotes = fetch_us_quotes(list(BENCHMARK_TICKERS))
    result: List[Dict[str, Any]] = []
    for ticker in BENCHMARK_TICKERS:
        series = fetch_daily_series(ticker, use_cache=True)
        event_price = _price_on_or_before(series, event_date) if series else None
        latest_price = quotes.get(ticker)
        if latest_price is None and series:
            latest_price = series[-1].get("close")
        entry: Dict[str, Any] = {
            "ticker": ticker,
            "label": "标普500" if ticker == "SPY" else "纳斯达克100",
            "exchange": "US",
            "benchmark": True,
        }
        entry["price_at_event"] = round(event_price, 2) if event_price is not None else None
        entry["latest_price"] = round(float(latest_price), 2) if latest_price is not None else None
        if event_price and latest_price and event_price != 0:
            entry["change_pct"] = round(
                (float(latest_price) - event_price) / event_price * 100, 2
            )
        result.append(entry)
    return result


def is_macro_like_milestone(description: str, theme_title: str = "") -> bool:
    text = f"{description} {theme_title}"
    return bool(_MACRO_KEYWORDS.search(text))


def is_theme_evidence_sparse(articles: List[Dict[str, str]]) -> bool:
    if not articles:
        return True
    substantive = 0
    for article in articles:
        summary = (article.get("summary") or "").strip()
        if len(summary) >= 80 or _HAS_DIGIT_RE.search(summary):
            substantive += 1
    return substantive == 0


def resolve_evidence_hint(
    *,
    milestone_description: str,
    theme_title: str,
    articles: List[Dict[str, str]],
) -> str:
    if is_macro_like_milestone(milestone_description, theme_title):
        return "macro_or_sparse"
    if is_theme_evidence_sparse(articles):
        return "macro_or_sparse"
    return "theme_rich"


def extract_search_tokens(description: str, limit: int = 3) -> List[str]:
    """从节点描述提取宏观检索词。"""
    seen = set()
    tokens: List[str] = []
    for match in _TOKEN_RE.finditer(description or ""):
        raw = match.group(0)
        token = raw.upper() if raw.isascii() else raw
        key = token.lower()
        if key in seen or len(token) < 2:
            continue
        if token.lower() in {"the", "and", "for", "数据", "发布", "公布", "走势"}:
            continue
        seen.add(key)
        tokens.append(token)
        if len(tokens) >= limit:
            break
    return tokens


def _dedupe_news(items: List[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
    seen_titles = set()
    out: List[Dict[str, str]] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _filter_events_by_keywords(
    events: List[Dict[str, str]],
    keywords: List[str],
) -> List[Dict[str, str]]:
    if not keywords:
        return events
    lowered = [k.lower() for k in keywords]
    matched = []
    for event in events:
        hay = f"{event.get('title', '')} {event.get('summary', '')}".lower()
        if any(k in hay for k in lowered):
            matched.append(event)
    return matched or events[:8]


def _fetch_benchmark_news(from_news: str, to_news: str) -> List[Dict[str, str]]:
    news_pool: List[Dict[str, str]] = []
    for ticker in BENCHMARK_TICKERS:
        if fmp.has_api_key() and not fmp.is_news_feature_on_cooldown():
            news_pool.extend(
                fmp.fetch_stock_news(
                    ticker,
                    from_date=from_news,
                    to_date=to_news,
                    limit=_NEWS_LIMIT,
                )
            )
        elif eodhd.has_api_key() and not eodhd.is_news_feature_on_cooldown():
            news_pool.extend(
                eodhd.fetch_financial_news(
                    symbol=ticker,
                    from_date=from_news,
                    to_date=to_news,
                    limit=_NEWS_LIMIT,
                )
            )
    return news_pool


def _fetch_tagged_news(token: str, from_news: str, to_news: str) -> List[Dict[str, str]]:
    if eodhd.has_api_key() and not eodhd.is_news_feature_on_cooldown():
        return eodhd.fetch_financial_news(
            tag=token.lower(),
            from_date=from_news,
            to_date=to_news,
            limit=4,
        )
    if fmp.has_api_key() and not fmp.is_news_feature_on_cooldown() and token.isascii():
        return fmp.fetch_stock_news(
            token.upper(),
            from_date=from_news,
            to_date=to_news,
            limit=4,
        )
    return []


def _fetch_economic_events(cal_from: str, cal_to: str) -> List[Dict[str, str]]:
    if fmp.has_api_key() and not fmp.is_economic_calendar_on_cooldown():
        events = fmp.fetch_economic_calendar(
            from_date=cal_from,
            to_date=cal_to,
            country="US",
            limit=40,
        )
        if events:
            return events
    if eodhd.has_api_key():
        return eodhd.fetch_economic_events(
            from_date=cal_from,
            to_date=cal_to,
            country="US",
            limit=40,
        )
    return []


def fetch_external_news_and_events(
    *,
    event_date: str,
    milestone_description: str,
) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """拉取 FMP（优先）或 EODHD 新闻与宏观日历。"""
    if not fmp.has_api_key() and not eodhd.has_api_key():
        return [], []

    try:
        ev = date.fromisoformat(event_date)
    except ValueError:
        return [], []

    to_dt = ev + timedelta(days=_EVENT_NEWS_DAYS)
    from_news = event_date
    to_news = to_dt.isoformat()

    cal_from = (ev - timedelta(days=_MACRO_CALENDAR_PADDING_DAYS)).isoformat()
    cal_to = (ev + timedelta(days=_MACRO_CALENDAR_PADDING_DAYS)).isoformat()

    news_pool = _fetch_benchmark_news(from_news, to_news)

    tokens = extract_search_tokens(milestone_description)
    for token in tokens:
        if token.isascii() and len(token) <= 6:
            news_pool.extend(_fetch_tagged_news(token, from_news, to_news))

    keywords = tokens + [t.lower() for t in tokens if t.isascii()]
    events = _fetch_economic_events(cal_from, cal_to)
    events = _filter_events_by_keywords(events, keywords)

    return _dedupe_news(news_pool, _NEWS_LIMIT * 2), events[:10]


def is_market_data_available() -> bool:
    return fmp.has_api_key() or eodhd.has_api_key()


def build_macro_context_block(
    *,
    event_date: str,
    milestone_description: str,
    theme_title: str,
    articles: List[Dict[str, str]],
) -> Dict[str, Any]:
    """组装大盘、外部资讯与 evidence_hint。"""
    external_news, economic_events = fetch_external_news_and_events(
        event_date=event_date,
        milestone_description=milestone_description,
    )
    return {
        "evidence_hint": resolve_evidence_hint(
            milestone_description=milestone_description,
            theme_title=theme_title,
            articles=articles,
        ),
        "market_dynamics": build_market_dynamics(event_date),
        "external_news": external_news,
        "economic_events": economic_events,
        "market_data_available": is_market_data_available(),
        "fmp_available": fmp.has_api_key(),
        "eodhd_available": eodhd.has_api_key(),
    }


def format_rationale_with_basis(rationale: str, scoring_basis: str | None) -> str:
    """为 AI 理由加上评分依据前缀。"""
    text = (rationale or "").strip()
    basis = (scoring_basis or "").strip().lower()
    prefix = _SCORING_BASIS_PREFIX.get(basis)
    if not prefix or text.startswith("["):
        return text
    return f"{prefix} {text}"
