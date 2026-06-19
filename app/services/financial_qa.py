"""财报详情页 AI 答疑：基于报告原文与结构化数据回答用户问题。"""
import json
from typing import Any, Dict, List

from app.services.financial_ai import CHART_INSIGHT_MODEL, chat_completion_messages, has_financial_ai_configured
from app.services.financial_chart_insight import build_dashboard_context
from app.services.financial_reports import fetch_report_by_id, fetch_report_extracted, get_report_source_text
from app.services.financial_statements import build_chart_payload
from app.services.financial_valuation import build_valuation_payload, get_valuation_override
from app.services.market_stats import fetch_us_market_stats

PRESET_QUESTIONS: List[Dict[str, str]] = [
    {
        "id": "fundamentals",
        "label": "公司基本面",
        "question": (
            "这家公司的基本面如何？请从营收与利润、毛利率与费用率、"
            "资产负债与现金流质量等方面，基于报告数据作出分析。"
        ),
    },
    {
        "id": "risks",
        "label": "风险与跟踪",
        "question": (
            "有哪些主要风险与后续应跟踪的事项？"
            "请结合风险提示、重大事项及财务数据说明。"
        ),
    },
    {
        "id": "valuation",
        "label": "估值是否合理",
        "question": (
            "结合当前 PS/PE/PEG 倍数、盈利阶段与 DCF 三情景结果，"
            "这家公司的估值是否合理？请说明主要支撑与风险。"
        ),
    },
]

_MAX_SOURCE_CHARS = 8000
_MAX_SESSION_MESSAGES = 6
_MAX_QUESTION_LEN = 2000

_SYSTEM_PROMPT = """你是财务分析助手。仅依据用户提供的「报告数据」回答，禁止编造数字或预测股价。
若问题超出数据范围，明确说明无法从现有报告中得出。用中文回答，结构清晰，可分点。"""


def get_preset_question(preset_id: str) -> str | None:
    preset_id = (preset_id or "").strip()
    for item in PRESET_QUESTIONS:
        if item["id"] == preset_id:
            return item["question"]
    return None


def _normalize_session_messages(raw: Any) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        return []
    messages: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def trim_session_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if len(messages) <= _MAX_SESSION_MESSAGES:
        return messages
    return messages[-_MAX_SESSION_MESSAGES:]


def build_report_qa_context(report_id: int) -> Dict[str, Any] | None:
    report = fetch_report_by_id(report_id)
    if not report:
        return None

    source_text = get_report_source_text(report_id)
    has_analysis = bool(report.get("has_analysis"))
    if not source_text and not has_analysis:
        return None

    context: Dict[str, Any] = {
        "ticker": report.get("ticker"),
        "fiscal_period": report.get("fiscal_period"),
        "title": report.get("title"),
    }
    if source_text:
        context["source_text_excerpt"] = source_text[:_MAX_SOURCE_CHARS]

    if has_analysis:
        extracted = fetch_report_extracted(report_id)
        if extracted:
            context["ai_summary"] = extracted.get("ai_summary") or report.get("ai_summary")
            context["red_flags"] = extracted.get("red_flags") or []
            context["material_events"] = extracted.get("material_events") or []
            chart_payload = build_chart_payload(
                report["ticker"],
                report.get("fiscal_period"),
                current_report_id=report_id,
                current_extracted=extracted,
            )
            if chart_payload.get("periods"):
                context["dashboard_data"] = build_dashboard_context(chart_payload)
                context["red_flags"] = chart_payload.get("red_flags") or context["red_flags"]
                context["material_events"] = chart_payload.get("material_events") or context["material_events"]
                override = get_valuation_override(report_id)
                market_stats = fetch_us_market_stats([report["ticker"]]).get(
                    (report.get("ticker") or "").upper(), {}
                )
                context["valuation"] = build_valuation_payload(
                    report["ticker"],
                    chart_payload,
                    market_stats,
                    override,
                )

    return context


def ask_report_question(
    report_id: int,
    question: str,
    session_messages: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    if not has_financial_ai_configured():
        return {"error": "未配置 DEEPSEEK_API_KEY"}

    question = (question or "").strip()
    if not question:
        return {"error": "请输入问题"}
    if len(question) > _MAX_QUESTION_LEN:
        return {"error": f"问题过长（最多 {_MAX_QUESTION_LEN} 字）"}

    context = build_report_qa_context(report_id)
    if not context:
        return {"error": "暂无可用于答疑的报告数据，请先粘贴原文或完成 AI 分析"}

    history = trim_session_messages(_normalize_session_messages(session_messages or []))
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": f"{_SYSTEM_PROMPT}\n\n【报告数据】\n{context_json}"},
        *history,
        {"role": "user", "content": question},
    ]

    result = chat_completion_messages(messages, model=CHART_INSIGHT_MODEL)
    if result.get("error"):
        return result
    text = (result.get("text") or "").strip()
    if not text:
        return {"error": "AI 未返回有效回答"}
    return {"answer": text}
