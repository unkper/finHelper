from app.database import get_db

MONITOR_INTERVAL_KEY = "monitor_interval_minutes"
QUOTE_CACHE_MINUTES_KEY = "quote_cache_minutes"
HISTORY_CACHE_HOURS_KEY = "history_cache_hours"
DEFAULT_MONITOR_INTERVAL = 1
DEFAULT_QUOTE_CACHE_MINUTES = 5
DEFAULT_HISTORY_CACHE_HOURS = 12
MIN_MONITOR_INTERVAL = 1
MAX_MONITOR_INTERVAL = 1440
MIN_QUOTE_CACHE_MINUTES = 1
MAX_QUOTE_CACHE_MINUTES = 120
MIN_HISTORY_CACHE_HOURS = 1
MAX_HISTORY_CACHE_HOURS = 168


def ensure_default_settings() -> None:
    db = get_db()
    defaults = (
        (MONITOR_INTERVAL_KEY, str(DEFAULT_MONITOR_INTERVAL)),
        (QUOTE_CACHE_MINUTES_KEY, str(DEFAULT_QUOTE_CACHE_MINUTES)),
        (HISTORY_CACHE_HOURS_KEY, str(DEFAULT_HISTORY_CACHE_HOURS)),
    )
    for key, value in defaults:
        db.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    db.commit()


def get_setting(key: str, default: str = "") -> str:
    db = get_db()
    row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    db.commit()


def get_monitor_interval_minutes() -> int:
    raw = get_setting(MONITOR_INTERVAL_KEY, str(DEFAULT_MONITOR_INTERVAL))
    try:
        minutes = int(raw)
    except ValueError:
        minutes = DEFAULT_MONITOR_INTERVAL
    return max(MIN_MONITOR_INTERVAL, min(MAX_MONITOR_INTERVAL, minutes))


def set_monitor_interval_minutes(minutes: int) -> int:
    clamped = max(MIN_MONITOR_INTERVAL, min(MAX_MONITOR_INTERVAL, int(minutes)))
    set_setting(MONITOR_INTERVAL_KEY, str(clamped))
    return clamped


def get_quote_cache_minutes() -> int:
    raw = get_setting(QUOTE_CACHE_MINUTES_KEY, str(DEFAULT_QUOTE_CACHE_MINUTES))
    try:
        minutes = int(raw)
    except ValueError:
        minutes = DEFAULT_QUOTE_CACHE_MINUTES
    return max(MIN_QUOTE_CACHE_MINUTES, min(MAX_QUOTE_CACHE_MINUTES, minutes))


def set_quote_cache_minutes(minutes: int) -> int:
    clamped = max(MIN_QUOTE_CACHE_MINUTES, min(MAX_QUOTE_CACHE_MINUTES, int(minutes)))
    set_setting(QUOTE_CACHE_MINUTES_KEY, str(clamped))
    return clamped


def get_history_cache_hours() -> int:
    raw = get_setting(HISTORY_CACHE_HOURS_KEY, str(DEFAULT_HISTORY_CACHE_HOURS))
    try:
        hours = int(raw)
    except ValueError:
        hours = DEFAULT_HISTORY_CACHE_HOURS
    return max(MIN_HISTORY_CACHE_HOURS, min(MAX_HISTORY_CACHE_HOURS, hours))


def set_history_cache_hours(hours: int) -> int:
    clamped = max(MIN_HISTORY_CACHE_HOURS, min(MAX_HISTORY_CACHE_HOURS, int(hours)))
    set_setting(HISTORY_CACHE_HOURS_KEY, str(clamped))
    return clamped
