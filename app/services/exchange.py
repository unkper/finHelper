import json
import sqlite3
from typing import Any, Dict, Tuple
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from flask import current_app

from app.database import SUPPORTED_CURRENCIES, get_db

DEFAULT_RATES = {
    "CNY": {"CNY": 1.0, "HKD": 1.08, "USD": 0.14},
    "HKD": {"CNY": 0.93, "HKD": 1.0, "USD": 0.128},
    "USD": {"CNY": 7.20, "HKD": 7.80, "USD": 1.0},
}

def get_rate_table(base_currency: str, target_date: str) -> Tuple[Dict[str, float], str]:
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
    api_proxy = current_app.config.get("API_PROXY")
    try:
        if api_proxy:
            opener = build_opener(ProxyHandler({"http": api_proxy, "https": api_proxy}))
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

def convert_amount(amount: float, from_currency: str, to_currency: str, rate_cache: Dict[str, Any]) -> Tuple[float, str]:
    if from_currency == to_currency:
        return amount, "native"

    cache_key = f"{from_currency}:{rate_cache['date']}"
    if cache_key not in rate_cache:
        rate_cache[cache_key] = get_rate_table(from_currency, rate_cache["date"])

    table, source = rate_cache[cache_key]
    return amount * table[to_currency], source