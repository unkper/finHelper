from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from flask import Flask, flash, g, redirect, render_template, request, url_for


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "assets.db"
SUPPORTED_CURRENCIES = ("CNY", "HKD", "USD")
DEFAULT_RATES = {
    "CNY": {"CNY": 1.0, "HKD": 1.08, "USD": 0.14},
    "HKD": {"CNY": 0.93, "HKD": 1.0, "USD": 0.128},
    "USD": {"CNY": 7.20, "HKD": 7.80, "USD": 1.0},
}
API_PROXY = "http://127.0.0.1:6244"


app = Flask(__name__)
app.config["SECRET_KEY"] = "finhelper-dev-key"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def quantize(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def init_db() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL DEFAULT 'bank',
        currency TEXT NOT NULL DEFAULT 'CNY',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS snapshot_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        amount REAL NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT
    );

    CREATE TABLE IF NOT EXISTS exchange_rates (
        target_date TEXT NOT NULL,
        base_currency TEXT NOT NULL,
        rates TEXT NOT NULL,
        PRIMARY KEY (target_date, base_currency)
    );
    """
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(schema)
        migrate_db(conn)
        conn.commit()


def migrate_db(conn: sqlite3.Connection) -> None:
    account_columns = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
    if "currency" not in account_columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'CNY'")

    entry_columns = {row["name"] for row in conn.execute("PRAGMA table_info(snapshot_entries)")}
    if "amount" in entry_columns:
        return

    if {"cny_amount", "hkd_amount", "usd_amount"}.issubset(entry_columns):
        legacy_rows = conn.execute(
            """
            SELECT e.id, e.snapshot_id, e.account_id, e.cny_amount, e.hkd_amount, e.usd_amount, e.sort_order
            FROM snapshot_entries e
            ORDER BY e.id ASC
            """
        ).fetchall()

        conn.executescript(
            """
            ALTER TABLE snapshot_entries RENAME TO snapshot_entries_legacy;
            CREATE TABLE snapshot_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE,
                FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT
            );
            """
        )

        for row in legacy_rows:
            candidates = [
                ("CNY", row["cny_amount"]),
                ("HKD", row["hkd_amount"]),
                ("USD", row["usd_amount"]),
            ]
            chosen_currency = "CNY"
            chosen_amount = 0.0
            for currency, amount in candidates:
                if abs(amount or 0) > 0:
                    chosen_currency = currency
                    chosen_amount = amount
                    break

            conn.execute(
                "UPDATE accounts SET currency = ? WHERE id = ?",
                (chosen_currency, row["account_id"]),
            )
            conn.execute(
                """
                INSERT INTO snapshot_entries (id, snapshot_id, account_id, amount, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row["id"], row["snapshot_id"], row["account_id"], chosen_amount, row["sort_order"]),
            )

        conn.execute("DROP TABLE snapshot_entries_legacy")


init_db()


def parse_amount(raw_value: str | None) -> float:
    if raw_value is None or raw_value.strip() == "":
        return 0.0
    return quantize(float(raw_value))


def parse_snapshot_form(form: Any) -> tuple[str, str, str, list[dict[str, Any]]]:
    snapshot_date = form.get("snapshot_date", "").strip() or date.today().isoformat()
    note = form.get("note", "").strip()
    display_currency = form.get("display_currency", "CNY").upper()
    if display_currency not in SUPPORTED_CURRENCIES:
        display_currency = "CNY"

    entries: list[dict[str, Any]] = []
    account_names = form.getlist("account_name[]")
    categories = form.getlist("account_category[]")
    currencies = form.getlist("account_currency[]")
    amounts = form.getlist("amount[]")

    for index, raw_name in enumerate(account_names):
        name = raw_name.strip()
        if not name:
            continue

        category = (categories[index] if index < len(categories) else "bank").strip() or "bank"
        currency = (currencies[index] if index < len(currencies) else "CNY").upper()
        if currency not in SUPPORTED_CURRENCIES:
            currency = "CNY"

        entries.append(
            {
                "name": name,
                "category": category,
                "currency": currency,
                "amount": parse_amount(amounts[index] if index < len(amounts) else None),
                "sort_order": index,
            }
        )

    return snapshot_date, note, display_currency, entries


