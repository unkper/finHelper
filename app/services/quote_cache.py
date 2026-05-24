"""股价 API 结果的数据库缓存。"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.database import get_db
from app.services.settings import get_history_cache_hours, get_quote_cache_minutes


def _parse_timestamp(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_cache_fresh(updated_at: str | None, ttl: timedelta) -> bool:
    updated = _parse_timestamp(updated_at)
    if not updated:
        return False
    return datetime.now() - updated < ttl


def quote_cache_ttl() -> timedelta:
    return timedelta(minutes=get_quote_cache_minutes())


def history_cache_ttl() -> timedelta:
    return timedelta(hours=get_history_cache_hours())


def read_cached_quotes(
    tickers: List[str],
    *,
    allow_stale: bool = False,
) -> Dict[str, float]:
    if not tickers:
        return {}

    db = get_db()
    placeholders = ",".join("?" for _ in tickers)
    rows = db.execute(
        f"""
        SELECT ticker, price, updated_at
        FROM stock_quote_cache
        WHERE ticker IN ({placeholders})
        """,
        tuple(tickers),
    ).fetchall()

    ttl = quote_cache_ttl()
    quotes: Dict[str, float] = {}
    for row in rows:
        fresh = is_cache_fresh(row["updated_at"], ttl)
        if fresh or allow_stale:
            quotes[row["ticker"]] = float(row["price"])
    return quotes


def write_cached_quotes(quotes: Dict[str, float]) -> None:
    if not quotes:
        return

    db = get_db()
    now_iso = datetime.now().isoformat(timespec="seconds")
    for ticker, price in quotes.items():
        symbol = ticker.strip().upper()
        if not symbol or price is None:
            continue
        db.execute(
            """
            INSERT INTO stock_quote_cache (ticker, price, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                price = excluded.price,
                updated_at = excluded.updated_at
            """,
            (symbol, float(price), now_iso),
        )
    db.commit()


def invalidate_quote_cache(tickers: List[str] | None = None) -> None:
    db = get_db()
    if not tickers:
        db.execute("DELETE FROM stock_quote_cache")
    else:
        placeholders = ",".join("?" for _ in tickers)
        db.execute(
            f"DELETE FROM stock_quote_cache WHERE ticker IN ({placeholders})",
            tuple(t.strip().upper() for t in tickers if t),
        )
    db.commit()


def read_cached_daily_series(ticker: str, *, allow_stale: bool = False) -> List[Dict]:
    db = get_db()
    meta = db.execute(
        "SELECT updated_at FROM stock_daily_cache_meta WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    if not meta:
        return []

    fresh = is_cache_fresh(meta["updated_at"], history_cache_ttl())
    if not fresh and not allow_stale:
        return []

    rows = db.execute(
        """
        SELECT bar_date, close FROM stock_daily_cache
        WHERE ticker = ?
        ORDER BY bar_date ASC
        """,
        (ticker,),
    ).fetchall()
    return [{"date": row["bar_date"], "close": row["close"]} for row in rows]


def write_cached_daily_series(ticker: str, series: List[Dict]) -> None:
    if not series:
        return

    db = get_db()
    db.execute("DELETE FROM stock_daily_cache WHERE ticker = ?", (ticker,))
    for point in series:
        db.execute(
            """
            INSERT INTO stock_daily_cache (ticker, bar_date, close)
            VALUES (?, ?, ?)
            """,
            (ticker, point["date"], point["close"]),
        )
    db.execute(
        """
        INSERT INTO stock_daily_cache_meta (ticker, updated_at)
        VALUES (?, ?)
        ON CONFLICT(ticker) DO UPDATE SET updated_at = excluded.updated_at
        """,
        (ticker, datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()


def invalidate_daily_cache(tickers: List[str] | None = None) -> None:
    db = get_db()
    if not tickers:
        db.execute("DELETE FROM stock_daily_cache")
        db.execute("DELETE FROM stock_daily_cache_meta")
    else:
        for ticker in tickers:
            symbol = ticker.strip().upper()
            if not symbol:
                continue
            db.execute("DELETE FROM stock_daily_cache WHERE ticker = ?", (symbol,))
            db.execute("DELETE FROM stock_daily_cache_meta WHERE ticker = ?", (symbol,))
    db.commit()
