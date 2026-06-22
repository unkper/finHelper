"""FMP financial-reports-json → extracted_json。"""
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.services.financial_ai import normalize_extracted_payload
from app.services.fiscal_calendar import build_period_context, _parse_date
from app.services.sec_statement_maps import (
    BALANCE_MAP,
    CASH_MAP,
    INCOME_MAP,
    build_kpis,
    match_field,
    normalize_label,
    to_float,
)

_VALID_PERIODS = frozenset({"Q1", "Q2", "Q3", "Q4", "FY"})


def _find_section(payload: Dict[str, Any], *keywords: str) -> Tuple[Optional[str], List[Any]]:
    keys = [k for k in payload if isinstance(k, str)]
    for key in keys:
        upper = key.upper()
        if all(kw.upper() in upper for kw in keywords):
            section = payload.get(key)
            if isinstance(section, list):
                return key, section
    return None, []


def _section_items(section: List[Any]) -> List[Tuple[str, List[Any]]]:
    rows: List[Tuple[str, List[Any]]] = []
    for item in section:
        if not isinstance(item, dict):
            continue
        for label, vals in item.items():
            if isinstance(vals, list):
                rows.append((str(label), vals))
            else:
                rows.append((str(label), [vals]))
    return rows


def _scope_from_header(values: List[Any]) -> str:
    scopes: List[str] = []
    for val in values:
        norm = normalize_label(val)
        if not norm:
            continue
        if "three months" in norm or "3 months" in norm or "quarter ended" in norm:
            scopes.append("quarter")
        elif "nine months" in norm or "9 months" in norm:
            scopes.append("ytd")
        elif "year ended" in norm or "years ended" in norm:
            scopes.append("annual")
    if "quarter" in scopes:
        return "quarter"
    if "ytd" in scopes:
        return "ytd"
    if "annual" in scopes:
        return "annual"
    return "unknown"


def _pick_flow_columns(rows: List[Tuple[str, List[Any]]]) -> Tuple[str, int, Optional[int], Optional[date]]:
    """利润表/现金流：识别 scope 与当前/同比列。"""
    scope = "unknown"
    header_scopes: List[str] = []
    date_values: List[Any] = []

    for label, vals in rows[:8]:
        norm = normalize_label(label)
        row_scope = _scope_from_header(vals)
        if row_scope != "unknown":
            header_scopes = [normalize_label(v) for v in vals]
            scope = row_scope
        if norm == "items":
            date_values = list(vals)

    current_col = 0
    prior_col: Optional[int] = None

    if scope == "quarter" and header_scopes:
        quarter_indices = [
            i for i, s in enumerate(header_scopes)
            if s and ("three months" in s or "3 months" in s)
        ]
        if quarter_indices:
            current_col = quarter_indices[0]
            if len(quarter_indices) > 1:
                prior_col = quarter_indices[1]
            elif current_col + 1 < len(date_values):
                prior_col = current_col + 1
    elif scope in ("ytd", "annual") and len(date_values) >= 2:
        current_col = 0
        prior_col = 1
    elif len(date_values) >= 2:
        current_col = 0
        prior_col = 1

    period_end = None
    parsed_dates = [_parse_date(v) for v in date_values]
    if current_col < len(parsed_dates) and parsed_dates[current_col]:
        period_end = parsed_dates[current_col]
    else:
        valid = [d for d in parsed_dates if d]
        if valid:
            period_end = max(valid)

    return scope, current_col, prior_col, period_end


def _pick_balance_columns(rows: List[Tuple[str, List[Any]]]) -> Tuple[int, Optional[int], Optional[date]]:
    """资产负债表：取最近报告日列。"""
    date_cols: List[Tuple[int, date]] = []
    for label, vals in rows[:6]:
        norm = normalize_label(label)
        if "balance sheet" in norm and "usd" in norm:
            for i, val in enumerate(vals):
                parsed = _parse_date(val)
                if parsed:
                    date_cols.append((i, parsed))
        if norm == "items":
            for i, val in enumerate(vals):
                parsed = _parse_date(val)
                if parsed:
                    date_cols.append((i, parsed))

    if not date_cols:
        return 1, 2, None

    date_cols.sort(key=lambda x: x[1], reverse=True)
    current_col = date_cols[0][0]
    prior_col = date_cols[1][0] if len(date_cols) > 1 else None
    return current_col, prior_col, date_cols[0][1]