def upsert_account(name: str, category: str, currency: str) -> int:
    db = get_db()
    db.execute(
        """
        INSERT INTO accounts (name, category, currency)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category = excluded.category,
            currency = excluded.currency
        """,
        (name, category, currency),
    )
    return db.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()["id"]


def persist_snapshot_entries(
    snapshot_id: int,
    snapshot_date: str,
    note: str,
    entries: list[dict[str, Any]],
) -> None:
    db = get_db()
    db.execute(
        "UPDATE snapshots SET snapshot_date = ?, note = ? WHERE id = ?",
        (snapshot_date, note, snapshot_id),
    )
    db.execute("DELETE FROM snapshot_entries WHERE snapshot_id = ?", (snapshot_id,))

    for entry in entries:
        account_id = upsert_account(entry["name"], entry["category"], entry["currency"])
        db.execute(
            """
            INSERT INTO snapshot_entries (snapshot_id, account_id, amount, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (snapshot_id, account_id, entry["amount"], entry["sort_order"]),
        )


def get_rate_table(base_currency: str, target_date: str) -> tuple[dict[str, float], str]:
    fallback = DEFAULT_RATES[base_currency]
    if base_currency not in SUPPORTED_CURRENCIES:
        return DEFAULT_RATES["CNY"], "default"

    db = get_db()
    cached_row = db.execute(
        "SELECT rates FROM exchange_rates WHERE target_date = ? AND base_currency = ?",
        (target_date, base_currency),
    ).fetchone()
    if cached_row:
        try:
            cached_rates = json.loads(cached_row["rates"])
            for currency in SUPPORTED_CURRENCIES:
                if currency not in cached_rates:
                    cached_rates[currency] = fallback.get(currency, 1.0)
            return cached_rates, "db_cache"
        except json.JSONDecodeError:
            pass

    url = f"https://api.frankfurter.app/{target_date}?from={base_currency}&to=CNY,HKD,USD"
    headers = {"User-Agent": "Mozilla/5.0 (FinHelper/1.0)"}
    try:
        if API_PROXY:
            opener = build_opener(ProxyHandler({"http": API_PROXY, "https": API_PROXY}))
        else:
            opener = build_opener()
        request_obj = Request(url, headers=headers)
        with opener.open(request_obj, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return fallback, "default"

    rates = payload.get("rates", {})
    table = {
        currency: (1.0 if currency == base_currency else float(rates.get(currency, fallback[currency])))
        for currency in SUPPORTED_CURRENCIES
    }
    try:
        db.execute(
            """
            INSERT INTO exchange_rates (target_date, base_currency, rates)
            VALUES (?, ?, ?)
            ON CONFLICT(target_date, base_currency) DO UPDATE SET rates = excluded.rates
            """,
            (target_date, base_currency, json.dumps(table)),
        )
        db.commit()
    except sqlite3.Error:
        pass
    return table, "historical"


def convert_amount(amount: float, from_currency: str, to_currency: str, rate_cache: dict[str, Any]) -> tuple[float, str]:
    if from_currency == to_currency:
        return amount, "native"

    cache_key = f"{from_currency}:{rate_cache['date']}"
    if cache_key not in rate_cache:
        rate_cache[cache_key] = get_rate_table(from_currency, rate_cache["date"])

    table, source = rate_cache[cache_key]
    return amount * table[to_currency], source


def fetch_accounts() -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        "SELECT id, name, category, currency FROM accounts ORDER BY lower(name)"
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_snapshot_entries(snapshot_id: int) -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT e.id, e.amount, e.sort_order, a.name, a.category, a.currency
        FROM snapshot_entries e
        JOIN accounts a ON a.id = e.account_id
        WHERE e.snapshot_id = ?
        ORDER BY e.sort_order ASC, a.name ASC
        """,
        (snapshot_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def summarize_snapshot(snapshot_id: int, display_currency: str) -> dict[str, Any] | None:
    db = get_db()
    header = db.execute(
        """
        SELECT s.id, s.snapshot_date, s.note, s.created_at, COUNT(e.id) AS account_count
        FROM snapshots s
        LEFT JOIN snapshot_entries e ON e.snapshot_id = s.id
        WHERE s.id = ?
        GROUP BY s.id
        """,
        (snapshot_id,),
    ).fetchone()
    if header is None:
        return None

    entries = fetch_snapshot_entries(snapshot_id)
    rate_cache: dict[str, Any] = {"date": header["snapshot_date"]}
    total = 0.0
    rate_sources: set[str] = set()
    detailed_entries = []
    for entry in entries:
        converted_amount, rate_source = convert_amount(
            entry["amount"], entry["currency"], display_currency, rate_cache
        )
        total += converted_amount
        rate_sources.add(rate_source)
        detailed_entries.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "category": entry["category"],
                "currency": entry["currency"],
                "amount": quantize(entry["amount"]),
                "converted_amount": quantize(converted_amount),
            }
        )

    summary_rate_source = "native"
    if "historical" in rate_sources:
        summary_rate_source = "historical"
    elif "default" in rate_sources:
        summary_rate_source = "default"
    elif "db_cache" in rate_sources:
        summary_rate_source = "historical"

    return {
        "id": header["id"],
        "snapshot_date": header["snapshot_date"],
        "note": header["note"],
        "created_at": header["created_at"],
        "account_count": header["account_count"],
        "display_currency": display_currency,
        "total_in_display_currency": quantize(total),
        "rate_source": summary_rate_source,
        "entries": detailed_entries,
    }


