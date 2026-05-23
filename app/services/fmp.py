"""兼容旧引用，请改用 app.services.quotes。"""
from app.services.quotes import fetch_us_quotes

__all__ = ["fetch_us_quotes"]
