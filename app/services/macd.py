"""MACD 计算与金叉/死叉信号识别（DIF/DEA，12/26/9）。"""
from typing import Any, Dict, List, Optional, Tuple

SIGNAL_GOLDEN_CROSS_ABOVE_ZERO = "golden_cross_above_zero"
SIGNAL_DEATH_CROSS_BELOW_ZERO = "death_cross_below_zero"

SIGNAL_LABELS = {
    SIGNAL_GOLDEN_CROSS_ABOVE_ZERO: "零轴上方金叉",
    SIGNAL_DEATH_CROSS_BELOW_ZERO: "零轴下方死叉",
}


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    multiplier = 2 / (period + 1)
    prev: Optional[float] = None
    for i, value in enumerate(values):
        if value is None:
            out.append(None)
            continue
        if prev is None:
            if i < period - 1:
                out.append(None)
                continue
            prev = sum(values[i - period + 1 : i + 1]) / period
            out.append(prev)
            continue
        prev = value * multiplier + prev * (1 - multiplier)
        out.append(prev)
    return out


def calc_macd(
    closes: List[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    ema_fast = _ema(closes, fast_period)
    ema_slow = _ema(closes, slow_period)
    dif: List[Optional[float]] = []
    for fast, slow in zip(ema_fast, ema_slow):
        if fast is None or slow is None:
            dif.append(None)
        else:
            dif.append(fast - slow)

    dif_for_signal = [d if d is not None else 0.0 for d in dif]
    dea_raw = _ema(dif_for_signal, signal_period)
    dea = [None if dif[i] is None else dea_raw[i] for i in range(len(dif))]

    histogram = []
    for d, s in zip(dif, dea):
        if d is None or s is None:
            histogram.append(None)
        else:
            histogram.append(d - s)
    return dif, dea, histogram


def _cross_at_index(
    dif: List[Optional[float]],
    dea: List[Optional[float]],
    index: int,
) -> List[str]:
    if index < 1 or index >= len(dif):
        return []
    prev_dif, curr_dif = dif[index - 1], dif[index]
    prev_dea, curr_dea = dea[index - 1], dea[index]
    if None in (prev_dif, curr_dif, prev_dea, curr_dea):
        return []

    signals: List[str] = []
    if prev_dif <= prev_dea and curr_dif > curr_dea and curr_dif > 0 and curr_dea > 0:
        signals.append(SIGNAL_GOLDEN_CROSS_ABOVE_ZERO)
    if prev_dif >= prev_dea and curr_dif < curr_dea and curr_dif < 0 and curr_dea < 0:
        signals.append(SIGNAL_DEATH_CROSS_BELOW_ZERO)
    return signals


def analyze_macd_from_series(
    series: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """基于日 K 收盘价序列分析 MACD，返回最新信号与 DIF/DEA。"""
    closes = [float(p["close"]) for p in series if p.get("close") is not None]
    dates = [p["date"] for p in series if p.get("close") is not None]
    empty = {
        "dif": None,
        "dea": None,
        "histogram": None,
        "bar_date": None,
        "signals": [],
        "ready": False,
    }
    if len(closes) < 35:
        return empty

    dif, dea, histogram = calc_macd(closes)
    index = len(closes) - 1
    if dif[index] is None or dea[index] is None:
        return empty

    return {
        "dif": round(dif[index], 4),
        "dea": round(dea[index], 4),
        "histogram": round(histogram[index], 4) if histogram[index] is not None else None,
        "bar_date": dates[index] if index < len(dates) else None,
        "signals": _cross_at_index(dif, dea, index),
        "ready": True,
    }