def fetch_snapshot_cards(limit: int = 12, display_currency: str = "CNY") -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT id
        FROM snapshots
        ORDER BY snapshot_date DESC, created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    cards = []
    for row in rows:
        summary = summarize_snapshot(row["id"], display_currency)
        if summary:
            cards.append(summary)
    return cards


def fetch_latest_totals(display_currency: str) -> dict[str, Any] | None:
    cards = fetch_snapshot_cards(limit=1, display_currency=display_currency)
    return cards[0] if cards else None


def fetch_trend_rows(display_currency: str) -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT id, snapshot_date
        FROM snapshots
        ORDER BY snapshot_date ASC, created_at ASC
        """
    ).fetchall()
    trend_rows = []
    for row in rows:
        summary = summarize_snapshot(row["id"], display_currency)
        if summary:
            trend_rows.append(
                {
                    "snapshot_id": row["id"],
                    "snapshot_date": row["snapshot_date"],
                    "total": summary["total_in_display_currency"],
                }
            )
    return trend_rows


def fetch_growth_rows(display_currency: str) -> list[dict[str, Any]]:
    trend_rows = fetch_trend_rows(display_currency)
    growth_rows: list[dict[str, Any]] = []
    previous_row: dict[str, Any] | None = None

    for row in trend_rows:
        if previous_row is None:
            growth_rows.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "snapshot_date": row["snapshot_date"],
                    "growth_per_day": 0.0,
                    "day_span": 0,
                }
            )
            previous_row = row
            continue

        current_date = date.fromisoformat(row["snapshot_date"])
        previous_date = date.fromisoformat(previous_row["snapshot_date"])
        day_span = max((current_date - previous_date).days, 1)
        total_diff = row["total"] - previous_row["total"]
        growth_rows.append(
            {
                "snapshot_id": row["snapshot_id"],
                "snapshot_date": row["snapshot_date"],
                "growth_per_day": quantize(total_diff / day_span),
                "day_span": day_span,
            }
        )
        previous_row = row

    return growth_rows


def build_pie_data(display_currency: str) -> list[dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT id, snapshot_date
        FROM snapshots
        ORDER BY snapshot_date DESC, created_at DESC
        """
    ).fetchall()
    datasets = []
    for row in rows:
        summary = summarize_snapshot(row["id"], display_currency)
        if not summary:
            continue
        datasets.append(
            {
                "snapshot_id": row["id"],
                "snapshot_date": row["snapshot_date"],
                "values": [
                    {
                        "label": entry["name"],
                        "value": entry["converted_amount"],
                        "native_amount": entry["amount"],
                        "currency": entry["currency"],
                    }
                    for entry in summary["entries"]
                    if abs(entry["converted_amount"]) > 0
                ],
            }
        )
    return datasets


