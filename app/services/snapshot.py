import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.database import get_db
from app.services.exchange import convert_amount
from app.utils import quantize

def parse_amount(raw_value: Optional[str]) -> float:
    if raw_value is None or raw_value.strip() == "":
        return 0.0
    return quantize(float(raw_value))

def parse_snapshot_form(form: Any) -> Tuple[str, str, str, List[Dict[str, Any]]]:
    snapshot_date = form.get("snapshot_date", "").strip() or date.today().isoformat()
    note = form.get("note", "").strip()
    display_currency = form.get("display_currency", "CNY").upper()
    if display_currency not in ("CNY", "HKD", "USD"):
        display_currency = "CNY"

    entries: List[Dict[str, Any]] = []
    account_names = form.getlist("account_name[]")
    categories = form.getlist("account_category[]")
    currencies = form.getlist("account_currency[]")
    amounts = form.getlist("amount[]")
    regions = form.getlist("account_region[]")

    for index, raw_name in enumerate(account_names):
        name = raw_name.strip()
        if not name:
            continue

        category = (categories[index] if index < len(categories) else "bank").strip() or "bank"
        currency = (currencies[index] if index < len(currencies) else "CNY").upper()
        if currency not in ("CNY", "HKD", "USD"):
            currency = "CNY"

        region = (regions[index] if index < len(regions) else "中国").strip() or "中国"

        entries.append(
            {
                "name": name,
                "category": category,
                "currency": currency,
                "region": region,
                "amount": parse_amount(amounts[index] if index < len(amounts) else None),
                "sort_order": index,
            }
        )

    return snapshot_date, note, display_currency, entries

def upsert_account(name: str, category: str, currency: str, region: str) -> int:
    db = get_db()
    db.execute(
        """
        INSERT INTO accounts (name, category, currency, region)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category = excluded.category,
            currency = excluded.currency,
            region = excluded.region
        """,
        (name, category, currency, region),
    )
    return db.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()["id"]

def persist_snapshot_entries(
    snapshot_id: int,
    snapshot_date: str,
    note: str,
    entries: List[Dict[str, Any]],
) -> None:
    db = get_db()
    db.execute(
        "UPDATE snapshots SET snapshot_date = ?, note = ? WHERE id = ?",
        (snapshot_date, note, snapshot_id),
    )
    db.execute("DELETE FROM snapshot_entries WHERE snapshot_id = ?", (snapshot_id,))

    for entry in entries:
        account_id = upsert_account(entry["name"], entry["category"], entry["currency"], entry["region"])
        db.execute(
            """
            INSERT INTO snapshot_entries (snapshot_id, account_id, amount, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (snapshot_id, account_id, entry["amount"], entry["sort_order"]),
        )

def fetch_accounts() -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        "SELECT id, name, category, currency FROM accounts ORDER BY lower(name)"
    ).fetchall()
    return [dict(row) for row in rows]

def fetch_snapshot_entries(snapshot_id: int) -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT e.id, e.amount, e.sort_order, a.name, a.category, a.currency, a.region
        FROM snapshot_entries e
        JOIN accounts a ON a.id = e.account_id
        WHERE e.snapshot_id = ?
        ORDER BY e.sort_order ASC, a.name ASC
        """,
        (snapshot_id,),
    ).fetchall()
    return [dict(row) for row in rows]

def summarize_snapshot(snapshot_id: int, display_currency: str) -> Optional[Dict[str, Any]]:
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
    rate_cache: Dict[str, Any] = {"date": header["snapshot_date"]}
    total = 0.0
    rate_sources: set = set()
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
                "region": entry.get("region", "中国"),
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

def fetch_snapshot_cards(limit: int = 12, display_currency: str = "CNY") -> List[Dict[str, Any]]:
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

def fetch_latest_totals(display_currency: str) -> Optional[Dict[str, Any]]:
    cards = fetch_snapshot_cards(limit=1, display_currency=display_currency)
    return cards[0] if cards else None

def fetch_trend_rows(display_currency: str) -> List[Dict[str, Any]]:
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

def fetch_growth_rows(display_currency: str) -> List[Dict[str, Any]]:
    trend_rows = fetch_trend_rows(display_currency)
    growth_rows: List[Dict[str, Any]] = []
    previous_row: Optional[Dict[str, Any]] = None

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

def build_pie_data(display_currency: str) -> List[Dict[str, Any]]:
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

        cat_map = {"bank": "银行", "stock": "证券", "broker": "券商"}
        composite_data = {}

        for entry in summary["entries"]:
            if abs(entry["converted_amount"]) <= 0:
                continue

            # 1. 获取当前账户的国家和类型（这需要确保 summarize_snapshot 的 entry 带有 region 和 category）
            # 注意：如果原本的 summarize_snapshot 没查 region，需要在其 SQL 关联查询中加入 a.region
            region = entry.get("region", "中国")
            cat_eng = entry.get("category", "bank")
            cat_zh = cat_map.get(cat_eng, "其他")

            # 2. 生成复合标签，例如 "中国银行" 或 "美国证券"
            composite_label = f"{region}{cat_zh}"

            # 3. 按复合标签累加金额
            if composite_label not in composite_data:
                composite_data[composite_label] = 0.0
            composite_data[composite_label] += entry["converted_amount"]

        datasets.append(
            {
                "snapshot_id": row["id"],
                "snapshot_date": row["snapshot_date"],
                "values": [
                    {
                        "label": label,
                        "value": quantize(amount)
                    }
                    for label, amount in composite_data.items()
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