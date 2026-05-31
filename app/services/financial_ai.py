"""从粘贴的财报解读文字中抽取结构化财务数据（DeepSeek API）。"""
import json
import re
from typing import Any, Dict, List, Optional

import requests
from flask import current_app

from app.services.financial_period import normalize_fiscal_period
from app.services.financial_statements import _sort_periods
from app.services.settings import get_ai_article_model, get_ai_financial_parse_model  # noqa: F401

CHART_INSIGHT_MODEL = "deepseek-v4-flash"

_EXTRACTION_PROMPT = """你是一名资深财务分析助手。请从以下财报解读/分析文字中，抽取可用于图表展示的结构化财务数据。

要求：
1. 只抽取文中明确出现的数字，禁止编造；缺失字段用 null
2. 金额单位统一为百万美元（millions），在 JSON 顶层标明 unit: "millions"、currency: "USD"
3. 区分净利润 net_profit 与扣非净利润 net_profit_adjusted；文中无扣非则 net_profit_adjusted 为 null
4. periods 及所有表对象的键必须使用标准财季格式 YYYY-Q1～Q4（如 2025-Q4、2026-Q1），禁止 FY2025、纯年份等其它写法
5. 每个 period 在 kpis、income_statement、balance_sheet、cash_flow 下各有对应对象
6. income_statement 字段：revenue, cogs, gross_profit, rd, sga, operating_income, tax, net_income（均为百万美元，缺失 null）
7. balance_sheet 字段：cash, receivables, inventory, ppe, total_assets, current_liabilities, long_term_debt, equity
8. cash_flow 字段：operating, investing, financing（正负均可）
9. kpis 字段：revenue/net_profit/net_profit_adjusted 为 {{"value": 数, "yoy_pct": 数或null, "qoq_pct": 数或null}}；gross_margin_pct、roe_pct 为百分数
10. red_flags：基于文中可推断的风险点，数组 {{code, message}}，无则 []
11. ai_summary：3-5 句白话「公司体检报告」
12. 仅返回 JSON，不要 markdown 代码块

JSON 格式：
{{
  "currency": "USD",
  "unit": "millions",
  "periods": ["2026-Q1"],
  "kpis": {{ "2026-Q1": {{ ... }} }},
  "income_statement": {{ "2026-Q1": {{ ... }} }},
  "balance_sheet": {{ "2026-Q1": {{ ... }} }},
  "cash_flow": {{ "2026-Q1": {{ ... }} }},
  "red_flags": [],
  "ai_summary": "..."
}}

标的：{ticker}
财季：{fiscal_period}
标题：{title}

正文：
{source_text}
"""


def has_financial_ai_configured() -> bool:
    return bool(current_app.config.get("DEEPSEEK_API_KEY", "").strip())


