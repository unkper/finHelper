"""监控标的财经新闻：EODHD 拉取与短缓存。"""
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app, has_app_context

from app.database import get_db
from app.services.investment import fetch_tracked_assets_overview
from app.services.news_translate import is_translation_available, translate_news_items
from app.services.quote_providers import eodhd

logger = logging.getLogger(__name__)

CACHE_TTL_MINUTES = 30
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
_inflight_lock = threading.Lock()
_inflight_keys: set[str] = set()


def is_news_available() -> bool:
    return eodhd.has_api_key() and not eodhd.is_news_feature_on_cooldown()


def list_news_tickers() -> List[Dict[str, Any]]:
    assets = fetch_tracked_assets_overview()
    us_assets = [
        item for item in assets
        if (item.get("exchange") or "").upper() == "US"
    ]
    us_assets.sort(key=lambda row: row["ticker"])
    return [
        {"ticker": item["ticker"], "themes": item.get("themes") or []}
        for item in us_assets
    ]


def _cache_key(
    ticker: str,
    offset: int,
    limit: int,
    from_date: Optional[str],
    to_date: Optional[str],
) -> str:
    return f"{ticker.upper()}:{offset}:{limit}:{from_date or ''}:{to_date or ''}"


def _parse_cache_payload(payload: Any) -> Tuple[List[Dict[str, Any]], bool]:
    """解析缓存；旧 list 格式视为已翻译。"""
    if isinstance(payload, list):
        return payload, True
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items, bool(payload.get("translated", False))
    return [], False


def _read_cache_entry(cache_key: str) -> Optional[Tuple[List[Dict[str, Any]], bool, datetime]]:
    db = get_db()
    row = db.execute(
        "SELECT payload_json, fetched_at FROM stock_news_cache WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if not row:
        return None
    try:
        fetched_at = datetime.fromisoformat(row["fetched_at"])
    except ValueError:
        return None
    if datetime.now() - fetched_at > timedelta(minutes=CACHE_TTL_MINUTES):
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    items, translated = _parse_cache_payload(payload)
    return items, translated, fetched_at


def _write_cache(cache_key: str, items: List[Dict[str, Any]], *, translated: bool) -> None:
    db = get_db()
    payload = {"items": items, "translated": translated}
    db.execute(
        """
        INSERT INTO stock_news_cache (cache_key, payload_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at
        """,
        (
            cache_key,
            json.dumps(payload, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    db.commit()


def _normalize_limit(limit: int | str | None) -> int:
    try:
        value = int(limit) if limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, value))


def _normalize_offset(offset: int | str | None) -> int:
    try:
        value = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        value = 0
    return max(0, value)


def _should_translate() -> bool:
    return is_translation_available()


def _translate_and_persist(cache_key: str, items: List[Dict[str, Any]]) -> None:
    try:
        translated_items = translate_news_items(items)
        _write_cache(cache_key, translated_items, translated=True)
    except Exception as exc:
        logger.warning("新闻后台翻译失败 (%s): %s", cache_key, exc)
    finally:
        with _inflight_lock:
            _inflight_keys.discard(cache_key)


def _run_translate_job(app, cache_key: str, items: List[Dict[str, Any]]) -> None:
    with app.app_context():
        _translate_and_persist(cache_key, items)


def _schedule_translation(app, cache_key: str, items: List[Dict[str, Any]]) -> bool:
    if not _should_translate():
        return False
    with _inflight_lock:
        if cache_key in _inflight_keys:
            return True
        _inflight_keys.add(cache_key)
    thread = threading.Thread(
        target=_run_translate_job,
        args=(app, cache_key, [dict(item) for item in items]),
        daemon=True,
    )
    thread.start()
    return True


def fetch_ticker_news(
    ticker: str,
    *,
    offset: int | str | None = 0,
    limit: int | str | None = DEFAULT_LIMIT,
    from_date: str | None = None,
    to_date: str | None = None,
    force_refresh: bool = False,
    app=None,
) -> Tuple[List[Dict[str, Any]], bool, Dict[str, Any]]:
    """
    返回 (items, has_more, meta)。
    meta 含 configured / translated / translating / unavailable_reason。
    """
    ticker = (ticker or "").strip().upper()
    offset = _normalize_offset(offset)
    limit = _normalize_limit(limit)
    meta: Dict[str, Any] = {
        "configured": is_news_available(),
        "translated": True,
        "translating": False,
    }

    if not ticker:
        return [], False, {**meta, "error": "请选择标的"}
    if not eodhd.has_api_key():
        return [], False, {**meta, "configured": False, "error": "未配置 EODHD_API_KEY"}
    if eodhd.is_news_feature_on_cooldown():
        return [], False, {
            **meta,
            "configured": False,
            "error": "当前 EODHD 套餐可能不含新闻接口，或接口暂不可用",
        }

    cache_key = _cache_key(ticker, offset, limit, from_date, to_date)
    flask_app = app
    if flask_app is None and has_app_context():
        flask_app = current_app._get_current_object()

    if not force_refresh:
        cached = _read_cache_entry(cache_key)
        if cached is not None:
            items, translated, _fetched_at = cached
            has_more = len(items) >= limit
            meta["translated"] = translated
            if not translated and _should_translate() and flask_app is not None:
                meta["translating"] = _schedule_translation(flask_app, cache_key, items)
            elif not translated and not _should_translate():
                meta["translated"] = True
            return items, has_more, meta

    items = eodhd.fetch_financial_news(
        symbol=ticker,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )

    if _should_translate():
        _write_cache(cache_key, items, translated=False)
        meta["translated"] = False
        if flask_app is not None:
            meta["translating"] = _schedule_translation(flask_app, cache_key, items)
    else:
        _write_cache(cache_key, items, translated=True)
        meta["translated"] = True

    has_more = len(items) >= limit
    return items, has_more, meta
