"""财报叙事层：投研 / 游戏风格，按需生成并缓存于 extracted_json.narratives。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.services.financial_ai import CHART_INSIGHT_MODEL, chat_completion_text, _extract_json_text
from app.services.financial_chart_insight import build_dashboard_context
from app.services.financial_game_rules import build_game_rules, infer_boss_threat, threat_to_hp_bars
from app.services.settings import get_ai_financial_parse_model

NARRATIVE_STYLES = frozenset({"professional", "game"})
_FOOTNOTE_PRO = "数据来自已确认财报字段，不构成投资建议。"
_FOOTNOTE_GAME = "战报数据来自已确认财报字段，不构成投资建议。"


def get_cached_narrative(extracted: Dict[str, Any] | None, style: str) -> Dict[str, Any] | None:
    if not extracted or style not in NARRATIVE_STYLES:
        return None
    narratives = extracted.get("narratives")
    if not isinstance(narratives, dict):
        return None
    cached = narratives.get(style)
    return cached if isinstance(cached, dict) else None


def _parse_narrative_json(raw: str, style: str) -> Dict[str, Any] | None:
    try:
        data = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    data["style"] = style
    return data


def _normalize_professional(data: Dict[str, Any], chart_payload: Dict[str, Any]) -> Dict[str, Any]:
    bullets = data.get("bullets")
    if not isinstance(bullets, list):
        bullets = []
    bullets = [str(b).strip() for b in bullets if str(b).strip()][:5]

    risk_cards = []
    for item in data.get("risk_cards") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        one_liner = str(item.get("one_liner") or item.get("message") or "").strip()
        if not title and not one_liner:
            continue
        sev = str(item.get("severity") or "medium").lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        risk_cards.append({
            "title": title or one_liner[:60],
            "one_liner": one_liner or title,
            "severity": sev,
        })

    if not risk_cards:
        for flag in chart_payload.get("red_flags") or []:
            if not isinstance(flag, dict):
                continue
            msg = str(flag.get("message") or "").strip()
            if msg:
                risk_cards.append({
                    "title": msg[:60],
                    "one_liner": msg,
                    "severity": infer_boss_threat(msg, str(flag.get("code") or "")),
                })

    headline = str(data.get("headline") or "").strip()
    if not headline:
        headline = str(chart_payload.get("ai_summary") or "")[:80]

    return {
        "style": "professional",
        "headline": headline,
        "bullets": bullets,
        "risk_cards": risk_cards[:12],
        "footnote": str(data.get("footnote") or _FOOTNOTE_PRO),
    }


def _merge_boss_encounters(
    ai_bosses: List[Any],
    rules: Dict[str, Any],
) -> List[Dict[str, Any]]:
    defaults = rules.get("boss_defaults") or []
    result: List[Dict[str, Any]] = []
    for i, default in enumerate(defaults):
        ai_item = ai_bosses[i] if i < len(ai_bosses) and isinstance(ai_bosses[i], dict) else {}
        threat = default.get("threat") or "medium"
        if str(ai_item.get("threat") or "").lower() in ("high", "medium", "low"):
            threat = str(ai_item["threat"]).lower()
        return_item = {
            "boss_name": str(ai_item.get("boss_name") or default.get("boss_name") or "未知 BOSS").strip(),
            "threat": threat,
            "hp_bars": threat_to_hp_bars(threat),
            "attack_pattern": str(ai_item.get("attack_pattern") or "").strip(),
            "counter_tip": str(ai_item.get("counter_tip") or "").strip(),
        }
        result.append(return_item)
    return result


def _normalize_game(
    data: Dict[str, Any],
    chart_payload: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    patch_notes = data.get("patch_notes")
    if not isinstance(patch_notes, list):
        patch_notes = data.get("bullets") if isinstance(data.get("bullets"), list) else []
    patch_notes = [str(p).strip() for p in patch_notes if str(p).strip()][:5]

    stat_flavors = data.get("stat_flavors")
    if not isinstance(stat_flavors, dict):
        stat_flavors = {}

    quests = []
    for q in data.get("quests") or []:
        if not isinstance(q, dict):
            continue
        title = str(q.get("quest_title") or q.get("title") or "").strip()
        objective = str(q.get("objective") or q.get("description") or "").strip()
        if not title:
            continue
        qtype = str(q.get("quest_type") or "reward").lower()
        if qtype not in ("reward", "penalty"):
            qtype = "reward"
        quests.append({
            "quest_title": title,
            "quest_type": qtype,
            "objective": objective,
        })

    boss_encounters = _merge_boss_encounters(
        data.get("boss_encounters") if isinstance(data.get("boss_encounters"), list) else [],
        rules,
    )

    verdict = rules.get("run_verdict") or "stalemate"

    return {
        "style": "game",
        "guild_title": str(data.get("guild_title") or f"{chart_payload.get('ticker') or ''} 公会").strip(),
        "run_headline": str(data.get("run_headline") or "").strip()[:80],
        "run_verdict": verdict,
        "hp_pct": rules.get("hp_pct", 50),
        "patch_notes": patch_notes,
        "stat_flavors": {str(k): str(v)[:40] for k, v in stat_flavors.items()},
        "boss_encounters": boss_encounters,
        "quests": quests[:8],
        "footnote": str(data.get("footnote") or _FOOTNOTE_GAME),
        "game_rules": {
            "stats": rules.get("stats") or [],
            "focus_period": rules.get("focus_period"),
        },
    }


def build_professional_fallback(chart_payload: Dict[str, Any], ai_summary: str = "") -> Dict[str, Any]:
    summary = (ai_summary or chart_payload.get("ai_summary") or "").strip()
    bullets = []
    for part in re.split(r"[。；\n]+", summary):
        part = part.strip()
        if part and len(bullets) < 3:
            bullets.append(part)

    risk_cards = []
    for flag in chart_payload.get("red_flags") or []:
        if not isinstance(flag, dict):
            continue
        msg = str(flag.get("message") or "").strip()
        if msg:
            risk_cards.append({
                "title": msg[:60],
                "one_liner": msg,
                "severity": infer_boss_threat(msg, str(flag.get("code") or "")),
            })

    return {
        "style": "professional",
        "headline": summary[:80] if summary else "财报摘要",
        "bullets": bullets,
        "risk_cards": risk_cards,
        "footnote": _FOOTNOTE_PRO,
    }


def _prompt_professional(context: Dict[str, Any]) -> str:
    return f"""你是财务分析助手。根据以下财报仪表盘数据，输出 JSON（不要 markdown）：
{{
  "headline": "一句话结论（≤50字）",
  "bullets": ["要点1", "要点2", "要点3"],
  "risk_cards": [{{"title": "风险简称", "one_liner": "一句话", "severity": "high|medium|low"}}],
  "footnote": "{_FOOTNOTE_PRO}"
}}
要求：禁止编造数据中没有的数字；risk_cards 须覆盖 red_flags 要点；仅返回 JSON。

