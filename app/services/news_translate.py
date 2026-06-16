"""财经新闻标题与摘要自动翻译为简体中文（DeepSeek Flash 批量翻译）。"""
import json
import re
from typing import Any, Dict, List

from app.services.financial_ai import (
    CHART_INSIGHT_MODEL,
    chat_completion_messages,
    has_financial_ai_configured,
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_SUMMARY_PROMPT_MAX_LEN = 240


def _cjk_ratio(text: str) -> float:
    text = (text or "").strip()
    if not text:
        return 1.0
    cjk_count = len(_CJK_RE.findall(text))
    return cjk_count / max(len(text), 1)


def needs_translation(text: str) -> bool:
    """中文占比偏低时视为需要翻译。"""
    return _cjk_ratio(text) < 0.25


def is_translation_available() -> bool:
    """是否已配置 DeepSeek，可用于新闻翻译。"""
    return has_financial_ai_configured()


def _truncate_for_prompt(text: str, max_len: int = _SUMMARY_PROMPT_MAX_LEN) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _extract_json_array(raw: str) -> List[Any]:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def translate_news_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将英文新闻标题与摘要译为简体中文；无 DeepSeek 或已是中文则原样返回。"""
    if not items or not has_financial_ai_configured():
        return items

    pending: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not needs_translation(title) and not needs_translation(summary):
            continue
        pending.append({
            "index": index,
            "title": title,
            "summary": _truncate_for_prompt(summary),
        })

    if not pending:
        return items

    prompt = f"""你是财经新闻翻译助手。将下列英文新闻标题与摘要译为简体中文。
要求：
1. 保留公司名、股票代码、数字与专有名词的准确性
2. 语言简洁通顺，符合中文财经报道习惯
3. 仅返回 JSON 数组，每项含 index（原序号）、title、summary 字段，不要 markdown

待翻译：
{json.dumps(pending, ensure_ascii=False, indent=2)}"""

    result = chat_completion_messages(
        [{"role": "user", "content": prompt}],
        model=CHART_INSIGHT_MODEL,
    )
    if result.get("error"):
        return items

    try:
        translated_rows = _extract_json_array(result.get("text") or "")
    except (json.JSONDecodeError, TypeError):
        return items

    if not isinstance(translated_rows, list):
        return items

    merged = [dict(item) for item in items]
    for row in translated_rows:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(merged):
            continue
        title = str(row.get("title") or "").strip()
        summary = str(row.get("summary") or "").strip()
        if title:
            merged[index]["title"] = title
        if summary:
            merged[index]["summary"] = summary
        merged[index]["translated"] = True

    return merged
