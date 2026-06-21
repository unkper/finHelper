"""FMP 基本面 TTM（三表 + profile），财报 AI 提取作回退。"""
from typing import Any, Dict, List, Optional

from flask import current_app

from app.services.quote_client import http_get_json, parse_price

FMP_BASE = "https://financialmodelingprep.com/stable"
_BALANCE_TTM_URL = f"{FMP_BASE}/balance-sheet-statement-ttm"
_INCOME_TTM_URL = f"{FMP_BASE}/income-statement-ttm"
_CASHFLOW_TTM_URL = f"{FMP_BASE}/cash-flow-statement-ttm"
_PROFILE_URL = f"{FMP_BASE}/profile"


def _first_row(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    if isinstance(payload, dict):
        return payload
    return {}


def _millions_to_usd(value: Any) -> Optional[float]:
    parsed = parse_price(value)
    if parsed is None:
        return None
    return float(parsed) * 1_000_000


def _fetch_fmp_ttm(ticker: str) -> Dict[str, Any]:
    api_key = current_app.config.get("FMP_API_KEY", "")
    if not api_key:
        return {}
    symbol = ticker.strip().upper()
    params = {"symbol": symbol, "apikey": api_key}
    balance = _first_row(http_get_json(_BALANCE_TTM_URL, params))
    income = _first_row(http_get_json(_INCOME_TTM_URL, params))
    cashflow = _first_row(http_get_json(_CASHFLOW_TTM_URL, params))
    profile = _first_row(http_get_json(_PROFILE_URL, params))

    equity = parse_price(balance.get("totalStockholdersEquity"))
    if equity is None:
        equity = parse_price(balance.get("totalEquity"))
    debt = parse_price(balance.get("totalDebt"))
    if debt is None:
        debt = parse_price(balance.get("longTermDebt"))

    rd = parse_price(income.get("researchAndDevelopmentExpenses"))
    if rd is None:
        rd = parse_price(income.get("researchAndDevelopment"))
    net_income = parse_price(income.get("netIncome"))
    operating_cf = parse_price(cashflow.get("operatingCashFlow"))
    beta = parse_price(profile.get("beta"))

    result: Dict[str, Any] = {}
    if equity is not None:
        result["equity_usd"] = equity * 1_000_000 if abs(equity) < 1e6 else equity
    if rd is not None:
        result["rd_expense_usd"] = rd * 1_000_000 if abs(rd) < 1e6 else rd
    if net_income is not None:
        result["net_income_usd"] = net_income * 1_000_000 if abs(net_income) < 1e6 else net_income
    if operating_cf is not None:
        result["operating_cf_usd"] = operating_cf * 1_000_000 if abs(operating_cf) < 1e6 else operating_cf
    if debt is not None:
        result["total_debt_usd"] = debt * 1_000_000 if abs(debt) < 1e6 else debt
    if beta is not None:
        result["beta"] = beta
    return result


def _ttm_from_extracted(
    periods: List[str],
    income: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
    balance: Dict[str, Dict[str, Any]],
    cash_flow: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    from app.services.financial_valuation import _compute_ttm, _fcf_millions_ttm, _sort_periods

    ttm = _compute_ttm(periods, income, kpis)
    periods_used = ttm.get("periods_used") or []
    rd_sum = 0.0
    rd_count = 0
    for period in periods_used:
        block = income.get(period) or {}
        rd = block.get("rd")
        if rd is not None:
            rd_sum += float(rd)
            rd_count += 1
    if rd_count and len(periods_used) == 1 and rd_count == 1:
        rd_sum *= 4

    equity = None
    if periods_used:
        latest = periods_used[-1]
        eq_block = balance.get(latest) or {}
        equity = parse_price(eq_block.get("equity"))

    debt_sum = 0.0
    debt_count = 0
    for period in periods_used:
        b = balance.get(period) or {}
        lt = b.get("long_term_debt")
        if lt is not None:
            debt_sum += float(lt)
            debt_count += 1
    if debt_count and len(periods_used) == 1:
        debt_sum *= 4

    fcf_m, _est = _fcf_millions_ttm(
        periods_used,
        income,
        kpis,
        cash_flow,
        ttm.get("revenue_millions"),
        ttm.get("net_income_millions"),
    )

    result: Dict[str, Any] = {}
    if equity is not None:
        result["equity_usd"] = equity * 1_000_000
    if rd_count:
        result["rd_expense_usd"] = rd_sum * 1_000_000
    if ttm.get("net_income_millions") is not None:
        result["net_income_usd"] = ttm["net_income_millions"] * 1_000_000
    if fcf_m is not None:
        result["operating_cf_usd"] = fcf_m * 1_000_000
    if debt_count:
        result["total_debt_usd"] = debt_sum * 1_000_000
    return result


def fetch_fundamentals_ttm(
    ticker: str,
    chart_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    返回 ticker 基本面 TTM（美元）。
    FMP 优先，缺项用 chart_payload 财报提取补全。
    """
    chart_payload = chart_payload or {}
    fmp = _fetch_fmp_ttm(ticker)
    extracted = _ttm_from_extracted(
        chart_payload.get("periods") or [],
        chart_payload.get("income_statement") or {},
        chart_payload.get("kpis") or {},
        chart_payload.get("balance_sheet") or {},
        chart_payload.get("cash_flow") or {},
    )

    merged: Dict[str, Any] = {
        "source": "none",
        "equity_usd": None,
        "rd_expense_usd": None,
        "net_income_usd": None,
        "operating_cf_usd": None,
        "beta": None,
        "total_debt_usd": None,
    }
    keys = (
        "equity_usd",
        "rd_expense_usd",
        "net_income_usd",
        "operating_cf_usd",
        "beta",
        "total_debt_usd",
    )
    fmp_hits = 0
    extract_hits = 0
    for key in keys:
        if fmp.get(key) is not None:
            merged[key] = fmp[key]
            fmp_hits += 1
        elif extracted.get(key) is not None:
            merged[key] = extracted[key]
            extract_hits += 1

    if fmp_hits and extract_hits:
        merged["source"] = "mixed"
    elif fmp_hits:
        merged["source"] = "fmp"
    elif extract_hits:
        merged["source"] = "extracted"
    return merged
