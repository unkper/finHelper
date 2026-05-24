from datetime import date

from flask import flash, redirect, render_template, request, url_for, current_app

from app.database import SUPPORTED_CURRENCIES
from app.database import get_db
from app.scheduler_setup import configure_monitor_jobs
from app.services.settings import (
    get_history_cache_hours,
    get_monitor_interval_minutes,
    get_quote_cache_minutes,
    set_history_cache_hours,
    set_monitor_interval_minutes,
    set_quote_cache_minutes,
)
from app.services.snapshot import (
    build_pie_data,
    fetch_accounts,
    fetch_growth_rows,
    fetch_latest_totals,
    fetch_snapshot_cards,
    fetch_trend_rows,
    parse_snapshot_form,
    persist_snapshot_entries,
)

from . import bp

@bp.route("/")
def index():
    display_currency = request.args.get("display_currency", "CNY").upper()
    if display_currency not in SUPPORTED_CURRENCIES:
        display_currency = "CNY"

    return render_template(
        "index.html",
        today=date.today().isoformat(),
        accounts=fetch_accounts(),
        supported_currencies=SUPPORTED_CURRENCIES,
        display_currency=display_currency,
        latest_totals=fetch_latest_totals(display_currency),
        trend_rows=fetch_trend_rows(display_currency),
        growth_rows=fetch_growth_rows(display_currency),
        pie_data=build_pie_data(display_currency),
        recent_snapshots=fetch_snapshot_cards(display_currency=display_currency),
    )

@bp.route("/snapshots", methods=["POST"])
def create_snapshot():
    snapshot_date, note, display_currency, entries = parse_snapshot_form(request.form)
    if not entries:
        flash("Please add at least one account before saving.", "error")
        return redirect(url_for(".index", display_currency=display_currency))

    db = get_db()
    snapshot_id = db.execute(
        "INSERT INTO snapshots (snapshot_date, note) VALUES (?, ?)",
        (snapshot_date, note),
    ).lastrowid
    persist_snapshot_entries(snapshot_id, snapshot_date, note, entries)
    db.commit()
    flash("Snapshot saved.", "success")
    return redirect(url_for(".index", display_currency=display_currency))


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            monitor_minutes = int(request.form.get("monitor_interval_minutes", "1"))
            quote_cache_minutes = int(request.form.get("quote_cache_minutes", "5"))
            history_cache_hours = int(request.form.get("history_cache_hours", "12"))
        except ValueError:
            flash("配置项必须是整数", "error")
            return redirect(url_for(".settings"))

        interval = set_monitor_interval_minutes(monitor_minutes)
        quote_ttl = set_quote_cache_minutes(quote_cache_minutes)
        history_ttl = set_history_cache_hours(history_cache_hours)
        configure_monitor_jobs(current_app._get_current_object())
        flash(
            f"已保存：监控 {interval} 分钟/次，现价缓存 {quote_ttl} 分钟，历史缓存 {history_ttl} 小时",
            "success",
        )
        return redirect(url_for(".settings"))

    return render_template(
        "settings.html",
        monitor_interval_minutes=get_monitor_interval_minutes(),
        quote_cache_minutes=get_quote_cache_minutes(),
        history_cache_hours=get_history_cache_hours(),
    )