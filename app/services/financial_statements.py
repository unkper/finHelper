"""投研图表数据：合并同 ticker 多份已分析报告（不调用 FMP）。"""
from typing import Any, Dict, List, Optional

from app.services.financial_reports import fetch_ticker_extracted_for_charts


def _merge_period_maps(base: Dict[str, Dict], extra: Dict[str, Dict]) -> Dict[str, Dict]:
    merged = dict(extra)
    for period, block in base.items():
        if period not in merged:
            merged[period] = block
        else:
            combined = dict(merged[period])
            combined.update(block)
            merged[period] = combined
    return merged


def _sort_periods(periods: List[str]) -> List[str]:
    def sort_key(raw) -> tuple[int, int]:
        p = str(raw).strip().upper()
        try:
            year_s, q_s = p.split("-", 1)
            if q_s.startswith("Q") and len(q_s) == 2 and q_s[1].isdigit():
                return (int(year_s), int(q_s[1]))
        except (ValueError, AttributeError):
            pass
        return (999999, 99)

    cleaned = {str(x).strip() for x in periods if x is not None and str(x).strip()}
    return sorted(cleaned, key=sort_key)


def _compute_margin_trends(
    income: Dict[str, Dict[str, Any]],
    periods: List[str],
) -> Dict[str, List[Optional[float]]]:
    gross = []
    net = []
    for period in periods:
        block = income.get(period) or {}
        revenue = block.get("revenue")
        gross_profit = block.get("gross_profit")
        net_income = block.get("net_income")
        if revenue and gross_profit is not None:
            gross.append(round(gross_profit / revenue * 100, 2))
        else:
            gross.append(None)
        if revenue and net_income is not None:
            net.append(round(net_income / revenue * 100, 2))
        else:
            net.append(None)
    return {"gross_margin_pct": gross, "net_margin_pct": net}


def _pct_of(part: Any, whole: Any) -> Optional[float]:
    if part is None or whole is None or whole == 0:
        return None
    try:
        return round(float(part) / float(whole) * 100, 2)
    except (TypeError, ValueError):
        return None


def _ratio(a: Any, b: Any) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    try:
        return round(float(a) / float(b), 2)
    except (TypeError, ValueError):
        return None


def _revenue_for_period(
    period: str,
    income: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
) -> Optional[float]:
    inc = income.get(period) or {}
    rev = inc.get("revenue")
    if rev is not None:
        return rev
    k = (kpis.get(period) or {}).get("revenue")
    if isinstance(k, dict):
        return k.get("value")
    return None


def _net_income_for_period(
    period: str,
    income: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
) -> Optional[float]:
    inc = income.get(period) or {}
    net = inc.get("net_income")
    if net is not None:
        return net
    k = (kpis.get(period) or {}).get("net_profit")
    if isinstance(k, dict):
        return k.get("value")
    return None


def _compute_derived(
    income: Dict[str, Dict[str, Any]],
    balance: Dict[str, Dict[str, Any]],
    cash_flow: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
    periods: List[str],
    focus_period: str | None,
) -> Dict[str, Any]:
    revenue_series: List[Optional[float]] = []
    net_income_series: List[Optional[float]] = []
    rd_pct: List[Optional[float]] = []
    sga_pct: List[Optional[float]] = []
    operating: List[Optional[float]] = []
    investing: List[Optional[float]] = []
    financing: List[Optional[float]] = []
    ocf_quality_ratio: List[Optional[float]] = []

    for period in periods:
        inc = income.get(period) or {}
        cf = cash_flow.get(period) or {}
        rev = _revenue_for_period(period, income, kpis)
        net = _net_income_for_period(period, income, kpis)
        revenue_series.append(rev)
        net_income_series.append(net)
        rd_pct.append(_pct_of(inc.get("rd"), rev))
        sga_pct.append(_pct_of(inc.get("sga"), rev))
        ocf = cf.get("operating")
        operating.append(ocf)
        investing.append(cf.get("investing"))
        financing.append(cf.get("financing"))
        ocf_quality_ratio.append(_ratio(ocf, net))

    asset_mix: List[Dict[str, Any]] = []
    if focus_period:
        b = balance.get(focus_period) or {}
        for name, key in (
            ("现金", "cash"),
            ("应收账款", "receivables"),
            ("存货", "inventory"),
            ("固定资产", "ppe"),
        ):
            val = b.get(key)
            if val is not None:
                asset_mix.append({"name": name, "value": val})

    return {
        "revenue_series": revenue_series,
        "net_income_series": net_income_series,
        "expense_ratio_trend": {"rd_pct": rd_pct, "sga_pct": sga_pct},
        "cashflow_series": {
            "operating": operating,
            "investing": investing,
            "financing": financing,
        },
        "ocf_quality_ratio": ocf_quality_ratio,
        "asset_mix": asset_mix,
    }


