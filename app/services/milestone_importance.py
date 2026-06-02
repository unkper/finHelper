"""时间线节点 AI 重要性评分（DeepSeek Flash + 主题内最新动态）。"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests
from flask import current_app

from app.services.investment import (
    fetch_milestone_by_id,
    save_milestone_importance_result,
    set_milestone_importance_pending,
)
from app.services.quotes import fetch_us_quotes
from app.services.settings import get_ai_article_model
from app.services.stock_history import fetch_daily_series

_SUMMARY_MAX = 400
_ARTICLE_LIMIT_AFTER = 8
_ARTICLE_LIMIT_FALLBACK = 3

_SCORING_PROMPT = """你是投资主题时间线评审助手。请根据下列「节点信息」与「事件后动态」，评估该已发生事件对投资主题的重要性。

评分标准（0–10，保留一位小数）：
- 9–10：主题逻辑的关键验证/转折，动态与事件高度一致且影响大
- 7–8：明显影响仓位或观点，有较充分事后证据
- 4–6：有一定参考价值但影响有限，或证据不充分
- 0–3：与主题关联弱、已被证伪或几乎无增量信息

要求：
1. 只依据上下文中提供的信息，禁止编造行情、财报或新闻
2. 若动态信息不足，给 4–6 分并在 rationale 中说明「证据不足」
3. 仅返回 JSON，不要 markdown

JSON 格式：
{{"importance_score": 7.5, "rationale": "不超过80字的中文理由"}}

