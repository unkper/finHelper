"""SEC 三表字段标签映射与 KPI 构建（FMP JSON / 旧 Excel 共用）。"""
import re
from typing import Any, Dict, Optional, Tuple

INCOME_MAP: Dict[str, Tuple[str, ...]] = {
    "revenue": ("revenue",),
    "net sales": ("revenue",),
    "total revenue": ("revenue",),
    "cost of goods sold": ("cogs",),
    "gross margin": ("gross_profit",),
    "research and development": ("rd",),
    "selling, general, and administrative": ("sga",),
    "operating income": ("operating_income",),
    "operating income (loss)": ("operating_income",),
    "income tax": ("tax",),
    "income tax (provision) benefit": ("tax",),
    "provision for income taxes": ("tax",),
    "net income": ("net_income",),
    "net income (loss)": ("net_income",),
}

BALANCE_MAP: Dict[str, Tuple[str, ...]] = {
    "cash and cash equivalents": ("cash",),
    "receivables": ("receivables",),
    "inventories": ("inventory",),
    "property, plant, and equipment": ("ppe",),
    "total assets": ("total_assets",),
    "total current liabilities": ("current_liabilities",),
    "long-term debt": ("long_term_debt",),
    "total liabilities": ("total_liabilities",),
    "total shareholders' equity": ("equity",),
    "total shareholders’ equity": ("equity",),
    "total stockholders' equity": ("equity",),
    "total stockholders’ equity": ("equity",),
    "total equity": ("equity",),
}

CASH_MAP: Dict[str, Tuple[str, ...]] = {
    "net cash provided by operating activities": ("operating",),
    "net cash used for operating activities": ("operating",),
    "net cash used for investing activities": ("investing",),
    "net cash provided by (used for) investing activities": ("investing",),
    "net cash provided by (used for) financing activities": ("financing",),
    "net cash used for financing activities": ("financing",),
}


def normalize_label(text: Any) -> str:
    s = str(text or "").strip().lower()
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = re.sub(r"\s+", " ", s)
    return s


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        if value != value:
            return None
        return float(value)
    text = str(value).strip().replace(",", "").replace("—", "").replace("–", "")
    if not text or text in ("-", "—"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def match_field(label: str, mapping: Dict[str, Tuple[str, ...]]) -> Optional[str]:
    norm = normalize_label(label)
    if not norm:
        return None
    if "non-operating" in norm and "operating income" in norm:
        pass  # 避免 Other non-operating income 误匹配营业利润
    elif "before income tax" in norm or "equity in net income" in norm:
        return None
    for key in sorted(mapping.keys(), key=len, reverse=True):
        fields = mapping[key]
        if key in norm or norm.startswith(key):
            if key == "operating income" and "non-operating" in norm:
                continue
            return fields[0]
    return None


def yoy_pct(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None or prior == 0:
        return None
    return round((current - prior) / abs(prior) * 100, 2)


def build_kpis(
    income: Dict[str, float],
    income_prior: Dict[str, float],
    cash_flow: Dict[str, float],
    cash_scope: str,
) -> Dict[str, Any]:
    kpis: Dict[str, Any] = {}
    rev = income.get("revenue")
    if rev is not None:
        kpis["revenue"] = {
            "value": rev,
            "yoy_pct": yoy_pct(rev, income_prior.get("revenue")),
            "qoq_pct": None,
        }
    net = income.get("net_income")
    if net is not None:
        kpis["net_profit"] = {
            "value": net,
            "yoy_pct": yoy_pct(net, income_prior.get("net_income")),
            "qoq_pct": None,
        }
    if income.get("revenue") and income.get("gross_profit") is not None:
        kpis["gross_margin_pct"] = round(
            income["gross_profit"] / income["revenue"] * 100, 2
        )
    if cash_scope == "quarter" and cash_flow.get("operating") is not None:
        kpis["operating_cf"] = cash_flow["operating"]
        kpis["free_cash_flow"] = cash_flow["operating"]
    return kpis
