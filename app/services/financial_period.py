"""财季字符串校验与规范化（YYYY-Q1～Q4）。"""
import re

FISCAL_PERIOD_RE = re.compile(r"^\d{4}-Q[1-4]$")


def normalize_fiscal_period(raw: str) -> str:
    s = (raw or "").strip().upper()
    if not FISCAL_PERIOD_RE.match(s):
        raise ValueError("财季格式须为 YYYY-Q1～Q4，例如 2026-Q1")
    return s
