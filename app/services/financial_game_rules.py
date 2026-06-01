"""财报游戏化规则：由结构化 KPI 推导等级、HP、胜负（不依赖 AI 编造数字）。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_STAT_DEFS = (
    ("revenue", "进攻·营收", "revenue"),
    ("net_profit", "护盾·净利", "net_profit"),
    ("operating_cf", "续航·经营现金流", None),
    ("nrr_pct", "留存·NRR", "nrr_pct"),
    ("free_cash_flow", "续航·自由现金流", "free_cash_flow"),
    ("rpo", "任务池·RPO", "rpo"),
)

_HIGH_THREAT_KEYWORDS = re.compile(
    r"诉讼|破产|违约|重大|material|substantial|依赖.*(?:单一|唯一)|aws|持续亏损",
    re.IGNORECASE,
)
_MEDIUM_THREAT_KEYWORDS = re.compile(
    r"风险|波动|竞争|稀释|可转债|网络安全|macro|宏观",
    re.IGNORECASE,
)


def _metric_value(metric: Any) -> Optional[float]:
    if metric is None:
        return None
    if isinstance(metric, dict):
        return metric.get("value")
    try:
        return float(metric)
    except (TypeError, ValueError):
        return None


def _metric_yoy(metric: Any) -> Optional[float]:
    if isinstance(metric, dict):
        return metric.get("yoy_pct")
    return None


def tier_from_yoy(yoy: Optional[float]) -> str:
    if yoy is None:
        return "B"
    if yoy >= 20:
        return "S"
    if yoy >= 10:
        return "A"
    if yoy >= 0:
        return "B"
    return "C"


def tier_from_nrr(nrr: Optional[float]) -> str:
    if nrr is None:
        return "B"
    if nrr >= 130:
        return "S"
    if nrr >= 120:
        return "A"
    if nrr >= 100:
        return "B"
    return "C"


def tier_from_net_profit(value: Optional[float], yoy: Optional[float]) -> str:
    if value is None:
        return "C"
    if value > 0:
        return tier_from_yoy(yoy) if yoy is not None else "A"
    return "C"


def tier_from_positive_amount(value: Optional[float]) -> str:
    if value is None:
        return "C"
    if value <= 0:
        return "C"
    if value >= 1000:
        return "S"
    if value >= 100:
        return "A"
    return "B"


def infer_boss_threat(message: str, code: str = "") -> str:
    text = f"{code} {message}"
    if _HIGH_THREAT_KEYWORDS.search(text):
        return "high"
    if _MEDIUM_THREAT_KEYWORDS.search(text):
        return "medium"
    return "low"


def threat_to_hp_bars(threat: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(threat, 2)


def compute_run_verdict(
    net_profit: Optional[float],
    revenue_yoy: Optional[float],
    operating_cf: Optional[float],
) -> str:
    score = 0
    if net_profit is not None:
        if net_profit > 0:
            score += 2
        elif net_profit < 0:
            score -= 2
    if revenue_yoy is not None:
        if revenue_yoy >= 15:
            score += 2
        elif revenue_yoy >= 0:
            score += 1
        else:
            score -= 1
    if operating_cf is not None:
        if operating_cf > 0:
            score += 1
        elif operating_cf < 0:
            score -= 1
    if score >= 3:
        return "winning"
    if score <= -2:
        return "losing"
    return "stalemate"


def compute_hp_pct(
    net_profit: Optional[float],
    operating_cf: Optional[float],
    revenue_yoy: Optional[float],
) -> int:
    base = 50
    if net_profit is not None:
        if net_profit > 0:
            base += 20
        else:
            base -= 25
    if operating_cf is not None:
        if operating_cf > 0:
            base += 15
        else:
            base -= 10
    if revenue_yoy is not None:
        if revenue_yoy >= 20:
            base += 10
        elif revenue_yoy < 0:
            base -= 10
    return max(5, min(95, base))


def _format_amount(value: Optional[float], unit: str) -> str:
    if value is None:
        return "—"
    suffix = " M" if unit == "millions" else ""
    return f"${value:,.1f}{suffix}".replace(".0", "")


def _format_delta(yoy: Optional[float], suffix: str = "") -> str:
    if yoy is None:
        return ""
    sign = "+" if yoy > 0 else ""
    return f"{sign}{yoy:g}%{suffix}"


def build_game_rules(chart_payload: Dict[str, Any]) -> Dict[str, Any]:
    focus = chart_payload.get("focus_period")
    unit = chart_payload.get("unit") or "millions"
    kpis_block = (chart_payload.get("kpis") or {}).get(focus) or {}
    income = (chart_payload.get("income_statement") or {}).get(focus) or {}
    cf_block = (chart_payload.get("cash_flow") or {}).get(focus) or {}

    revenue_metric = kpis_block.get("revenue")
    if revenue_metric is None and income.get("revenue") is not None:
        revenue_metric = {"value": income.get("revenue"), "yoy_pct": None}
    net_metric = kpis_block.get("net_profit")
    if net_metric is None and income.get("net_income") is not None:
        net_metric = {"value": income.get("net_income"), "yoy_pct": None}

    rev_val = _metric_value(revenue_metric)
    rev_yoy = _metric_yoy(revenue_metric)
    net_val = _metric_value(net_metric)
    net_yoy = _metric_yoy(net_metric)
    ocf = cf_block.get("operating")
    if ocf is None:
        ocf = _metric_value(kpis_block.get("operating_cf"))

    nrr = kpis_block.get("nrr_pct")
    if isinstance(nrr, dict):
        nrr = nrr.get("value")
    fcf = _metric_value(kpis_block.get("free_cash_flow"))
    rpo = _metric_value(kpis_block.get("rpo"))

    stats: List[Dict[str, Any]] = []

    if rev_val is not None or revenue_metric is not None:
        stats.append({
            "key": "revenue",
            "label": "进攻·营收",
            "value": _format_amount(rev_val, unit),
            "raw_value": rev_val,
            "delta": _format_delta(rev_yoy, " YoY"),
            "tier": tier_from_yoy(rev_yoy),
        })
    if net_val is not None or net_metric is not None:
        stats.append({
            "key": "net_profit",
            "label": "护盾·净利",
            "value": _format_amount(net_val, unit),
            "raw_value": net_val,
            "delta": _format_delta(net_yoy, " YoY"),
            "tier": tier_from_net_profit(net_val, net_yoy),
            "debuff": net_val is not None and net_val < 0,
        })
    if ocf is not None:
        stats.append({
            "key": "operating_cf",
            "label": "续航·经营现金流",
            "value": _format_amount(ocf, unit),
            "raw_value": ocf,
            "delta": "",
            "tier": tier_from_positive_amount(ocf),
        })
    if nrr is not None:
        stats.append({
            "key": "nrr_pct",
            "label": "留存·NRR",
            "value": f"{nrr:g}%",
            "raw_value": nrr,
            "delta": "",
            "tier": tier_from_nrr(float(nrr)),
        })
    if fcf is not None:
        stats.append({
            "key": "free_cash_flow",
            "label": "续航·自由现金流",
            "value": _format_amount(fcf, unit),
            "raw_value": fcf,
            "delta": "",
            "tier": tier_from_positive_amount(fcf),
        })
    if rpo is not None:
        stats.append({
            "key": "rpo",
            "label": "任务池·RPO",
            "value": _format_amount(rpo, unit),
            "raw_value": rpo,
            "delta": "",
            "tier": tier_from_positive_amount(rpo),
        })

    boss_defaults = []
    for flag in chart_payload.get("red_flags") or []:
        if not isinstance(flag, dict):
            continue
        msg = str(flag.get("message") or "").strip()
        if not msg:
            continue
        code = str(flag.get("code") or "")
        threat = infer_boss_threat(msg, code)
        boss_defaults.append({
            "boss_name": msg[:80] if len(msg) > 80 else msg,
            "threat": threat,
            "hp_bars": threat_to_hp_bars(threat),
            "source_message": msg,
        })

    return {
        "focus_period": focus,
        "fiscal_period_label": focus or "",
        "ticker": chart_payload.get("ticker"),
        "unit": unit,
        "run_verdict": compute_run_verdict(net_val, rev_yoy, ocf),
        "hp_pct": compute_hp_pct(net_val, ocf, rev_yoy),
        "stats": stats,
        "boss_defaults": boss_defaults,
    }