def _extract_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _to_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _normalize_kpi_metric(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        val = _to_float(raw)
        return {"value": val, "yoy_pct": None, "qoq_pct": None} if val is not None else None
    value = _to_float(raw.get("value"))
    if value is None:
        return None
    return {
        "value": round(value, 2),
        "yoy_pct": _to_float(raw.get("yoy_pct")),
        "qoq_pct": _to_float(raw.get("qoq_pct")),
    }


def _try_canonical_period(raw: Any) -> str | None:
    try:
        return normalize_fiscal_period(str(raw))
    except ValueError:
        return None


def _normalize_period_map(raw: Any, fields: List[str]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for period, block in raw.items():
        if not isinstance(block, dict):
            continue
        period_key = _try_canonical_period(period)
        if not period_key:
            continue
        normalized = {}
        for field in fields:
            val = _to_float(block.get(field))
            if val is not None:
                normalized[field] = round(val, 2)
        if normalized:
            if period_key in result:
                result[period_key].update(normalized)
            else:
                result[period_key] = normalized
    return result


def normalize_extracted_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    periods_raw = payload.get("periods")
    periods: List[str] = []
    if isinstance(periods_raw, list):
        for p in periods_raw:
            key = _try_canonical_period(p)
            if key and key not in periods:
                periods.append(key)

    kpis_raw = payload.get("kpis") if isinstance(payload.get("kpis"), dict) else {}
    kpis: Dict[str, Dict[str, Any]] = {}
    for period, block in kpis_raw.items():
        if not isinstance(block, dict):
            continue
        period_key = _try_canonical_period(period)
        if not period_key:
            continue
        entry: Dict[str, Any] = {}
        for metric in ("revenue", "net_profit", "net_profit_adjusted"):
            normalized = _normalize_kpi_metric(block.get(metric))
            if normalized:
                entry[metric] = normalized
        for pct_key in ("gross_margin_pct", "roe_pct"):
            pct = _to_float(block.get(pct_key))
            if pct is not None:
                entry[pct_key] = round(pct, 2)
        if entry:
            kpis[period_key] = entry
            if period_key not in periods:
                periods.append(period_key)

    income = _normalize_period_map(
        payload.get("income_statement"),
        ["revenue", "cogs", "gross_profit", "rd", "sga", "operating_income", "tax", "net_income"],
    )
    balance = _normalize_period_map(
        payload.get("balance_sheet"),
        [
            "cash", "receivables", "inventory", "ppe", "total_assets",
            "current_liabilities", "long_term_debt", "equity",
        ],
    )
    cash_flow = _normalize_period_map(
        payload.get("cash_flow"),
        ["operating", "investing", "financing"],
    )

    for period in income:
        if period not in periods:
            periods.append(period)

    red_flags = []
    if isinstance(payload.get("red_flags"), list):
        for item in payload["red_flags"]:
            if not isinstance(item, dict):
                continue
            message = str(item.get("message") or "").strip()
            if message:
                red_flags.append({
                    "code": str(item.get("code") or "custom").strip(),
                    "message": message,
                })

    return {
        "currency": str(payload.get("currency") or "USD").upper(),
        "unit": str(payload.get("unit") or "millions"),
        "periods": _sort_periods(periods),
        "kpis": kpis,
        "income_statement": income,
        "balance_sheet": balance,
        "cash_flow": cash_flow,
        "red_flags": red_flags,
        "ai_summary": str(payload.get("ai_summary") or "").strip(),
    }


def _call_deepseek_chat(prompt: str, model: str | None = None) -> Dict[str, Any]:
    api_key = current_app.config.get("DEEPSEEK_API_KEY", "").strip()
    base_url = current_app.config.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = model or get_ai_article_model()
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    if model == "deepseek-v4-pro":
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "medium"

    proxies = None
    api_proxy = current_app.config.get("API_PROXY")
    if api_proxy:
        proxies = {"http": api_proxy, "https": api_proxy}

    try:
        response = requests.post(url, headers=headers, json=payload, proxies=proxies, timeout=120)
    except requests.RequestException as exc:
        return {"error": f"AI 服务调用失败：{exc}"}

    try:
        body = response.json()
    except ValueError:
        return {"error": f"AI 分析失败（{response.status_code}）：响应不是有效 JSON"}

    if response.status_code != 200:
        message = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else body.get("message")
        return {"error": f"AI 分析失败（{response.status_code}）：{message or '未知错误'}"}

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"error": "AI 返回格式异常，无法解析"}

    return {"content": content}


def extract_from_financial_text(
    ticker: str,
    fiscal_period: str,
    title: str,
    source_text: str,
    *,
    model: str | None = None,
) -> Dict[str, Any]:
    if not has_financial_ai_configured():
        return {"error": "未配置 DEEPSEEK_API_KEY，请在 .env 中设置"}

    source_text = (source_text or "").strip()
    if not source_text:
        return {"error": "请先粘贴财报解读文字"}

    prompt = _EXTRACTION_PROMPT.format(
        ticker=(ticker or "").strip().upper(),
        fiscal_period=(fiscal_period or "").strip(),
        title=(title or "").strip() or "（无标题）",
        source_text=source_text,
    )

    use_model = model or get_ai_financial_parse_model()
    result = _call_deepseek_chat(prompt, model=use_model)
    if result.get("error"):
        return {"error": result["error"]}

    try:
        payload = json.loads(_extract_json_text(result["content"]))
    except json.JSONDecodeError:
        return {"error": "AI 返回内容不是有效 JSON，请稍后重试"}

    if not isinstance(payload, dict):
        return {"error": "AI 返回格式无效"}

    normalized = normalize_extracted_payload(payload)
    if not normalized.get("periods"):
        return {"error": "未能从文中识别有效财季数据，请检查粘贴内容"}

    return {
        "status": "ok",
        "extracted": normalized,
        "ai_summary": normalized.get("ai_summary") or "",
    }


def chat_completion_text(prompt: str, *, model: str) -> Dict[str, Any]:
    """通用短文本生成（如图表解读）。"""
    result = _call_deepseek_chat(prompt, model=model)
    if result.get("error"):
        return result
    return {"text": (result.get("content") or "").strip()}
