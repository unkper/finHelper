"""各图表 DeepSeek Flash 解读与全局仪表盘解读（Pro）。"""
import json
from typing import Any, Dict, List

from app.services.financial_ai import CHART_INSIGHT_MODEL, chat_completion_text
from app.services.settings import get_ai_financial_parse_model

CHART_TYPES = frozenset({
    "kpi",
    "waterfall",
    "margin_trend",
    "balance",
    "cashflow",
    "profit_ocf",
    "revenue_profit_trend",
    "expense_ratio_trend",
    "cashflow_trend",
    "asset_mix",
    "ocf_quality",
})

_CHART_LABELS = {
    "kpi": "核心 KPI 概览",
    "waterfall": "利润结构瀑布图",
    "margin_trend": "盈利能力趋势",
    "balance": "资产负债结构",
    "cashflow": "现金流量对比（单季）",
    "profit_ocf": "净利润与经营现金流",
    "revenue_profit_trend": "营收与利润趋势",
    "expense_ratio_trend": "费用率趋势",
    "cashflow_trend": "现金流三期趋势",
    "asset_mix": "资产结构",
    "ocf_quality": "盈利质量（OCF/净利）",
}

_MAX_PERIODS = 8


def _trim_periods(periods: List[str]) -> List[str]:
    if len(periods) <= _MAX_PERIODS:
        return periods
    return periods[-_MAX_PERIODS:]


def _linked_hint(payload: Dict[str, Any]) -> str:
    linked = payload.get("report_count", 1)
    if linked and linked > 1:
        periods = ", ".join(payload.get("linked_periods") or [])
        return f"数据已合并该标的 {linked} 份报告（财季：{periods}）。"
    return ""


def build_dashboard_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    periods = _trim_periods(list(payload.get("periods") or []))
    focus = payload.get("focus_period")
    derived = payload.get("derived") or {}
    income = payload.get("income_statement") or {}
    balance = payload.get("balance_sheet") or {}
    cash_flow = payload.get("cash_flow") or {}
    kpis = payload.get("kpis") or {}

    def _slice_series(values: List[Any]) -> List[Any]:
        all_periods = payload.get("periods") or []
        if len(all_periods) <= len(values):
            start = max(0, len(all_periods) - len(periods))
            return values[start : start + len(periods)]
        return values[-len(periods) :] if periods else values

    rev = derived.get("revenue_series") or []
    net = derived.get("net_income_series") or []
    expense = derived.get("expense_ratio_trend") or {}
    cf_series = derived.get("cashflow_series") or {}

    return {
        "ticker": payload.get("ticker"),
        "focus_period": focus,
        "periods": periods,
        "unit": payload.get("unit"),
        "currency": payload.get("currency"),
        "report_count": payload.get("report_count"),
        "kpis_focus": kpis.get(focus) if focus else None,
        "income_focus": income.get(focus) if focus else None,
        "balance_focus": balance.get(focus) if focus else None,
        "cash_flow_focus": cash_flow.get(focus) if focus else None,
        "trends": payload.get("trends"),
        "series": {
            "revenue": _slice_series(rev),
            "net_income": _slice_series(net),
            "rd_pct": _slice_series(expense.get("rd_pct") or []),
            "sga_pct": _slice_series(expense.get("sga_pct") or []),
            "operating_cf": _slice_series(cf_series.get("operating") or []),
            "ocf_quality_ratio": _slice_series(derived.get("ocf_quality_ratio") or []),
        },
        "asset_mix": derived.get("asset_mix"),
        "red_flags": payload.get("red_flags") or [],
        "ai_summary_from_report": payload.get("ai_summary") or "",
    }