数据：
{json.dumps(context, ensure_ascii=False, indent=2)}"""


def _prompt_game(context: Dict[str, Any], rules: Dict[str, Any]) -> str:
    return f"""你是 RPG 财报攻略写手。根据以下数据输出 JSON（不要 markdown）：
{{
  "guild_title": "公会/阵营名（如：云数据公会）",
  "run_headline": "本局战报一句（≤50字）",
  "patch_notes": ["版本更新要点1", "要点2", "要点3"],
  "stat_flavors": {{"revenue": "≤20字风味", "net_profit": "..."}},
  "boss_encounters": [
    {{"boss_name": "BOSS名", "attack_pattern": "攻击模式描述", "counter_tip": "应对提示"}}
  ],
  "quests": [
    {{"quest_title": "支线名", "quest_type": "reward|penalty", "objective": "目标描述"}}
  ],
  "footnote": "{_FOOTNOTE_GAME}"
}}
约束：
- 使用 RPG/BOSS/支线/版本更新隐喻，语气像游戏攻略，但不要低俗或预测股价
- 禁止编造 context 中没有的数字
- boss_encounters 条数必须等于 game_rules.boss_defaults 条数，顺序对应，threat/hp 由系统填充勿写
- quests 来自 material_events（profit→reward，loss→penalty），无则 []
- 不要输出 run_verdict（系统根据 KPI 计算）

context：
{json.dumps(context, ensure_ascii=False, indent=2)}

game_rules：
{json.dumps(rules, ensure_ascii=False, indent=2)}"""


def generate_narrative(
    chart_payload: Dict[str, Any],
    style: str,
    *,
    ai_summary: str = "",
) -> Dict[str, Any]:
    if style not in NARRATIVE_STYLES:
        return {"error": f"不支持的风格: {style}"}

    if style == "professional":
        cached_like = build_professional_fallback(chart_payload, ai_summary)
        if not chart_payload.get("periods"):
            return {"status": "ok", "narrative": cached_like, "cached": False}

    rules = build_game_rules(chart_payload)
    context = build_dashboard_context(chart_payload)
    context["game_rules"] = rules
    context["ai_summary"] = ai_summary or chart_payload.get("ai_summary") or ""

    if style == "professional":
        prompt = _prompt_professional(context)
        model = get_ai_financial_parse_model()
    else:
        prompt = _prompt_game(context, rules)
        model = CHART_INSIGHT_MODEL

    result = chat_completion_text(prompt, model=model)
    if result.get("error"):
        if style == "professional":
            return {"status": "ok", "narrative": build_professional_fallback(chart_payload, ai_summary)}
        return result

    parsed = _parse_narrative_json(result.get("text") or "", style)
    if not parsed:
        if style == "professional":
            return {"status": "ok", "narrative": build_professional_fallback(chart_payload, ai_summary)}
        return {"error": "AI 返回叙事 JSON 无效"}

    if style == "professional":
        narrative = _normalize_professional(parsed, chart_payload)
    else:
        narrative = _normalize_game(parsed, chart_payload, rules)

    return {"status": "ok", "narrative": narrative, "game_rules": rules}


def merge_narrative_into_extracted(
    extracted: Dict[str, Any],
    style: str,
    narrative: Dict[str, Any],
) -> Dict[str, Any]:
    out = dict(extracted)
    narratives = out.get("narratives")
    if not isinstance(narratives, dict):
        narratives = {}
    else:
        narratives = dict(narratives)
    narratives[style] = narrative
    out["narratives"] = narratives
    return out
