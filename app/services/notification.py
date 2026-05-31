"""统一监控通知：收集、按优先级排序、合并 digest 后推送。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from flask import current_app

from app.database import get_db
from app.services.feishu import push_feishu_message

DIGEST_MAX_CHARS = 4000

PRIORITY_PRICE = 0
PRIORITY_MILESTONE_DAY = 1
PRIORITY_MACD = 2
PRIORITY_MILESTONE_ADVANCE = 3
PRIORITY_MILESTONE_QUOTES = 4
PRIORITY_EARNINGS = 5

SECTION_TITLES = {
    PRIORITY_PRICE: "P0 · 股价触达",
    PRIORITY_MILESTONE_DAY: "P1 · 节点提醒",
    PRIORITY_MACD: "P2 · MACD 信号",
    PRIORITY_MILESTONE_ADVANCE: "P3 · 节点提前提醒",
    PRIORITY_MILESTONE_QUOTES: "P4 · 节点标的行情",
    PRIORITY_EARNINGS: "P5 · 财报日历",
}


@dataclass
class AlertEvent:
    priority: int
    category: str
    body: str
    sort_key: tuple = field(default_factory=tuple)

    @property
    def section_title(self) -> str:
        return SECTION_TITLES.get(self.priority, f"P{self.priority}")


@dataclass
class CollectResult:
    events: list[AlertEvent] = field(default_factory=list)
    apply_marks: Callable[[], None] | None = None


def _sort_events(events: list[AlertEvent]) -> list[AlertEvent]:
    return sorted(events, key=lambda e: (e.priority, e.sort_key))


def build_digest(events: list[AlertEvent]) -> tuple[str, int]:
    """构建 digest 文本；返回 (content, omitted_count)。"""
    sorted_events = _sort_events(events)
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"🔔 FinHelper 监控汇总\n{now_label} · 共 {len(sorted_events)} 条"

    by_priority: dict[int, list[AlertEvent]] = defaultdict(list)
    for event in sorted_events:
        by_priority[event.priority].append(event)

    sections: list[str] = []

    for priority in sorted(by_priority.keys()):
        group = by_priority[priority]
        section_title = SECTION_TITLES.get(priority, f"P{priority}")
        section_lines = [f"━━ {section_title} ━━"]
        for event in group:
            section_lines.append(event.body)
        sections.append("\n\n".join(section_lines))

    body = header + "\n\n" + "\n\n".join(sections)
    if len(body) <= DIGEST_MAX_CHARS:
        return body, 0

    omitted = 0
    trimmed: list[AlertEvent] = list(sorted_events)
    while trimmed:
        trimmed.pop()
        omitted += 1
        by_priority = defaultdict(list)
        for event in trimmed:
            by_priority[event.priority].append(event)
        sections = []
        for priority in sorted(by_priority.keys()):
            group = by_priority[priority]
            section_title = SECTION_TITLES.get(priority, f"P{priority}")
            section_lines = [f"━━ {section_title} ━━"]
            for event in group:
                section_lines.append(event.body)
            sections.append("\n\n".join(section_lines))
        body = header.replace(f"共 {len(sorted_events)} 条", f"共 {len(trimmed)} 条")
        body += "\n\n" + "\n\n".join(sections)
        if len(body) <= DIGEST_MAX_CHARS:
            body += f"\n\n（另有 {omitted} 条较低优先级提醒未展示）"
            return body, omitted

    return header + "\n\n（消息过长，本轮提醒未展示）", len(sorted_events)


def run_monitor_digest() -> None:
    """收集全部监控事件，合并 digest 推送；仅推送成功时写入去重标记。"""
    from app.services.earnings_monitor import collect_earnings_alerts
    from app.services.macd_monitor import collect_macd_alerts
    from app.services.monitor import collect_milestone_alerts
    from app.services.price_monitor import collect_price_alerts

    collectors = (
        collect_price_alerts,
        collect_milestone_alerts,
        collect_macd_alerts,
        collect_earnings_alerts,
    )

    all_events: list[AlertEvent] = []
    mark_callbacks: list[Callable[[], None]] = []

    for collect in collectors:
        result = collect()
        if result.events:
            all_events.extend(result.events)
        if result.apply_marks:
            mark_callbacks.append(result.apply_marks)

    if not all_events:
        return

    digest, omitted = build_digest(all_events)
    if omitted:
        print(f"监控 digest 截断：省略 {omitted} 条较低优先级提醒")

    receiver_id = current_app.config.get("FEISHU_ALERT_RECEIVER_ID")
    receiver_type = current_app.config.get("FEISHU_ALERT_RECEIVER_TYPE")

    if not receiver_id:
        print("未配置 FEISHU_ALERT_RECEIVER_ID，无法发送飞书消息。内容如下：\n", digest)
        return

    db = get_db()
    try:
        ok = push_feishu_message(receiver_type, receiver_id, digest)
        if not ok:
            db.rollback()
            print("飞书主动推送失败或被限流，去重标记未写入，下轮将重试")
            return

        for apply_marks in mark_callbacks:
            apply_marks()
        db.commit()
        print(f"已成功发送监控 digest 至飞书（{len(all_events)} 条事件）")
    except Exception as exc:
        db.rollback()
        print(f"监控 digest 推送异常: {exc}")
