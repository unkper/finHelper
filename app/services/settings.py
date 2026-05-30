from app.database import get_db

MONITOR_INTERVAL_KEY = "monitor_interval_minutes"
QUOTE_CACHE_MINUTES_KEY = "quote_cache_minutes"
HISTORY_CACHE_HOURS_KEY = "history_cache_hours"
MACD_ALERT_GOLDEN_ABOVE_KEY = "macd_alert_golden_cross_above_zero"
MACD_ALERT_DEATH_BELOW_KEY = "macd_alert_death_cross_below_zero"
EARNINGS_HORIZON_DAYS_KEY = "earnings_horizon_days"
EARNINGS_REMIND_DAYS_BEFORE_KEY = "earnings_remind_days_before"
EARNINGS_REMIND_ENABLED_KEY = "earnings_remind_enabled"
AI_ARTICLE_MODEL_KEY = "ai_article_model"
ALLOWED_AI_ARTICLE_MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")
DEFAULT_AI_ARTICLE_MODEL = "deepseek-v4-flash"
DEFAULT_MONITOR_INTERVAL = 1
DEFAULT_QUOTE_CACHE_MINUTES = 5
DEFAULT_HISTORY_CACHE_HOURS = 12
DEFAULT_EARNINGS_HORIZON_DAYS = 30
DEFAULT_EARNINGS_REMIND_DAYS_BEFORE = 3
MIN_EARNINGS_HORIZON_DAYS = 7
MAX_EARNINGS_HORIZON_DAYS = 60
MIN_EARNINGS_REMIND_DAYS = 1
MAX_EARNINGS_REMIND_DAYS = 30
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
        (MACD_ALERT_GOLDEN_ABOVE_KEY, "0"),
        (MACD_ALERT_DEATH_BELOW_KEY, "0"),
        (EARNINGS_HORIZON_DAYS_KEY, str(DEFAULT_EARNINGS_HORIZON_DAYS)),
        (EARNINGS_REMIND_DAYS_BEFORE_KEY, str(DEFAULT_EARNINGS_REMIND_DAYS_BEFORE)),
        (EARNINGS_REMIND_ENABLED_KEY, "1"),
        (AI_ARTICLE_MODEL_KEY, DEFAULT_AI_ARTICLE_MODEL),
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


def _is_truthy_setting(key: str) -> bool:
    return get_setting(key, "0") in ("1", "true", "True", "yes", "on")


def is_macd_alert_golden_cross_above_zero_enabled() -> bool:
    return _is_truthy_setting(MACD_ALERT_GOLDEN_ABOVE_KEY)


def is_macd_alert_death_cross_below_zero_enabled() -> bool:
    return _is_truthy_setting(MACD_ALERT_DEATH_BELOW_KEY)


def set_macd_alert_golden_cross_above_zero(enabled: bool) -> None:
    set_setting(MACD_ALERT_GOLDEN_ABOVE_KEY, "1" if enabled else "0")


def set_macd_alert_death_cross_below_zero(enabled: bool) -> None:
    set_setting(MACD_ALERT_DEATH_BELOW_KEY, "1" if enabled else "0")


def get_macd_alert_settings() -> dict:
    return {
        "golden_cross_above_zero": is_macd_alert_golden_cross_above_zero_enabled(),
        "death_cross_below_zero": is_macd_alert_death_cross_below_zero_enabled(),
    }


def get_earnings_horizon_days() -> int:
    raw = get_setting(EARNINGS_HORIZON_DAYS_KEY, str(DEFAULT_EARNINGS_HORIZON_DAYS))
    try:
        days = int(raw)
    except ValueError:
        days = DEFAULT_EARNINGS_HORIZON_DAYS
    return max(MIN_EARNINGS_HORIZON_DAYS, min(MAX_EARNINGS_HORIZON_DAYS, days))


def set_earnings_horizon_days(days: int) -> int:
    clamped = max(MIN_EARNINGS_HORIZON_DAYS, min(MAX_EARNINGS_HORIZON_DAYS, int(days)))
    set_setting(EARNINGS_HORIZON_DAYS_KEY, str(clamped))
    return clamped


def get_earnings_remind_days_before() -> int:
    raw = get_setting(EARNINGS_REMIND_DAYS_BEFORE_KEY, str(DEFAULT_EARNINGS_REMIND_DAYS_BEFORE))
    try:
        days = int(raw)
    except ValueError:
        days = DEFAULT_EARNINGS_REMIND_DAYS_BEFORE
    return max(MIN_EARNINGS_REMIND_DAYS, min(MAX_EARNINGS_REMIND_DAYS, days))


def set_earnings_remind_days_before(days: int) -> int:
    clamped = max(MIN_EARNINGS_REMIND_DAYS, min(MAX_EARNINGS_REMIND_DAYS, int(days)))
    set_setting(EARNINGS_REMIND_DAYS_BEFORE_KEY, str(clamped))
    return clamped


def is_earnings_remind_enabled() -> bool:
    return _is_truthy_setting(EARNINGS_REMIND_ENABLED_KEY)


def set_earnings_remind_enabled(enabled: bool) -> None:
    set_setting(EARNINGS_REMIND_ENABLED_KEY, "1" if enabled else "0")


def get_earnings_settings() -> dict:
    return {
        "horizon_days": get_earnings_horizon_days(),
        "remind_days_before": get_earnings_remind_days_before(),
        "remind_enabled": is_earnings_remind_enabled(),
    }


def get_ai_article_model() -> str:
    raw = get_setting(AI_ARTICLE_MODEL_KEY, DEFAULT_AI_ARTICLE_MODEL)
    if raw not in ALLOWED_AI_ARTICLE_MODELS:
        return DEFAULT_AI_ARTICLE_MODEL
    return raw


def set_ai_article_model(model: str) -> str:
    value = model if model in ALLOWED_AI_ARTICLE_MODELS else DEFAULT_AI_ARTICLE_MODEL
    set_setting(AI_ARTICLE_MODEL_KEY, value)
    return value


def get_ai_article_settings() -> dict:
    return {
        "model": get_ai_article_model(),
        "allowed_models": list(ALLOWED_AI_ARTICLE_MODELS),
    }
