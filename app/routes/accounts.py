from flask import flash, redirect, render_template, url_for

from app.database import get_db
from app.services.snapshot import account_has_entries, fetch_accounts

from . import bp

@bp.route("/accounts")
def manage_accounts():
    return render_template("accounts.html", accounts=fetch_accounts())

@bp.route("/accounts/<int:account_id>/delete", methods=["POST"])
def delete_account(account_id: int):
    if account_has_entries(account_id):
        flash("This account is used by history snapshots and cannot be deleted.", "error")
        return redirect(url_for(".manage_accounts"))

    db = get_db()
    db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    db.commit()
    flash("Account deleted.", "success")
    return redirect(url_for(".manage_accounts"))