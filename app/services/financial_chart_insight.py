"""各图表 DeepSeek Flash 解读。"""
import json
from typing import Any, Dict

from app.services.financial_ai import CHART_INSIGHT_MODEL, chat_completion_text

CHART_TYPES = frozenset({
    "kpi", "waterfall", "margin_trend", "balance", "cashflow", "profit_ocf",
})

_CHART_LABELS = {
    "kpi": "核心 KPI 概览",
    "waterfall": "利润结构瀑布图",
    "margin_trend": "盈利能力趋势",
    "balance": "资产负债结构",
    "cashflow": "现金流量对比",
    "profit_ocf": "净利润与经营现金流",
}


def _slice_context(chart_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    period = payload.get("focus_period")
    ticker = payload.get("ticker")
    unit = payload.get("unit")

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
            "periods": payload.get("periods"),
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
        periods = payload.get("periods") or []
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
    return {"ticker": ticker, "period": period}


def explain_chart(chart_type: str, chart_payload: Dict[str, Any]) -> Dict[str, Any]:
    if chart_type not in CHART_TYPES:
        return {"error": f"不支持的图表类型: {chart_type}"}

    label = _CHART_LABELS.get(chart_type, chart_type)
    context = _slice_context(chart_type, chart_payload)
    linked = chart_payload.get("report_count", 1)
    linked_hint = ""
    if linked and linked > 1:
        linked_hint = f"数据已合并该标的 {linked} 份报告（财季：{', '.join(chart_payload.get('linked_periods') or [])}）。"

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