def _extract_fields(
    rows: List[Tuple[str, List[Any]]],
    mapping: Dict[str, Tuple[str, ...]],
    current_col: int,
    prior_col: Optional[int],
) -> Tuple[Dict[str, float], Dict[str, float]]:
    current: Dict[str, float] = {}
    prior: Dict[str, float] = {}
    for label, vals in rows:
        field = match_field(label, mapping)
        if not field:
            continue
        cur_val = to_float(vals[current_col] if current_col < len(vals) else None)
        if cur_val is not None:
            current[field] = round(cur_val, 2)
        if prior_col is not None and prior_col < len(vals):
            prev_val = to_float(vals[prior_col])
            if prev_val is not None:
                prior[field] = round(prev_val, 2)
    return current, prior


def extract_cover_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    """从 Cover Page 提取元数据（轻量预览）。"""
    meta: Dict[str, Any] = {}
    cover = payload.get("Cover Page")
    if not isinstance(cover, list):
        return meta

    for item in cover:
        if not isinstance(item, dict):
            continue
        for label, vals in item.items():
            norm = normalize_label(label)
            val0 = vals[0] if isinstance(vals, list) and vals else vals
            if norm == "document type":
                meta["form_type"] = str(val0 or "").strip().upper() or None
            elif norm == "document period end date":
                parsed = _parse_date(val0)
                if parsed:
                    meta["period_end"] = parsed.isoformat()
            elif norm == "entity registrant name":
                meta["company_name"] = str(val0 or "").strip() or None
            elif norm == "entity central index key":
                meta["cik"] = str(val0 or "").strip() or None
            elif norm == "document fiscal year focus":
                meta["fmp_year"] = str(val0 or "").strip() or None
            elif norm == "document fiscal period focus":
                meta["fmp_period"] = str(val0 or "").strip().upper() or None

    return meta


def _normalize_period_code(raw: Any) -> str:
    code = str(raw or "").strip().upper()
    if code not in _VALID_PERIODS:
        raise ValueError(f"无效报告期：{raw}，须为 Q1–Q4 或 FY")
    return code


