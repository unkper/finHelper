from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from app.services.auth import (
    is_auth_enabled,
    is_authenticated,
    login_user,
    logout_user,
    safe_next_url,
    verify_password,
)
from app.services.captcha import build_captcha_svg, issue_captcha, verify_captcha
from app.services.login_guard import (
    FAIL_THRESHOLD,
    captcha_required,
    get_failure_count,
    record_login_failure,
    record_login_success,
)
from app.services.rate_limit import consume_rate_limit, get_client_ip

bp = Blueprint("auth", __name__)


def _login_context(next_url: str = ""):
    ip = get_client_ip()
    need_captcha = captcha_required(ip)
    failure_count = get_failure_count(ip)
    return {
        "auth_disabled": False,
        "next_url": next_url,
        "captcha_required": need_captcha,
        "failure_count": failure_count,
        "fail_threshold": FAIL_THRESHOLD,
    }


@bp.route("/login/captcha")
def captcha_image():
    if not is_auth_enabled() or is_authenticated():
        return Response("", status=404)

    code = issue_captcha()
    svg = build_captcha_svg(code)
    return Response(svg, mimetype="image/svg+xml")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if is_authenticated():
        return redirect(safe_next_url(request.args.get("next")))

    if not is_auth_enabled():
        return render_template("login.html", auth_disabled=True)

    next_url = request.form.get("next") or request.args.get("next") or ""

    if request.method == "POST":
        ip = get_client_ip()
        allowed, retry_after = consume_rate_limit(f"login:burst:{ip}", max_calls=30, window_seconds=300)
        if not allowed:
            flash(f"登录尝试过于频繁，请 {retry_after} 秒后再试", "error")
            return render_template("login.html", **_login_context(next_url))

        need_captcha = captcha_required(ip)
        if need_captcha:
            captcha_input = request.form.get("captcha", "")
            if not verify_captcha(captcha_input):
                flash("验证码错误或已过期，请重新输入", "error")
                return render_template("login.html", **_login_context(next_url))

        password = request.form.get("password", "")
        if verify_password(password):
            record_login_success(ip)
            login_user()
            flash("登录成功", "success")
            return redirect(safe_next_url(next_url))

        failure_count = record_login_failure(ip)
        if failure_count >= FAIL_THRESHOLD:
            flash(
                f"密码错误，已连续失败 {failure_count} 次，请输入验证码后继续登录",
                "error",
            )
        else:
            remaining = FAIL_THRESHOLD - failure_count
            flash(f"密码错误，还可尝试 {remaining} 次", "error")
        return render_template("login.html", **_login_context(next_url))

    return render_template("login.html", **_login_context(next_url))


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("已退出登录", "success")
    return redirect(url_for("auth.login"))