def _merge_extracted_list(
    reports: List[Dict[str, Any]],
    current_report_id: int | None,
) -> tuple[Dict[str, Any], List[int], List[str]]:
    """按报告 id 升序合并，当前报告最后写入以覆盖同 period。"""
    ordered = sorted(reports, key=lambda r: r["id"])
    if current_report_id is not None:
        ordered = [r for r in ordered if r["id"] != current_report_id]
        current = next((r for r in reports if r["id"] == current_report_id), None)
        if current:
            ordered.append(current)

    income: Dict[str, Dict] = {}
    balance: Dict[str, Dict] = {}
    cash_flow: Dict[str, Dict] = {}
    kpis: Dict[str, Dict] = {}
    red_flags: List[Dict[str, str]] = []
    material_events: List[Dict[str, Any]] = []
    material_seen: set[tuple[str, str, str]] = set()
    currency = "USD"
    unit = "millions"
    linked_ids: List[int] = []
    all_periods: List[str] = []

    for item in ordered:
        ext = item.get("extracted")
        if not ext:
            continue
        linked_ids.append(item["id"])
        currency = ext.get("currency") or currency
        unit = ext.get("unit") or unit
        income = _merge_period_maps(
            ext.get("income_statement") if isinstance(ext.get("income_statement"), dict) else {},
            income,
        )
        balance = _merge_period_maps(
            ext.get("balance_sheet") if isinstance(ext.get("balance_sheet"), dict) else {},
            balance,
        )
        cash_flow = _merge_period_maps(
            ext.get("cash_flow") if isinstance(ext.get("cash_flow"), dict) else {},
            cash_flow,
        )
        kpis = _merge_period_maps(
            ext.get("kpis") if isinstance(ext.get("kpis"), dict) else {},
            kpis,
        )
        all_periods.extend(ext.get("periods") or [])
        for flag in ext.get("red_flags") or []:
            if isinstance(flag, dict) and flag.get("message"):
                red_flags.append(flag)
        for event in ext.get("material_events") or []:
            if not isinstance(event, dict):
                continue
            etype = str(event.get("type") or "").strip().lower()
            title = str(event.get("title") or "").strip()
            if etype not in ("profit", "loss") or not title:
                continue
            period = str(event.get("period") or "").strip()
            key = (etype, title, period)
            if key in material_seen:
                continue
            material_seen.add(key)
            material_events.append(event)

    merged = {
        "currency": currency,
        "unit": unit,
        "periods": _sort_periods(all_periods + list(income.keys())),
        "kpis": kpis,
        "income_statement": income,
        "balance_sheet": balance,
        "cash_flow": cash_flow,
        "red_flags": red_flags,
        "material_events": material_events,
    }
    return merged, linked_ids, merged["periods"]


def build_chart_payload(
    ticker: str,
    focus_period: str | None = None,
    *,
    current_report_id: int | None = None,
    current_extracted: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """合并同 ticker 下所有已分析报告，供前端 ECharts 渲染。"""
    ticker = ticker.strip().upper()
    reports = fetch_ticker_extracted_for_charts(ticker)

    if current_report_id is not None and current_extracted:
        found = any(r["id"] == current_report_id for r in reports)
        if not found:
            reports.append({
                "id": current_report_id,
                "fiscal_period": focus_period,
                "extracted": current_extracted,
            })

    merged, linked_ids, linked_periods = _merge_extracted_list(reports, current_report_id)

    if current_extracted and not merged.get("periods"):
        merged = {**merged, **{k: current_extracted.get(k) for k in (
            "currency", "unit", "periods", "kpis", "income_statement",
            "balance_sheet", "cash_flow", "red_flags", "material_events",
        ) if current_extracted.get(k) is not None}}

    periods = _sort_periods(
        list(merged.get("periods") or [])
        + list((merged.get("income_statement") or {}).keys())
    )
    if focus_period and focus_period not in periods:
        periods.append(focus_period)
        periods = _sort_periods(periods)

    display_period = focus_period or (periods[-1] if periods else None)
    ai_summary = ""
    if current_report_id:
        for r in reports:
            if r["id"] == current_report_id and r.get("ai_summary"):
                ai_summary = r["ai_summary"]
                break
    if not ai_summary and current_extracted:
        ai_summary = current_extracted.get("ai_summary") or ""

    income = merged.get("income_statement") or {}
    balance = merged.get("balance_sheet") or {}
    cash_flow = merged.get("cash_flow") or {}
    kpis = merged.get("kpis") or {}

    return {
        "ticker": ticker,
        "currency": merged.get("currency") or "USD",
        "unit": merged.get("unit") or "millions",
        "periods": periods,
        "focus_period": display_period,
        "kpis": kpis,
        "income_statement": income,
        "balance_sheet": balance,
        "cash_flow": cash_flow,
        "red_flags": merged.get("red_flags") or [],
        "material_events": merged.get("material_events") or [],
        "ai_summary": ai_summary,
        "trends": _compute_margin_trends(income, periods),
        "derived": _compute_derived(income, balance, cash_flow, kpis, periods, display_period),
        "linked_report_ids": linked_ids,
        "linked_periods": linked_periods,
        "report_count": len(linked_ids),
    }