def parse_fmp_report_json(
    payload: Dict[str, Any],
    *,
    ticker: str | None = None,
    fmp_year: int | str | None = None,
    fmp_period: str | None = None,
) -> Dict[str, Any]:
    """将 FMP financial-reports-json 映射为 extracted_json 及建议字段。"""
    if not isinstance(payload, dict):
        raise ValueError("FMP 返回格式无效")

    cover = extract_cover_meta(payload)
    period_code = _normalize_period_code(
        fmp_period or cover.get("fmp_period") or payload.get("period")
    )
    year_raw = fmp_year or cover.get("fmp_year") or payload.get("year")
    form_type = cover.get("form_type") or ("10-K" if period_code == "FY" else "10-Q")
    company_name = cover.get("company_name")
    cik = cover.get("cik")
    parse_log: List[str] = []

    _, ops_section = _find_section(payload, "CONSOLIDATED", "OPER")
    _, bal_section = _find_section(payload, "CONSOLIDATED", "BALANCE")
    _, cf_section = _find_section(payload, "CONSOLIDATED", "CASH")

    income, income_prior = {}, {}
    balance, balance_prior = {}, {}
    cash_flow, cash_prior = {}, {}
    income_scope, cash_scope = "unknown", "unknown"
    period_end: Optional[date] = _parse_date(cover.get("period_end"))

    if ops_section:
        ops_rows = _section_items(ops_section)
        income_scope, cur_col, prior_col, ops_end = _pick_flow_columns(ops_rows)
        income, income_prior = _extract_fields(ops_rows, INCOME_MAP, cur_col, prior_col)
        parse_log.append(f"operations: {len(income)} fields, scope={income_scope}")
        if ops_end:
            period_end = ops_end
    else:
        parse_log.append("missing operations section")

    if bal_section:
        bal_rows = _section_items(bal_section)
        bal_cur, bal_prior_col, bal_end = _pick_balance_columns(bal_rows)
        balance, balance_prior = _extract_fields(bal_rows, BALANCE_MAP, bal_cur, bal_prior_col)
        parse_log.append(f"balance: {len(balance)} fields")
        if balance.get("equity") is None and balance.get("total_assets") and balance.get("total_liabilities"):
            balance["equity"] = round(balance["total_assets"] - balance["total_liabilities"], 2)
            parse_log.append("equity derived from assets - liabilities")
        balance.pop("total_liabilities", None)
        if bal_end and not period_end:
            period_end = bal_end
    else:
        parse_log.append("missing balance sheet")

    if cf_section:
        cf_rows = _section_items(cf_section)
        cash_scope, cf_cur, cf_prior, _ = _pick_flow_columns(cf_rows)
        cash_flow, cash_prior = _extract_fields(cf_rows, CASH_MAP, cf_cur, cf_prior)
        parse_log.append(f"cash flows: {len(cash_flow)} fields, scope={cash_scope}")
    else:
        parse_log.append("missing cash flows section")

    if not period_end:
        raise ValueError("无法从 FMP 财报中识别报告期末日期")

    period_ctx = build_period_context(period_end, ticker=ticker)
    calendar_period = period_ctx["calendar_period"]

    use_cash = cash_scope in ("quarter", "annual") and bool(cash_flow)
    cash_flow_block: Dict[str, Dict[str, float]] = {}
    if use_cash:
        cash_flow_block[calendar_period] = cash_flow

    raw_payload: Dict[str, Any] = {
        "currency": "USD",
        "unit": "millions",
        "periods": [calendar_period],
        "filing_meta": {
            "source": "sec_fmp",
            "form_type": form_type,
            "period_end": period_ctx["period_end"],
            "calendar_period": calendar_period,
            "filing_fy": period_ctx["filing_fy"],
            "filing_fq": period_ctx["filing_fq"],
            "fiscal_year_end_month": period_ctx["fiscal_year_end_month"],
            "fmp_year": int(year_raw) if year_raw is not None and str(year_raw).isdigit() else year_raw,
            "fmp_period": period_code,
            "cash_flow_scope": cash_scope,
            "income_scope": income_scope,
            "cik": cik,
            "company_name": company_name,
        },
        "income_statement": {calendar_period: income} if income else {},
        "balance_sheet": {calendar_period: balance} if balance else {},
        "cash_flow": cash_flow_block,
        "kpis": {
            calendar_period: build_kpis(
                income,
                income_prior,
                cash_flow if use_cash else {},
                cash_scope,
            ),
        },
        "red_flags": [],
        "material_events": [],
        "ai_summary": "",
    }

    historical: List[Dict[str, Any]] = []
    if income_prior:
        historical.append({"scope": "prior_year_column", "income_statement": income_prior})
    if balance_prior:
        if historical:
            historical[0]["balance_sheet"] = balance_prior
        else:
            historical.append({"scope": "prior_year_column", "balance_sheet": balance_prior})
    if historical:
        raw_payload["historical_periods"] = historical

    if not income and not balance:
        raise ValueError("未能从 FMP 财报识别有效三表数据")

    extracted = normalize_extracted_payload(raw_payload)
    extracted["filing_meta"] = raw_payload["filing_meta"]
    if historical:
        extracted["historical_periods"] = historical

    summary_lines = [
        f"{form_type} · {company_name or ticker or 'FMP'}",
        f"Period end: {period_ctx['period_end']} → {calendar_period}",
        f"FMP FY{year_raw} {period_code} · FY{period_ctx['filing_fy']} Q{period_ctx['filing_fq']}",
        f"Revenue: {income.get('revenue')} | Net income: {income.get('net_income')}",
        f"Cash flow scope: {cash_scope}",
    ]

    return {
        "extracted": extracted,
        "filing_meta": raw_payload["filing_meta"],
        "parse_log": parse_log,
        "source_text_summary": "\n".join(summary_lines),
        "suggested_ticker": (ticker or "").upper() or None,
        "suggested_fiscal_period": calendar_period,
        "suggested_report_date": period_ctx["period_end"],
        "suggested_title": f"{(ticker or company_name or 'FMP').strip()} {calendar_period} {form_type}",
    }


def preview_calendar_period(
    payload: Dict[str, Any],
    *,
    ticker: str | None = None,
) -> Optional[str]:
    """仅解析 Cover Page 得到日历季（供期次列表预览）。"""
    cover = extract_cover_meta(payload)
    period_end = _parse_date(cover.get("period_end"))
    if not period_end:
        return None
    try:
        return build_period_context(period_end, ticker=ticker)["calendar_period"]
    except ValueError:
        return None
