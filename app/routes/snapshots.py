from flask import flash, redirect, render_template, request, url_for

from app.database import SUPPORTED_CURRENCIES, get_db
from app.services.snapshot import (
    fetch_accounts,
    parse_snapshot_form,
    persist_snapshot_entries,
    summarize_snapshot,
)

from . import bp

@bp.route("/snapshots/<int:snapshot_id>")
def snapshot_detail(snapshot_id: int):
    display_currency = request.args.get("display_currency", "CNY").upper()
    if display_currency not in SUPPORTED_CURRENCIES:
        display_currency = "CNY"

    snapshot = summarize_snapshot(snapshot_id, display_currency)
    if snapshot is None:
        flash("Snapshot not found.", "error")
        return redirect(url_for(".index", display_currency=display_currency))

    return render_template(
        "snapshot_detail.html",
        snapshot=snapshot,
        accounts=fetch_accounts(),
        display_currency=display_currency,
        supported_currencies=SUPPORTED_CURRENCIES,
    )

@bp.route("/snapshots/<int:snapshot_id>/update", methods=["POST"])
def update_snapshot(snapshot_id: int):
    snapshot_date, note, display_currency, entries = parse_snapshot_form(request.form)
    if not entries:
        flash("Please keep at least one account in the snapshot.", "error")
        return redirect(url_for(".snapshot_detail", snapshot_id=snapshot_id, display_currency=display_currency))

    if summarize_snapshot(snapshot_id, display_currency) is None:
        flash("Snapshot not found.", "error")
        return redirect(url_for(".index", display_currency=display_currency))

    persist_snapshot_entries(snapshot_id, snapshot_date, note, entries)
    get_db().commit()
    flash("Snapshot updated.", "success")
    return redirect(url_for(".snapshot_detail", snapshot_id=snapshot_id, display_currency=display_currency))

@bp.route("/snapshots/<int:snapshot_id>/delete", methods=["POST"])
def delete_snapshot(snapshot_id: int):
    display_currency = request.form.get("display_currency", "CNY").upper()
    if display_currency not in SUPPORTED_CURRENCIES:
        display_currency = "CNY"

    db = get_db()
    db.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
    db.commit()
    flash("Snapshot deleted.", "success")
    return redirect(url_for(".index", display_currency=display_currency))