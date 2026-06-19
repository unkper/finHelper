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
        "warnings": warnings,
        "interpretation": _build_interpretation(
            stage, primary_metric, multiples, market, growth_pct, dcf
        ),
    }
