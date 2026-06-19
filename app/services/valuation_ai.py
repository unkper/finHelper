"""估值 DCF 参数 AI 推荐（DeepSeek Flash）。"""
import json
import re
from typing import Any, Dict, Optional

from app.services.financial_ai import CHART_INSIGHT_MODEL, chat_completion_messages, has_financial_ai_configured
from app.services.financial_qa import build_report_qa_context
from app.services.financial_reports import fetch_report_by_id, fetch_report_extracted
from app.services.financial_statements import build_chart_payload
from app.services.financial_valuation import build_valuation_payload, get_valuation_override
from app.services.market_stats import fetch_us_market_stats

_PARAM_BOUNDS = {
    "wacc": (6.0, 25.0),
    "optimistic_factor": (1.0, 2.0),
    "pessimistic_factor": (0.3, 1.0),
    "terminal_growth_optimistic": (1.0, 5.0),
    "terminal_growth_base": (1.0, 5.0),
    "terminal_growth_pessimistic": (0.5, 4.0),
}


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _clamp(name: str, value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    lo, hi = _PARAM_BOUNDS[name]
    return round(max(lo, min(hi, num)), 2)


def recommend_valuation_params(report_id: int) -> Dict[str, Any]:
    if not has_financial_ai_configured():
        return {"error": "未配置 DEEPSEEK_API_KEY"}

    report = fetch_report_by_id(report_id)
    if not report:
        return {"error": "报告不存在"}
    if not report.get("has_analysis"):
        return {"error": "请先完成 AI 分析后再推荐参数"}

    context = build_report_qa_context(report_id)
    if not context:
        return {"error": "暂无可用于推荐的报告数据"}

    extracted = fetch_report_extracted(report_id)
    chart_payload = build_chart_payload(
        report["ticker"],
        report.get("fiscal_period"),
        current_report_id=report_id,
        current_extracted=extracted,
    )
    override = get_valuation_override(report_id)
    market_stats = fetch_us_market_stats([report["ticker"]]).get(
        (report.get("ticker") or "").upper(), {}
    )
    valuation = build_valuation_payload(
        report["ticker"],
        chart_payload,
        market_stats,
        override,
    )

    prompt = f"""你是科技公司估值助手。根据下列财报与市场数据，为 DCF 三情景模型推荐合理参数。
要求：
1. 结合盈利阶段（盈利/投入期）、增速、PS/PE/PEG、风险提示与业务特征
2. 科技公司 WACC 通常 8–18%，高成长未盈利可偏高；永续增长保守
3. 仅返回 JSON 对象，不要 markdown，字段：
   wacc, optimistic_factor, pessimistic_factor,
   terminal_growth_optimistic, terminal_growth_base, terminal_growth_pessimistic,
   rationale（2-4 句中文理由）

报告与估值上下文：
{json.dumps({**context, "valuation": valuation}, ensure_ascii=False, indent=2)}"""

    result = chat_completion_messages(
        [{"role": "user", "content": prompt}],
        model=CHART_INSIGHT_MODEL,
    )
    if result.get("error"):
        return result

    try:
        raw = _extract_json_object(result.get("text") or "")
    except (json.JSONDecodeError, TypeError):
        return {"error": "AI 返回格式无法解析"}

    if not isinstance(raw, dict):
        return {"error": "AI 返回格式异常"}

    params: Dict[str, Any] = {}
    for key in _PARAM_BOUNDS:
        clamped = _clamp(key, raw.get(key))
        if clamped is None:
            return {"error": f"AI 未返回有效参数：{key}"}
        params[key] = clamped

    rationale = str(raw.get("rationale") or "").strip()
    if not rationale:
        rationale = "已根据当前财报阶段与估值倍数生成参数建议。"

    return {
        "params": params,
        "rationale": rationale,
    }
