"""功能开关（读取 Flask config / .env）。"""
from flask import current_app


def is_earnings_enabled() -> bool:
    return bool(current_app.config.get("EARNINGS_ENABLED", False))