def account_has_entries(account_id: int) -> bool:
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM snapshot_entries WHERE account_id = ? LIMIT 1",
        (account_id,),
    ).fetchone()
    return row is not None


@app.route("/")
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


@app.route("/snapshots", methods=["POST"])
def create_snapshot():
    snapshot_date, note, display_currency, entries = parse_snapshot_form(request.form)
    if not entries:
        flash("Please add at least one account before saving.", "error")
        return redirect(url_for("index", display_currency=display_currency))

    db = get_db()
    snapshot_id = db.execute(
        "INSERT INTO snapshots (snapshot_date, note) VALUES (?, ?)",
        (snapshot_date, note),
    ).lastrowid
    persist_snapshot_entries(snapshot_id, snapshot_date, note, entries)
    db.commit()
    flash("Snapshot saved.", "success")
    return redirect(url_for("index", display_currency=display_currency))


@app.route("/accounts")
def manage_accounts():
    return render_template("accounts.html", accounts=fetch_accounts())


@app.route("/accounts/<int:account_id>/delete", methods=["POST"])
def delete_account(account_id: int):
    if account_has_entries(account_id):
        flash("This account is used by history snapshots and cannot be deleted.", "error")
        return redirect(url_for("manage_accounts"))

    db = get_db()
    db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    db.commit()
    flash("Account deleted.", "success")
    return redirect(url_for("manage_accounts"))


@app.route("/snapshots/<int:snapshot_id>")
def snapshot_detail(snapshot_id: int):
    display_currency = request.args.get("display_currency", "CNY").upper()
    if display_currency not in SUPPORTED_CURRENCIES:
        display_currency = "CNY"

    snapshot = summarize_snapshot(snapshot_id, display_currency)
    if snapshot is None:
        flash("Snapshot not found.", "error")
        return redirect(url_for("index", display_currency=display_currency))

    return render_template(
        "snapshot_detail.html",
        snapshot=snapshot,
        accounts=fetch_accounts(),
        display_currency=display_currency,
        supported_currencies=SUPPORTED_CURRENCIES,
    )


@app.route("/snapshots/<int:snapshot_id>/update", methods=["POST"])
def update_snapshot(snapshot_id: int):
    snapshot_date, note, display_currency, entries = parse_snapshot_form(request.form)
    if not entries:
        flash("Please keep at least one account in the snapshot.", "error")
        return redirect(url_for("snapshot_detail", snapshot_id=snapshot_id, display_currency=display_currency))

    if summarize_snapshot(snapshot_id, display_currency) is None:
        flash("Snapshot not found.", "error")
        return redirect(url_for("index", display_currency=display_currency))

    persist_snapshot_entries(snapshot_id, snapshot_date, note, entries)
    get_db().commit()
    flash("Snapshot updated.", "success")
    return redirect(url_for("snapshot_detail", snapshot_id=snapshot_id, display_currency=display_currency))


@app.route("/snapshots/<int:snapshot_id>/delete", methods=["POST"])
def delete_snapshot(snapshot_id: int):
    display_currency = request.form.get("display_currency", "CNY").upper()
    if display_currency not in SUPPORTED_CURRENCIES:
        display_currency = "CNY"

    db = get_db()
    db.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
    db.commit()
    flash("Snapshot deleted.", "success")
    return redirect(url_for("index", display_currency=display_currency))


if __name__ == "__main__":
    app.run(debug=True)
