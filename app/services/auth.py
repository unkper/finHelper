"""基于 .env 中 WEB_PASSWORD 的简单会话鉴权。"""
import secrets
from typing import Optional

from flask import current_app, redirect, request, session, url_for


SESSION_AUTH_KEY = "authenticated"


def is_auth_enabled() -> bool:
    return bool(current_app.config.get("WEB_PASSWORD"))


def is_authenticated() -> bool:
    if not is_auth_enabled():
        return False
    return session.get(SESSION_AUTH_KEY) is True


def login_user() -> None:
    session[SESSION_AUTH_KEY] = True
    session.permanent = True


def logout_user() -> None:
    session.pop(SESSION_AUTH_KEY, None)


def verify_password(password: str) -> bool:
    expected = current_app.config.get("WEB_PASSWORD", "")
    if not expected:
        return False
    return secrets.compare_digest(str(password or ""), expected)


def safe_next_url(next_url: Optional[str]) -> str:
    if not next_url:
        return url_for("main.index")
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return url_for("main.index")


def require_login():
    """未登录时重定向到登录页；未配置密码时同样阻断。"""
    if is_authenticated():
        return None

    if request.path.startswith("/static/"):
        return None

    endpoint = request.endpoint or ""
    if endpoint in {"auth.login", "auth.captcha_image", "bot.feishu_callback"}:
        return None

    if endpoint == "static":
        return None

    return redirect(url_for("auth.login", next=request.full_path))