def _slice_context(chart_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    period = payload.get("focus_period")
    ticker = payload.get("ticker")
    unit = payload.get("unit")
    derived = payload.get("derived") or {}
    periods = payload.get("periods") or []

    if chart_type == "kpi":
        return {
            "ticker": ticker,
            "period": period,
            "kpis": (payload.get("kpis") or {}).get(period),
            "unit": unit,
        }
    if chart_type == "waterfall":
        return {
            "ticker": ticker,
            "period": period,
            "income_statement": (payload.get("income_statement") or {}).get(period),
            "unit": unit,
        }
    if chart_type == "margin_trend":
        return {
            "ticker": ticker,
            "periods": periods,
            "trends": payload.get("trends"),
        }
    if chart_type == "balance":
        return {
            "ticker": ticker,
            "period": period,
            "balance_sheet": (payload.get("balance_sheet") or {}).get(period),
            "unit": unit,
        }
    if chart_type == "cashflow":
        return {
            "ticker": ticker,
            "period": period,
            "cash_flow": (payload.get("cash_flow") or {}).get(period),
            "unit": unit,
        }
    if chart_type == "profit_ocf":
        series = []
        for p in periods:
            inc = (payload.get("income_statement") or {}).get(p) or {}
            cf = (payload.get("cash_flow") or {}).get(p) or {}
            kpi = (payload.get("kpis") or {}).get(p) or {}
            net = inc.get("net_income")
            if net is None and kpi.get("net_profit"):
                net = kpi["net_profit"].get("value")
            series.append({
                "period": p,
                "net_income": net,
                "operating_cf": cf.get("operating"),
            })
        return {"ticker": ticker, "series": series, "unit": unit}
    if chart_type == "revenue_profit_trend":
        return {
            "ticker": ticker,
            "periods": periods,
            "revenue": derived.get("revenue_series"),
            "net_income": derived.get("net_income_series"),
            "unit": unit,
        }
    if chart_type == "expense_ratio_trend":
        return {
            "ticker": ticker,
            "periods": periods,
            "expense_ratio_trend": derived.get("expense_ratio_trend"),
        }
    if chart_type == "cashflow_trend":
        return {
            "ticker": ticker,
            "periods": periods,
            "cashflow_series": derived.get("cashflow_series"),
            "unit": unit,
        }
    if chart_type == "asset_mix":
        return {
            "ticker": ticker,
            "period": period,
            "asset_mix": derived.get("asset_mix"),
            "unit": unit,
        }
    if chart_type == "ocf_quality":
        return {
            "ticker": ticker,
            "periods": periods,
            "ocf_quality_ratio": derived.get("ocf_quality_ratio"),
        }
    return {"ticker": ticker, "period": period}


def explain_chart(chart_type: str, chart_payload: Dict[str, Any]) -> Dict[str, Any]:
    if chart_type not in CHART_TYPES:
        return {"error": f"不支持的图表类型: {chart_type}"}

    label = _CHART_LABELS.get(chart_type, chart_type)
    context = _slice_context(chart_type, chart_payload)
    linked_hint = _linked_hint(chart_payload)

    prompt = f"""你是财务分析助手。根据以下图表数据，用中文写 3-6 句话解读（现象 + 含义 + 1 条注意点），面向个人投资者，不要编造数据中没有的数字。

图表：{label}
{linked_hint}

数据：
{json.dumps(context, ensure_ascii=False, indent=2)}

只输出解读正文，不要标题、不要 markdown。"""

    result = chat_completion_text(prompt, model=CHART_INSIGHT_MODEL)
    if result.get("error"):
        return result
    text = result.get("text", "").strip()
    if not text:
        return {"error": "AI 未返回解读内容"}
    return {"status": "ok", "insight": text, "chart_type": chart_type}


def explain_dashboard(payload: Dict[str, Any]) -> Dict[str, Any]:
    context = build_dashboard_context(payload)
    linked_hint = _linked_hint(payload)
    model = get_ai_financial_parse_model()

    prompt = f"""你是资深财务分析助手。根据以下财报仪表盘数据，写一份中文「全局解读」，共 8-12 句话，分三段（段首用【盈利与增长】【资产负债与现金流】【风险与跟踪】作小标题，不要用 markdown 其它格式）：
1. 盈利与增长：营收/利润趋势、毛利率/费用率要点
2. 资产负债与现金流：资产结构、经营/投资/筹资现金流与盈利质量
3. 风险与跟踪：结合 red_flags，给出后续应关注的 1-2 点

{linked_hint}
禁止编造数据中不存在的指标或数字。若某块数据缺失，可略写。

数据：
{json.dumps(context, ensure_ascii=False, indent=2)}"""

    result = chat_completion_text(prompt, model=model)
    if result.get("error"):
        return result
    text = result.get("text", "").strip()
    if not text:
        return {"error": "AI 未返回全局解读"}
    return {"status": "ok", "insight": text}
