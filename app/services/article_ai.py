"""从研报摘要中提取监控标的与关键时间线（DeepSeek API）。"""
import json
import re
from datetime import date
from typing import Any, Dict, List, Optional

import requests
from flask import current_app

from app.services.quotes import fetch_us_quotes
from app.services.api_usage import record_api_call
from app.services.settings import get_ai_article_model

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")

_EXTRACTION_PROMPT = """你是一名资深美股投研助手。请从以下研报/资讯内容中，提取可用于投资跟踪的结构化信息。

当前日期：{current_date}（{current_date_cn}，当前年份 {current_year} 年）

要求：
1. 只提取文中明确提到或可合理推断的美股 ticker（如 NVDA、AAPL），无法确定的不要输出
2. 只提取有明确或相对明确日期的事件（如财报日、产品发布、政策会议），日期格式必须为 YYYY-MM-DD
3. 解析日期时以「当前日期」为基准：文中只写月日、未写年份时，默认补全为 {current_year} 年。例如「5月27日」「5/27」应输出 {current_year}-05-27；「5月27日至5月30日」同理补全起止年份。若原文已写明其他年份则以原文为准
4. 不要编造文中没有的信息；若某类信息不存在，对应数组留空
5. 若文中提到目标价、支撑位、阻力位、买入/卖出参考价等具体美元价位，写入 price_alerts；direction 规则：跌至/低于/跌破该价用 below，涨至/高于/突破该价用 above；无明确价位则 price_alerts 留空
6. 仅返回 JSON，不要 markdown 代码块或其它说明文字

JSON 格式：
{{
  "milestones": [
    {{
      "event_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD 或 null",
      "description": "事件简述",
      "reminder_time": "HH:MM，默认 12:00",
      "source_quote": "原文依据片段"
    }}
  ],
  "assets": [
    {{
      "ticker": "大写美股代码",
      "rationale": "为何值得关注",
      "source_quote": "原文依据片段",
      "price_alerts": [
        {{
          "target_price": 150.0,
          "direction": "below 或 above",
          "note": "如：研报支撑位 / 目标价"
        }}
      ]
    }}
  ]
}}

标题：{title}

正文摘要：
{summary}
"""

_SUMMARIZE_PROMPT = """你是一名资深美股投研助手。请将以下研报/资讯摘要精炼为便于快速阅读的归纳总结。

要求：
1. 使用中文，总长度约 150–400 字
2. 以 2–4 条要点呈现（每条以「- 」开头），突出核心观点、关键数据、重要日期、相关美股 ticker 与价位
3. 保留原文中的事实与数字，不编造、不臆测
4. 去掉冗余、重复与无关铺垫，语言简洁专业
5. 仅输出归纳正文，不要标题、前言或 markdown 代码块

标题：{title}

原文摘要：
{summary}
"""


def _build_extraction_prompt(title: str, summary: str) -> str:
    today = date.today()
    return _EXTRACTION_PROMPT.format(
        current_date=today.isoformat(),
        current_date_cn=f"{today.year}年{today.month}月{today.day}日",
        current_year=today.year,
        title=(title or "").strip() or "（无标题）",
        summary=(summary or "").strip(),
    )


def _build_summarize_prompt(title: str, summary: str) -> str:
    return _SUMMARIZE_PROMPT.format(
        title=(title or "").strip() or "（无标题）",
        summary=(summary or "").strip(),
    )


def has_article_ai_configured() -> bool:
    return bool(current_app.config.get("DEEPSEEK_API_KEY", "").strip())


def _normalize_reminder_time(raw: Any) -> str:
    value = str(raw or "12:00").strip()
    if _TIME_RE.match(value[:5] if len(value) >= 5 else value):
        return value[:5]
    return "12:00"


def _normalize_date(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value or value.lower() == "null":
        return None
    if _DATE_RE.match(value):
        return value
    return None


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


def _normalize_milestones(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        event_date = _normalize_date(item.get("event_date"))
        description = str(item.get("description") or "").strip()
        if not event_date or not description:
            continue
        end_date = _normalize_date(item.get("end_date")) or event_date
        if end_date < event_date:
            end_date = event_date
        result.append({
            "event_date": event_date,
            "end_date": end_date,
            "description": description,
            "reminder_time": _normalize_reminder_time(item.get("reminder_time")),
            "source_quote": str(item.get("source_quote") or "").strip(),
        })
    return result


def _normalize_price_alerts(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        price_raw = item.get("target_price")
        if price_raw is None:
            continue
        try:
            target_price = float(price_raw)
        except (TypeError, ValueError):
            continue
        if target_price <= 0:
            continue
        direction = str(item.get("direction") or "below").strip().lower()
        if direction not in ("below", "above"):
            direction = "below"
        note = str(item.get("note") or "").strip() or None
        result.append({
            "target_price": round(target_price, 2),
            "direction": direction,
            "note": note,
        })
    return result


def _normalize_assets(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").upper().strip()
        if not ticker or not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", ticker):
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        result.append({
            "ticker": ticker,
            "rationale": str(item.get("rationale") or "").strip(),
            "source_quote": str(item.get("source_quote") or "").strip(),
            "price_alerts": _normalize_price_alerts(item.get("price_alerts")),
        })
    return result


def _enrich_assets_with_quotes(assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """用统一行情链校验 ticker 并附加现价。"""
    if not assets:
        return assets
    tickers = [a["ticker"] for a in assets]
    quotes = fetch_us_quotes(tickers)
    for asset in assets:
        price = quotes.get(asset["ticker"])
        asset["validated"] = price is not None
        if price is not None:
            asset["current_price"] = round(price, 2)
    return assets


def _call_deepseek_chat(prompt: str) -> Dict[str, Any]:
    api_key = current_app.config.get("DEEPSEEK_API_KEY", "").strip()
    base_url = current_app.config.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = get_ai_article_model()
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

    record_api_call("deepseek")
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


def extract_from_article(title: str, summary: str) -> Dict[str, Any]:
    """调用 DeepSeek 从研报摘要提取 milestones 与 assets。"""
    if not has_article_ai_configured():
        return {"error": "未配置 DEEPSEEK_API_KEY，请在 .env 中设置"}

    prompt = _build_extraction_prompt(title, summary)

    result = _call_deepseek_chat(prompt)
    if result.get("error"):
        return {"error": result["error"]}

    try:
        payload = json.loads(_extract_json_text(result["content"]))
    except json.JSONDecodeError:
        return {"error": "AI 返回内容不是有效 JSON，请稍后重试"}

    milestones = _normalize_milestones(payload.get("milestones"))
    assets = _enrich_assets_with_quotes(_normalize_assets(payload.get("assets")))

    return {
        "status": "ok",
        "milestones": milestones,
        "assets": assets,
    }


def summarize_article(title: str, summary: str) -> Dict[str, Any]:
    """调用 DeepSeek 将研报/资讯摘要精炼为结构化短摘要。"""
    if not has_article_ai_configured():
        return {"error": "未配置 DEEPSEEK_API_KEY，请在 .env 中设置"}

    text = (summary or "").strip()
    if not text:
        return {"error": "请先填写文章摘要后再进行 AI 归纳"}

    prompt = _build_summarize_prompt(title, text)
    result = _call_deepseek_chat(prompt)
    if result.get("error"):
        return {"error": result["error"]}

    refined = (result.get("content") or "").strip()
    if not refined:
        return {"error": "AI 未返回有效归纳内容，请稍后重试"}

    return {"summary": refined}
