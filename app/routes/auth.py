from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.services.auth import (
    is_auth_enabled,
    is_authenticated,
    login_user,
    logout_user,
    safe_next_url,
    verify_password,
)
from app.services.rate_limit import consume_rate_limit, get_client_ip

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if is_authenticated():
        return redirect(safe_next_url(request.args.get("next")))

    if not is_auth_enabled():
        return render_template("login.html", auth_disabled=True)

    if request.method == "POST":
        ip = get_client_ip()
        allowed, retry_after = consume_rate_limit(f"login:{ip}", max_calls=10, window_seconds=300)
        if not allowed:
            flash(f"登录尝试过于频繁，请 {retry_after} 秒后再试", "error")
            return render_template("login.html", auth_disabled=False)

        password = request.form.get("password", "")
        if verify_password(password):
            login_user()
            flash("登录成功", "success")
            return redirect(safe_next_url(request.form.get("next") or request.args.get("next")))

        flash("密码错误", "error")

    return render_template(
        "login.html",
        auth_disabled=False,
        next_url=request.args.get("next") or request.form.get("next") or "",
    )


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("已退出登录", "success")
    return redirect(url_for("auth.login"))
