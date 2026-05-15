from datetime import date

from flask import flash, redirect, render_template, request, url_for

from app.database import SUPPORTED_CURRENCIES
from app.database import get_db
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