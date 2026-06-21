"""投研估值：覆盖参数存储 + 基于财报与市场数据的估值计算。"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.database import get_db

DEFAULT_WACC = 12.0
DEFAULT_OPTIMISTIC_FACTOR = 1.3
DEFAULT_PESSIMISTIC_FACTOR = 0.6
DEFAULT_TERMINAL_GROWTH = {"optimistic": 4.0, "base": 3.0, "pessimistic": 2.0}


def get_valuation_override(report_id: int) -> Optional[Dict[str, Any]]:
    db = get_db()
    row = db.execute(
        """
        SELECT market_cap, shares_outstanding, dcf_params_json, updated_at
        FROM research_valuation_overrides
        WHERE report_id = ?
        """,
        (report_id,),
    ).fetchone()
    if not row:
        return None
    dcf_params = None
    if row["dcf_params_json"]:
        try:
            dcf_params = json.loads(row["dcf_params_json"])
        except (TypeError, json.JSONDecodeError):
            dcf_params = None
    return {
        "market_cap": row["market_cap"],
        "shares_outstanding": row["shares_outstanding"],
        "dcf_params": dcf_params if isinstance(dcf_params, dict) else {},
        "updated_at": row["updated_at"],
    }


def save_valuation_override(
    report_id: int,
    *,
    market_cap: float | None = None,
    shares_outstanding: float | None = None,
    clear_market_cap: bool = False,
    clear_shares: bool = False,
) -> None:
    existing = get_valuation_override(report_id) or {
        "market_cap": None,
        "shares_outstanding": None,
        "dcf_params": {},
    }
    cap = None if clear_market_cap else (
        market_cap if market_cap is not None else existing.get("market_cap")
    )
    shares = None if clear_shares else (
        shares_outstanding if shares_outstanding is not None else existing.get("shares_outstanding")
    )
    dcf_json = json.dumps(existing.get("dcf_params") or {}, ensure_ascii=False)
    db = get_db()
    db.execute(
        """
        INSERT INTO research_valuation_overrides
            (report_id, market_cap, shares_outstanding, dcf_params_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(report_id) DO UPDATE SET
            market_cap = excluded.market_cap,
            shares_outstanding = excluded.shares_outstanding,
            dcf_params_json = excluded.dcf_params_json,
            updated_at = excluded.updated_at
        """,
        (
            report_id,
            cap,
            shares,
            dcf_json,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    db.commit()


def save_valuation_dcf_params(report_id: int, dcf_params: Dict[str, Any]) -> None:
    existing = get_valuation_override(report_id) or {
        "market_cap": None,
        "shares_outstanding": None,
        "dcf_params": {},
    }
    merged = dict(existing.get("dcf_params") or {})
    for key in ("wacc", "optimistic_factor", "pessimistic_factor", "terminal_growth_optimistic", "terminal_growth_base", "terminal_growth_pessimistic"):
        if key in dcf_params and dcf_params[key] is not None:
            merged[key] = dcf_params[key]
    db = get_db()
    db.execute(
        """
        INSERT INTO research_valuation_overrides
            (report_id, market_cap, shares_outstanding, dcf_params_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(report_id) DO UPDATE SET
            dcf_params_json = excluded.dcf_params_json,
            updated_at = excluded.updated_at
        """,
        (
            report_id,
            existing.get("market_cap"),
            existing.get("shares_outstanding"),
            json.dumps(merged, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    db.commit()


def _sort_periods(periods: List[str]) -> List[str]:
    def sort_key(raw: str) -> tuple[int, int]:
        p = str(raw).strip().upper()
        try:
            year_s, q_s = p.split("-", 1)
            if q_s.startswith("Q") and len(q_s) == 2 and q_s[1].isdigit():
                return (int(year_s), int(q_s[1]))
        except (ValueError, AttributeError):
            pass
        return (999999, 99)

    cleaned = {str(x).strip() for x in periods if x is not None and str(x).strip()}
    return sorted(cleaned, key=sort_key)


def _revenue_for_period(
    period: str,
    income: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
) -> Optional[float]:
    inc = income.get(period) or {}
    rev = inc.get("revenue")
    if rev is not None:
        return float(rev)
    k = (kpis.get(period) or {}).get("revenue")
    if isinstance(k, dict) and k.get("value") is not None:
        return float(k["value"])
    return None


def _net_income_for_period(
    period: str,
    income: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
) -> Optional[float]:
    inc = income.get(period) or {}
    net = inc.get("net_income")
    if net is not None:
        return float(net)
    k = (kpis.get(period) or {}).get("net_profit")
    if isinstance(k, dict) and k.get("value") is not None:
        return float(k["value"])
    if isinstance(k, (int, float)):
        return float(k)
    return None


def _yoy_pct_for_period(period: str, kpis: Dict[str, Dict[str, Any]]) -> Optional[float]:
    block = kpis.get(period) or {}
    rev = block.get("revenue")
    if isinstance(rev, dict) and rev.get("yoy_pct") is not None:
        return float(rev["yoy_pct"])
    return None


def _compute_ttm(
    periods: List[str],
    income: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    sorted_periods = _sort_periods(periods)
    if not sorted_periods:
        return {
            "revenue_millions": None,
            "net_income_millions": None,
            "method": None,
            "periods_used": [],
        }

    use_periods = sorted_periods[-4:] if len(sorted_periods) >= 4 else [sorted_periods[-1]]
    rev_sum = 0.0
    net_sum = 0.0
    rev_count = 0
    net_count = 0
    for period in use_periods:
        rev = _revenue_for_period(period, income, kpis)
        net = _net_income_for_period(period, income, kpis)
        if rev is not None:
            rev_sum += rev
            rev_count += 1
        if net is not None:
            net_sum += net
            net_count += 1

    method = "sum_last_4q" if len(use_periods) >= 4 else "annualized_single_q"
    if method == "annualized_single_q" and rev_count:
        rev_sum *= 4
    if method == "annualized_single_q" and net_count:
        net_sum *= 4

    return {
        "revenue_millions": rev_sum if rev_count else None,
        "net_income_millions": net_sum if net_count else None,
        "method": method if rev_count or net_count else None,
        "periods_used": use_periods,
    }


def _growth_rate_pct(
    periods: List[str],
    income: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
    focus_period: str | None,
) -> Optional[float]:
    focus = focus_period or (_sort_periods(periods)[-1] if periods else None)
    if focus:
        yoy = _yoy_pct_for_period(focus, kpis)
        if yoy is not None:
            return yoy
    sorted_periods = _sort_periods(periods)
    if len(sorted_periods) < 2:
        return None
    prev = sorted_periods[-2]
    latest = sorted_periods[-1]
    prev_rev = _revenue_for_period(prev, income, kpis)
    latest_rev = _revenue_for_period(latest, income, kpis)
    if prev_rev and latest_rev and prev_rev != 0:
        return round((latest_rev - prev_rev) / prev_rev * 100, 2)
    return None


def _resolve_market(
    market_stats: Dict[str, Any] | None,
    override: Dict[str, Any] | None,
) -> Dict[str, Any]:
    stats = market_stats or {}
    override = override or {}
    price = stats.get("price")
    market_cap = override.get("market_cap")
    shares = override.get("shares_outstanding")
    source = "none"

    if market_cap is not None:
        source = "manual"
    elif stats.get("market_cap") is not None:
        market_cap = stats["market_cap"]
        source = stats.get("source") or "fmp"

    if shares is not None:
        if source == "none":
            source = "manual"
    elif stats.get("shares_outstanding") is not None:
        shares = stats["shares_outstanding"]

    if market_cap is None and price and shares:
        market_cap = price * shares
        if source in ("none", "quote"):
            source = "computed"

    if shares is None and market_cap and price and price > 0:
        shares = market_cap / price

    return {
        "price": price,
        "market_cap": market_cap,
        "shares": shares,
        "source": source,
        "pe": stats.get("pe"),
        "eps": stats.get("eps"),
    }


def _pe_g_label(peg: Optional[float]) -> Optional[str]:
    if peg is None:
        return None
    if peg < 1:
        return "偏便宜"
    if peg <= 2:
        return "合理"
    return "偏贵"


def _fcf_millions_ttm(
    periods_used: List[str],
    income: Dict[str, Dict[str, Any]],
    kpis: Dict[str, Dict[str, Any]],
    cash_flow: Dict[str, Dict[str, Any]],
    revenue_millions: Optional[float],
    net_income_millions: Optional[float],
) -> Tuple[Optional[float], bool]:
    fcf_sum = 0.0
    count = 0
    for period in periods_used:
        block = kpis.get(period) or {}
        fcf = block.get("free_cash_flow")
        if fcf is not None:
            fcf_sum += float(fcf)
            count += 1
            continue
        cf = (cash_flow.get(period) or {}).get("operating")
        if cf is not None:
            fcf_sum += float(cf) * 0.85
            count += 1
    if count:
        if len(periods_used) == 1 and count == 1:
            fcf_sum *= 4
        return fcf_sum, False
    if revenue_millions and net_income_millions is not None and net_income_millions > 0:
        margin = net_income_millions / revenue_millions
        return revenue_millions * margin * 0.85, True
    if revenue_millions:
        return revenue_millions * 0.05, True
    return None, True


def _dcf_scenario(
    fcf_usd: float,
    growth_pct: float,
    wacc_pct: float,
    terminal_growth_pct: float,
    shares: Optional[float],
) -> Dict[str, Any]:
    if wacc_pct <= terminal_growth_pct:
        return {
            "enterprise_value": None,
            "implied_price": None,
            "vs_current_price_pct": None,
        }
    fcf = fcf_usd
    pv = 0.0
    for _year in range(1, 6):
        fcf *= 1 + growth_pct / 100
        pv += fcf / ((1 + wacc_pct / 100) ** _year)
    terminal_fcf = fcf * (1 + terminal_growth_pct / 100)
    terminal_value = terminal_fcf / (wacc_pct / 100 - terminal_growth_pct / 100)
    pv += terminal_value / ((1 + wacc_pct / 100) ** 5)
    implied_price = pv / shares if shares else None
    return {
        "enterprise_value": round(pv, 2),
        "implied_price": round(implied_price, 4) if implied_price is not None else None,
        "vs_current_price_pct": None,
    }


def _build_dcf(
    fcf_millions: Optional[float],
    fcf_estimated: bool,
    base_growth: Optional[float],
    market: Dict[str, Any],
    dcf_params: Dict[str, Any],
) -> Dict[str, Any]:
    wacc = float(dcf_params.get("wacc") or DEFAULT_WACC)
    opt_factor = float(dcf_params.get("optimistic_factor") or DEFAULT_OPTIMISTIC_FACTOR)
    pes_factor = float(dcf_params.get("pessimistic_factor") or DEFAULT_PESSIMISTIC_FACTOR)
    terminal = {
        "optimistic": float(dcf_params.get("terminal_growth_optimistic") or DEFAULT_TERMINAL_GROWTH["optimistic"]),
        "base": float(dcf_params.get("terminal_growth_base") or DEFAULT_TERMINAL_GROWTH["base"]),
        "pessimistic": float(dcf_params.get("terminal_growth_pessimistic") or DEFAULT_TERMINAL_GROWTH["pessimistic"]),
    }
    base_growth = max(base_growth or 0.0, 0.0)
    scenario_defs = [
        ("optimistic", "乐观", base_growth * opt_factor, terminal["optimistic"]),
        ("base", "中性", base_growth, terminal["base"]),
        ("pessimistic", "悲观", base_growth * pes_factor, terminal["pessimistic"]),
    ]
    params = {
        "wacc": wacc,
        "optimistic_factor": opt_factor,
        "pessimistic_factor": pes_factor,
        "base_growth_pct": base_growth,
        "terminal_growth": terminal,
        "fcf_estimated": fcf_estimated,
    }
    if fcf_millions is None:
        return {"params": params, "scenarios": []}

    fcf_usd = fcf_millions * 1_000_000
    shares = market.get("shares")
    price = market.get("price")
    scenarios = []
    for key, label, growth, term_g in scenario_defs:
        row = _dcf_scenario(fcf_usd, growth, wacc, term_g, shares)
        row["name"] = key
        row["label"] = label
        row["growth_pct"] = round(growth, 2)
        row["terminal_growth_pct"] = term_g
        if row.get("implied_price") and price:
            row["vs_current_price_pct"] = round((row["implied_price"] / price - 1) * 100, 2)
        scenarios.append(row)
    return {"params": params, "scenarios": scenarios}


def _implied_price_at_wacc(
    fcf_usd: float,
    growth_pct: float,
    wacc_pct: float,
    terminal_growth_pct: float,
    shares: float,
) -> Optional[float]:
    row = _dcf_scenario(fcf_usd, growth_pct, wacc_pct, terminal_growth_pct, shares)
    return row.get("implied_price")


def solve_implied_wacc(
    fcf_usd: float,
    base_growth_pct: float,
    terminal_growth_pct: float,
    shares: float,
    target_price: float,
    *,
    low: float = 5.0,
    high: float = 35.0,
    tol: float = 0.01,
) -> Optional[float]:
    """中性情景下，使 DCF 隐含价等于 target_price 的 WACC（二分搜索）。"""
    if fcf_usd <= 0 or shares <= 0 or target_price <= 0:
        return None
    wacc_lo = max(low, terminal_growth_pct + 0.1)
    if wacc_lo >= high:
        return None

    price_lo = _implied_price_at_wacc(fcf_usd, base_growth_pct, wacc_lo, terminal_growth_pct, shares)
    price_hi = _implied_price_at_wacc(fcf_usd, base_growth_pct, high, terminal_growth_pct, shares)
    if price_lo is None or price_hi is None:
        return None
    if target_price > price_lo or target_price < price_hi:
        return None

    lo, hi = wacc_lo, high
    for _ in range(80):
        mid = (lo + hi) / 2
        price = _implied_price_at_wacc(fcf_usd, base_growth_pct, mid, terminal_growth_pct, shares)
        if price is None:
            return None
        if abs(price - target_price) / target_price < tol:
            return round(mid, 2)
        if price > target_price:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 2)


def _detect_fcf_source(
    periods_used: List[str],
    kpis: Dict[str, Dict[str, Any]],
    cash_flow: Dict[str, Dict[str, Any]],
    revenue_millions: Optional[float],
    net_income_millions: Optional[float],
) -> str:
    """返回 FCF 数据来源标识，便于缺失提示。"""
    for period in periods_used:
        block = kpis.get(period) or {}
        if block.get("free_cash_flow") is not None:
            return "free_cash_flow"
    for period in periods_used:
        cf = (cash_flow.get(period) or {}).get("operating")
        if cf is not None:
            return "operating_cf"
    if revenue_millions and net_income_millions is not None and net_income_millions > 0:
        return "net_margin_estimate"
    if revenue_millions:
        return "revenue_estimate"
    return "none"


def _build_data_gaps(
    *,
    periods: List[str],
    report_count: int,
    ttm: Dict[str, Any],
    revenue_m: Optional[float],
    net_income_m: Optional[float],
    growth_pct: Optional[float],
    market: Dict[str, Any],
    stage: str,
    primary_metric: str,
    multiples: Dict[str, Any],
    fcf_m: Optional[float],
    fcf_estimated: bool,
    fcf_source: str,
    dcf: Dict[str, Any],
    implied_wacc: Dict[str, Any],
) -> Dict[str, Any]:
    """列出估值所需数据的就绪状态与补全指引。"""
    items: List[Dict[str, Any]] = []
    periods_used = ttm.get("periods_used") or []
    period_count = len(_sort_periods(periods))
    ttm_method = ttm.get("method")

    if period_count >= 4:
        used_label = "、".join(periods_used[-4:])
        items.append({
            "id": "quarters",
            "label": "财报季度",
            "status": "ok",
            "detail": f"已合并 {period_count} 季，TTM 求和：{used_label}",
            "action": None,
        })
    elif period_count >= 1:
        used_label = "、".join(periods_used)
        need = 4 - period_count
        items.append({
            "id": "quarters",
            "label": "财报季度",
            "status": "partial",
            "detail": f"仅 {period_count} 季（{used_label}），TTM 按单季 ×4 年化",
            "action": f"同 ticker 下再补充 {need} 个及以上已 AI 分析财季，或一份报告提取多季数据",
        })
    else:
        items.append({
            "id": "quarters",
            "label": "财报季度",
            "status": "missing",
            "detail": "无有效财季",
            "action": "完成 AI 分析，确保 extracted 含 periods 与 income_statement",
        })

    if revenue_m is not None:
        method_note = "（单季×4）" if ttm_method == "annualized_single_q" else "（四季求和）"
        items.append({
            "id": "revenue_ttm",
            "label": "TTM 营收",
            "status": "partial" if ttm_method == "annualized_single_q" else "ok",
            "detail": f"约 {round(revenue_m, 2)} 百万 USD {method_note}",
            "action": None if period_count >= 4 else "补全更多季度以提高 TTM 准确度",
        })
    else:
        items.append({
            "id": "revenue_ttm",
            "label": "TTM 营收",
            "status": "missing",
            "detail": "财报中无 revenue",
            "action": "AI 分析需提取 income_statement 或 kpis.revenue",
        })

    if net_income_m is not None:
        items.append({
            "id": "net_income_ttm",
            "label": "TTM 净利润",
            "status": "ok" if net_income_m > 0 else "partial",
            "detail": f"约 {round(net_income_m, 2)} 百万 USD" + ("（亏损）" if net_income_m <= 0 else ""),
            "action": None if net_income_m > 0 else "盈利转正后可计算 PE/PEG",
        })
    else:
        items.append({
            "id": "net_income_ttm",
            "label": "TTM 净利润",
            "status": "partial" if stage == "pre_profit" else "missing",
            "detail": "未提取 net_income",
            "action": "投入期可暂缺；盈利期公司需 income_statement.net_income",
        })

    price = market.get("price")
    if price is not None:
        items.append({
            "id": "price",
            "label": "现价",
            "status": "ok",
            "detail": f"${round(float(price), 2)}（{market.get('source') or '行情'}）",
            "action": None,
        })
    else:
        items.append({
            "id": "price",
            "label": "现价",
            "status": "missing",
            "detail": "无行情价",
            "action": "配置 FMP_API_KEY（或 Alpha Vantage / EODHD 回退）",
        })

    market_cap = market.get("market_cap")
    if market_cap is not None:
        items.append({
            "id": "market_cap",
            "label": "市值",
            "status": "ok",
            "detail": fmt_usd_gap(market_cap),
            "action": None,
        })
    else:
        items.append({
            "id": "market_cap",
            "label": "市值",
            "status": "missing",
            "detail": "无市值",
            "action": "配置 FMP_API_KEY，或在下方表单手动填写市值",
        })

    shares = market.get("shares")
    if shares is not None:
        items.append({
            "id": "shares",
            "label": "总股本",
            "status": "ok",
            "detail": f"约 {round(float(shares) / 1e8, 2)} 亿股",
            "action": None,
        })
    else:
        items.append({
            "id": "shares",
            "label": "总股本",
            "status": "missing",
            "detail": "无股本",
            "action": "配置 FMP 拉取 shares_outstanding，或填市值+现价反推，或手动覆盖",
        })

    if growth_pct is not None:
        items.append({
            "id": "growth",
            "label": "营收增速",
            "status": "ok",
            "detail": f"{growth_pct}%（YoY 或环比）",
            "action": None,
        })
    else:
        items.append({
            "id": "growth",
            "label": "营收增速",
            "status": "missing",
            "detail": "无法计算增速",
            "action": "提取 kpis.revenue.yoy_pct，或至少两期营收做环比",
        })

    if primary_metric == "PS":
        if multiples.get("ps") is not None:
            items.append({
                "id": "ps",
                "label": "PS（主指标）",
                "status": "ok",
                "detail": f"{multiples['ps']}x",
                "action": None,
            })
        else:
            items.append({
                "id": "ps",
                "label": "PS（主指标）",
                "status": "missing",
                "detail": "缺少市值或 TTM 营收",
                "action": "补全市值与营收后可算 PS",
            })
    elif primary_metric == "PE":
        if multiples.get("pe") is not None:
            items.append({
                "id": "pe",
                "label": "PE（主指标）",
                "status": "ok",
                "detail": f"{multiples['pe']}x",
                "action": None,
            })
        else:
            items.append({
                "id": "pe",
                "label": "PE（主指标）",
                "status": "missing",
                "detail": "缺少市值或 TTM 净利润",
                "action": "补全市值与盈利数据后可算 PE/PEG",
            })

    if fcf_m is None:
        source_hint = {
            "none": "财报无 free_cash_flow、经营现金流，且无营收可估算",
        }.get(fcf_source, "")
        items.append({
            "id": "fcf",
            "label": "自由现金流（DCF）",
            "status": "missing",
            "detail": "无法得到 TTM FCF",
            "action": source_hint or "提取 kpis.free_cash_flow 或 cash_flow.operating",
        })
    elif fcf_m < 0:
        source_labels = {
            "free_cash_flow": "财报 FCF",
            "operating_cf": "经营现金流×0.85",
            "net_margin_estimate": "净利率估算",
            "revenue_estimate": "营收×5% 估算",
        }
        items.append({
            "id": "fcf",
            "label": "自由现金流（DCF）",
            "status": "partial",
            "detail": f"TTM 约 {round(fcf_m, 2)} 百万 USD（{source_labels.get(fcf_source, '估算')}，为负）",
            "action": "负 FCF 时 DCF 隐含价无参考意义，投入期建议主看 PS",
        })
    else:
        est_note = "（估算）" if fcf_estimated else "（财报）"
        items.append({
            "id": "fcf",
            "label": "自由现金流（DCF）",
            "status": "partial" if fcf_estimated else "ok",
            "detail": f"TTM 约 {round(fcf_m, 2)} 百万 USD {est_note}",
            "action": None if not fcf_estimated else "补充 kpis.free_cash_flow 可提高 DCF 准确度",
        })

    scenarios = dcf.get("scenarios") or []
    if not scenarios:
        items.append({
            "id": "dcf",
            "label": "三情景 DCF",
            "status": "missing",
            "detail": "无法计算（通常因缺少 FCF 或股本）",
            "action": "补全 FCF 与总股本",
        })
    else:
        base = next((s for s in scenarios if s.get("name") == "base"), scenarios[0] if scenarios else None)
        implied = base.get("implied_price") if base else None
        if implied is not None and implied < 0:
            items.append({
                "id": "dcf",
                "label": "三情景 DCF",
                "status": "partial",
                "detail": f"中性隐含价 ${round(implied, 2)}（负值，模型不适用）",
                "action": "FCF 转正后再参考 DCF；当前以 PS 为主",
            })
        elif implied is not None:
            items.append({
                "id": "dcf",
                "label": "三情景 DCF",
                "status": "ok",
                "detail": f"中性隐含价 ${round(implied, 2)}",
                "action": None,
            })
        else:
            items.append({
                "id": "dcf",
                "label": "三情景 DCF",
                "status": "partial",
                "detail": "参数无效（如 WACC ≤ 永续增长）",
                "action": "调整 WACC 或永续增长率",
            })

    if implied_wacc.get("available"):
        items.append({
            "id": "implied_wacc",
            "label": "现价隐含 WACC",
            "status": "ok",
            "detail": f"{implied_wacc.get('value')}%（中性情景）",
            "action": None,
        })
    else:
        items.append({
            "id": "implied_wacc",
            "label": "现价隐含 WACC",
            "status": "missing" if implied_wacc.get("reason") else "partial",
            "detail": implied_wacc.get("reason") or "不可算",
            "action": "需正 FCF、现价、股本，且现价在 DCF 可解释范围内",
        })

    if report_count > 1:
        items.append({
            "id": "report_merge",
            "label": "报告合并",
            "status": "ok",
            "detail": f"已合并同 ticker 下 {report_count} 份已分析报告",
            "action": None,
        })
    elif report_count == 1 and period_count < 4:
        items.append({
            "id": "report_merge",
            "label": "报告合并",
            "status": "partial",
            "detail": "仅 1 份报告参与合并",
            "action": "为更多财季各建一份报告并完成 AI 分析",
        })

    has_gaps = any(i["status"] in ("missing", "partial") for i in items)
    return {"items": items, "has_gaps": has_gaps}


def fmt_usd_gap(value: float) -> str:
    n = float(value)
    if abs(n) >= 1e9:
        return f"${n / 1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"${n / 1e6:.2f}M"
    return f"${n:,.0f}"


def _build_implied_wacc(
    fcf_millions: Optional[float],
    growth_pct: Optional[float],
    market: Dict[str, Any],
    dcf: Dict[str, Any],
) -> Dict[str, Any]:
    price = market.get("price")
    shares = market.get("shares")
    params = dcf.get("params") or {}
    terminal_base = (params.get("terminal_growth") or {}).get("base", DEFAULT_TERMINAL_GROWTH["base"])
    base_growth = params.get("base_growth_pct")
    if base_growth is None:
        base_growth = max(growth_pct or 0.0, 0.0)

    if fcf_millions is None:
        return {
            "available": False,
            "value": None,
            "target_price": price,
            "scenario": "base",
            "method": "bisection",
            "reason": "缺少 FCF",
        }
    if not price:
        return {
            "available": False,
            "value": None,
            "target_price": None,
            "scenario": "base",
            "method": "bisection",
            "reason": "缺少现价",
        }
    if not shares:
        return {
            "available": False,
            "value": None,
            "target_price": price,
            "scenario": "base",
            "method": "bisection",
            "reason": "缺少股本",
        }

    fcf_usd = fcf_millions * 1_000_000
    value = solve_implied_wacc(
        fcf_usd,
        float(base_growth),
        float(terminal_base),
        float(shares),
        float(price),
    )
    if value is None:
        return {
            "available": False,
            "value": None,
            "target_price": price,
            "scenario": "base",
            "method": "bisection",
            "reason": "现价超出 DCF 可解释范围或参数无效",
        }
    return {
        "available": True,
        "value": value,
        "target_price": price,
        "scenario": "base",
        "method": "bisection",
        "reason": None,
    }


def _build_interpretation(
    stage: str,
    primary_metric: str,
    multiples: Dict[str, Any],
    market: Dict[str, Any],
    growth_pct: Optional[float],
    dcf: Dict[str, Any],
) -> str:
    parts: List[str] = []
    if stage == "profitable":
        parts.append("公司处于盈利期，优先参考 PE / PEG。")
        if multiples.get("pe") is not None:
            parts.append(f"当前 PE 约 {multiples['pe']} 倍。")
        if multiples.get("peg") is not None and multiples.get("pe_g_label"):
            parts.append(f"PEG 约 {multiples['peg']}，估值匹配度：{multiples['pe_g_label']}。")
    else:
        parts.append("公司处于投入期或未稳定盈利，优先参考 PS 与 PS-净利率交叉验证。")
        if multiples.get("ps") is not None:
            parts.append(f"当前 PS 约 {multiples['ps']} 倍。")
        if multiples.get("ps_net_margin_note"):
            parts.append(multiples["ps_net_margin_note"])

    if growth_pct is not None:
        parts.append(f"营收增速参考约 {growth_pct}%。")
    if multiples.get("arr_multiple") is not None and multiples.get("nrr_pct") is not None:
        parts.append(
            f"订阅特征：NRR {multiples['nrr_pct']}%，ARR 代理倍数约 {multiples['arr_multiple']} 倍。"
        )

    base_scenario = next((s for s in dcf.get("scenarios") or [] if s.get("name") == "base"), None)
    if base_scenario and base_scenario.get("implied_price") is not None and market.get("price"):
        diff = base_scenario.get("vs_current_price_pct")
        if diff is not None:
            parts.append(f"中性 DCF 隐含价较现价{'偏高' if diff > 0 else '偏低'}约 {abs(diff)}%。")
    return " ".join(parts)


def build_valuation_payload(
    ticker: str,
    chart_payload: Dict[str, Any],
    market_stats: Dict[str, Any] | None,
    override: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """基于合并财报与市场数据构建估值面板数据。"""
    warnings: List[str] = []
    periods = chart_payload.get("periods") or []
    income = chart_payload.get("income_statement") or {}
    kpis = chart_payload.get("kpis") or {}
    cash_flow = chart_payload.get("cash_flow") or {}
    focus_period = chart_payload.get("focus_period")

    ttm = _compute_ttm(periods, income, kpis)
    if ttm.get("method") == "annualized_single_q":
        warnings.append("仅单季数据，营收/净利按 ×4 年化估算")
    revenue_m = ttm.get("revenue_millions")
    net_income_m = ttm.get("net_income_millions")
    revenue_usd = revenue_m * 1_000_000 if revenue_m is not None else None
    net_income_usd = net_income_m * 1_000_000 if net_income_m is not None else None

    growth_pct = _growth_rate_pct(periods, income, kpis, focus_period)
    market = _resolve_market(market_stats, override)
    if market.get("market_cap") is None:
        warnings.append("缺少市值，请填写覆盖值或配置 FMP_API_KEY")

    stage = "profitable" if net_income_usd and net_income_usd > 0 else "pre_profit"
    primary_metric = "PE" if stage == "profitable" else "PS"

    multiples: Dict[str, Any] = {
        "ps": None,
        "pe": None,
        "peg": None,
        "pe_g_label": None,
        "arr_multiple": None,
        "nrr_pct": None,
        "net_margin_pct": None,
        "ps_net_margin_note": None,
    }
    market_cap = market.get("market_cap")
    if market_cap and revenue_usd:
        multiples["ps"] = round(market_cap / revenue_usd, 2)
    if market_cap and net_income_usd and net_income_usd > 0:
        multiples["pe"] = round(market_cap / net_income_usd, 2)
    if multiples["pe"] and growth_pct and growth_pct > 0:
        multiples["peg"] = round(multiples["pe"] / growth_pct, 2)
        multiples["pe_g_label"] = _pe_g_label(multiples["peg"])
    if revenue_m and net_income_m is not None and revenue_m:
        multiples["net_margin_pct"] = round(net_income_m / revenue_m * 100, 2)
        if multiples["ps"] is not None:
            if net_income_m <= 0:
                multiples["ps_net_margin_note"] = "PS 偏高需结合未来盈利兑现；当前净利率为负或偏低。"
            else:
                multiples["ps_net_margin_note"] = (
                    f"PS {multiples['ps']} 倍对应净利率约 {multiples['net_margin_pct']}%，可交叉验证估值合理性。"
                )

    if focus_period:
        nrr = (kpis.get(focus_period) or {}).get("nrr_pct")
        if nrr is not None:
            multiples["nrr_pct"] = nrr
            if multiples["ps"] is not None:
                multiples["arr_multiple"] = multiples["ps"]

    dcf_params = (override or {}).get("dcf_params") or {}
    fcf_m, fcf_estimated = _fcf_millions_ttm(
        ttm.get("periods_used") or [],
        income,
        kpis,
        cash_flow,
        revenue_m,
        net_income_m,
    )
    if fcf_estimated:
        warnings.append("自由现金流为估算值（OCF×0.85 或营收×净利率×0.85）")
    dcf = _build_dcf(fcf_m, fcf_estimated, growth_pct, market, dcf_params)
    implied_wacc = _build_implied_wacc(fcf_m, growth_pct, market, dcf)
    fcf_source = _detect_fcf_source(
        ttm.get("periods_used") or [],
        kpis,
        cash_flow,
        revenue_m,
        net_income_m,
    )
    data_gaps = _build_data_gaps(
        periods=periods,
        report_count=int(chart_payload.get("report_count") or 1),
        ttm=ttm,
        revenue_m=revenue_m,
        net_income_m=net_income_m,
        growth_pct=growth_pct,
        market=market,
        stage=stage,
        primary_metric=primary_metric,
        multiples=multiples,
        fcf_m=fcf_m,
        fcf_estimated=fcf_estimated,
        fcf_source=fcf_source,
        dcf=dcf,
        implied_wacc=implied_wacc,
    )

    return {
        "ticker": ticker,
        "market": market,
        "ttm": {
            "revenue_usd": revenue_usd,
            "net_income_usd": net_income_usd,
            "revenue_millions": revenue_m,
            "net_income_millions": net_income_m,
            "method": ttm.get("method"),
            "periods_used": ttm.get("periods_used") or [],
        },
        "stage": stage,
        "primary_metric": primary_metric,
        "growth_pct": growth_pct,
        "multiples": multiples,
        "dcf": dcf,
        "implied_wacc": implied_wacc,
        "warnings": warnings,
        "data_gaps": data_gaps,
        "interpretation": _build_interpretation(
            stage, primary_metric, multiples, market, growth_pct, dcf
        ),
    }