上下文：
{context_json}
"""


def has_milestone_ai_configured() -> bool:
    return bool(current_app.config.get("DEEPSEEK_API_KEY", "").strip())


def clamp_importance_score(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(10.0, value)), 1)


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


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _price_on_or_before(series: List[Dict[str, Any]], target_date: str) -> Optional[float]:
    price = None
    for bar in series:
        bar_date = str(bar.get("date") or "")
        if bar_date and bar_date <= target_date:
            close = bar.get("close")
            if close is not None:
                price = float(close)
    return price


def _build_price_dynamics(theme_id: int, event_date: str) -> List[Dict[str, Any]]:
    from app.database import get_db

    db = get_db()
    assets = db.execute(
        "SELECT ticker, exchange FROM theme_assets WHERE theme_id = ? ORDER BY ticker",
        (theme_id,),
    ).fetchall()
    us_tickers = [row["ticker"].upper() for row in assets if row["exchange"] == "US"]
    quotes = fetch_us_quotes(us_tickers) if us_tickers else {}

    result: List[Dict[str, Any]] = []
    for row in assets:
        ticker = row["ticker"].upper()
        entry: Dict[str, Any] = {"ticker": ticker, "exchange": row["exchange"]}
        if row["exchange"] != "US":
            entry["note"] = "非美股，暂无自动涨跌幅"
            result.append(entry)
            continue
        series = fetch_daily_series(ticker, use_cache=True)
        event_price = _price_on_or_before(series, event_date) if series else None
        latest_price = quotes.get(ticker)
        if latest_price is None and series:
            latest_price = series[-1].get("close")
        entry["price_at_event"] = round(event_price, 2) if event_price is not None else None
        entry["latest_price"] = round(float(latest_price), 2) if latest_price is not None else None
        if event_price and latest_price and event_price != 0:
            entry["change_pct"] = round((float(latest_price) - event_price) / event_price * 100, 2)
        result.append(entry)
    return result


def build_scoring_context(theme_id: int, milestone_id: int) -> Dict[str, Any] | None:
    from app.database import get_db

    milestone = fetch_milestone_by_id(theme_id, milestone_id)
    if not milestone:
        return None

    db = get_db()
    theme = db.execute(
        "SELECT id, title, description FROM themes WHERE id = ?",
        (theme_id,),
    ).fetchone()
    if not theme:
        return None

    event_date = milestone["event_date"]
    articles_after = db.execute(
        """
        SELECT title, summary, created_at FROM theme_articles
        WHERE theme_id = ? AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (theme_id, event_date, _ARTICLE_LIMIT_AFTER),
    ).fetchall()

    articles_payload: List[Dict[str, str]] = []
    for row in articles_after:
        articles_payload.append({
            "title": row["title"],
            "created_at": row["created_at"],
            "summary": _truncate(row["summary"] or "", _SUMMARY_MAX),
        })

    if not articles_payload:
        fallback = db.execute(
            """
            SELECT title, summary, created_at FROM theme_articles
            WHERE theme_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (theme_id, _ARTICLE_LIMIT_FALLBACK),
        ).fetchall()
        for row in fallback:
            articles_payload.append({
                "title": row["title"],
                "created_at": row["created_at"],
                "summary": _truncate(row["summary"] or "", _SUMMARY_MAX),
                "note": "事件前/背景资讯",
            })

    today = date.today().isoformat()
    try:
        ev = date.fromisoformat(event_date)
        days_since = (date.today() - ev).days
    except ValueError:
        days_since = None

    return {
        "theme": {
            "title": theme["title"],
            "description": _truncate(theme["description"] or "", 500),
        },
        "milestone": {
            "description": milestone["description"],
            "event_date": event_date,
            "end_date": milestone.get("end_date") or event_date,
            "is_completed": bool(milestone.get("is_completed")),
            "days_since_event": days_since,
        },
        "articles": articles_payload,
        "price_dynamics": _build_price_dynamics(theme_id, event_date),
        "as_of": today,
    }


def score_milestone_importance(theme_id: int, milestone_id: int) -> Dict[str, Any]:
    if not has_milestone_ai_configured():
        save_milestone_importance_result(
            theme_id,
            milestone_id,
            score=None,
            rationale=None,
            status="failed",
            error="未配置 DEEPSEEK_API_KEY",
        )
        return {"error": "未配置 DEEPSEEK_API_KEY"}

    milestone = fetch_milestone_by_id(theme_id, milestone_id)
    if not milestone:
        return {"error": "节点不存在"}
    if not milestone.get("is_completed"):
        return {"error": "仅对已发生节点评分"}

    context = build_scoring_context(theme_id, milestone_id)
    if not context:
        return {"error": "无法构建评分上下文"}

    prompt = _SCORING_PROMPT.format(
        context_json=json.dumps(context, ensure_ascii=False, indent=2),
    )

    api_key = current_app.config.get("DEEPSEEK_API_KEY", "").strip()
    base_url = current_app.config.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = get_ai_article_model()
    proxies = None
    api_proxy = current_app.config.get("API_PROXY")
    if api_proxy:
        proxies = {"http": api_proxy, "https": api_proxy}

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            proxies=proxies,
            timeout=90,
        )
    except requests.RequestException as exc:
        save_milestone_importance_result(
            theme_id,
            milestone_id,
            score=None,
            rationale=None,
            status="failed",
            error=str(exc),
        )
        return {"error": f"AI 服务调用失败：{exc}"}

    try:
        body = response.json()
    except ValueError:
        save_milestone_importance_result(
            theme_id,
            milestone_id,
            score=None,
            rationale=None,
            status="failed",
            error="响应不是有效 JSON",
        )
        return {"error": "AI 响应无效"}

    if response.status_code != 200:
        message = ""
        if isinstance(body.get("error"), dict):
            message = body["error"].get("message") or ""
        save_milestone_importance_result(
            theme_id,
            milestone_id,
            score=None,
            rationale=None,
            status="failed",
            error=message or f"HTTP {response.status_code}",
        )
        return {"error": message or "AI 评分失败"}

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        save_milestone_importance_result(
            theme_id,
            milestone_id,
            score=None,
            rationale=None,
            status="failed",
            error="AI 返回格式异常",
        )
        return {"error": "AI 返回格式异常"}

    try:
        parsed = json.loads(_extract_json_text(content))
    except json.JSONDecodeError:
        save_milestone_importance_result(
            theme_id,
            milestone_id,
            score=None,
            rationale=None,
            status="failed",
            error="AI 返回不是有效 JSON",
        )
        return {"error": "AI 返回不是有效 JSON"}

    score = clamp_importance_score(parsed.get("importance_score"))
    rationale = str(parsed.get("rationale") or "").strip()
    if score is None:
        save_milestone_importance_result(
            theme_id,
            milestone_id,
            score=None,
            rationale=None,
            status="failed",
            error="未解析到有效分数",
        )
        return {"error": "未解析到有效分数"}

    save_milestone_importance_result(
        theme_id,
        milestone_id,
        score=score,
        rationale=rationale,
        status="done",
    )
    return {
        "status": "ok",
        "importance_score": score,
        "importance_rationale": rationale,
        "importance_status": "done",
    }


def run_milestone_importance_job(app, theme_id: int, milestone_id: int) -> None:
    def _worker():
        with app.app_context():
            score_milestone_importance(theme_id, milestone_id)

    threading.Thread(target=_worker, daemon=True).start()


def serialize_milestone_importance(row: dict) -> Dict[str, Any]:
    return {
        "importance_score": row.get("importance_score"),
        "importance_rationale": row.get("importance_rationale"),
        "importance_scored_at": row.get("importance_scored_at"),
        "importance_status": row.get("importance_status") or "idle",
        "importance_error": row.get("importance_error"),
    }
