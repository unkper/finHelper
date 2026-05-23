# app/routes/investments.py
from flask import Blueprint, render_template, request, flash, redirect, url_for
from app.services.investment import (
    fetch_assistants_with_themes, fetch_all_assistants, fetch_theme_by_id,
    fetch_theme_details, create_theme, create_assistant, move_theme_to_assistant,
    add_theme_asset, add_theme_milestone, add_theme_article,
    delete_theme_milestone, delete_theme_asset, delete_theme_article,
)

bp = Blueprint('investments', __name__, url_prefix='/investments')


@bp.route('/')
def index():
    assistant_groups = fetch_assistants_with_themes()
    assistants = fetch_all_assistants()
    return render_template(
        "investments/index.html",
        assistant_groups=assistant_groups,
        assistants=assistants,
    )


@bp.route('/<int:theme_id>')
def detail(theme_id):
    theme = fetch_theme_by_id(theme_id)
    if not theme:
        flash("投资主题不存在", "error")
        return redirect(url_for('investments.index'))

    details = fetch_theme_details(theme_id)
    return render_template(
        "investments/detail.html",
        theme=theme,
        assistants=fetch_all_assistants(),
        articles=details['articles'],
        assets=details['assets'],
        milestones=details['milestones']
    )


@bp.route('/create', methods=['POST'])
def create():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    assistant_id = request.form.get('assistant_id', type=int)

    if not title:
        flash("标题不能为空", "error")
    else:
        create_theme(title, description, assistant_id)
        flash("新投资主题已创建", "success")
    return redirect(url_for('investments.index'))


@bp.route('/assistants/create', methods=['POST'])
def create_assistant_route():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    if not name:
        flash("助手名称不能为空", "error")
    else:
        create_assistant(name, description)
        flash(f"投资助手「{name}」已创建", "success")
    return redirect(url_for('investments.index'))


@bp.route('/<int:theme_id>/move_assistant', methods=['POST'])
def move_assistant(theme_id):
    assistant_id = request.form.get('assistant_id', type=int)
    if not assistant_id:
        flash("请选择目标投资助手", "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    if move_theme_to_assistant(theme_id, assistant_id):
        flash("主题已移动到新的投资助手", "success")
    else:
        flash("移动失败，请检查主题或助手是否存在", "error")
    return redirect(url_for('investments.detail', theme_id=theme_id))


def _parse_price_alerts_from_form():
    """解析表单中的多条价格提醒。"""
    prices = request.form.getlist("alert_target_price")
    directions = request.form.getlist("alert_direction")
    notes = request.form.getlist("alert_note")
    alerts = []
    for i, price_raw in enumerate(prices):
        price_raw = (price_raw or "").strip()
        if not price_raw:
            continue
        try:
            target_price = float(price_raw)
        except ValueError:
            raise ValueError(f"第 {i + 1} 条提醒价格格式无效")
        direction = (directions[i] if i < len(directions) else "below").strip()
        if direction not in ("below", "above"):
            direction = "below"
        note = (notes[i] if i < len(notes) else "").strip() or None
        alerts.append({
            "target_price": target_price,
            "direction": direction,
            "note": note,
        })
    return alerts


@bp.route('/<int:theme_id>/add_asset', methods=['POST'])
def add_asset(theme_id):
    ticker = request.form.get('ticker', '').upper().strip()
    exchange = request.form.get('exchange', 'US').upper().strip()

    if not ticker:
        flash("股票代码不能为空", "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    if exchange != "US":
        flash("当前仅支持美股（US）的价格提醒", "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    try:
        price_alerts = _parse_price_alerts_from_form()
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    if not price_alerts:
        flash("请至少添加一条价格提醒", "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    add_theme_asset(theme_id, ticker, exchange, price_alerts)
    flash(f"已添加监控标的 {ticker}，共 {len(price_alerts)} 条价格提醒", "success")
    return redirect(url_for('investments.detail', theme_id=theme_id))


def _normalize_reminder_time(raw: str) -> str:
    """将表单时间规范为 HH:MM，默认 12:00。"""
    value = (raw or "12:00").strip()
    if len(value) >= 5:
        return value[:5]
    return "12:00"


@bp.route('/<int:theme_id>/add_milestone', methods=['POST'])
def add_milestone(theme_id):
    event_date = request.form.get('event_date')
    description = request.form.get('description', '').strip()
    reminder_time = _normalize_reminder_time(request.form.get('reminder_time'))

    if not event_date or not description:
        flash("日期和描述不能为空", "error")
    else:
        add_theme_milestone(theme_id, event_date, description, reminder_time)
        flash(f"时间线节点已添加，将于 {event_date} {reminder_time} 飞书提醒", "success")

    return redirect(url_for('investments.detail', theme_id=theme_id))


@bp.route('/<int:theme_id>/milestones/<int:milestone_id>/delete', methods=['POST'])
def delete_milestone(theme_id, milestone_id):
    if delete_theme_milestone(theme_id, milestone_id):
        flash("时间线节点已删除", "success")
    else:
        flash("节点不存在或已删除", "error")
    return redirect(url_for('investments.detail', theme_id=theme_id))


@bp.route('/<int:theme_id>/assets/<int:asset_id>/delete', methods=['POST'])
def delete_asset(theme_id, asset_id):
    ticker = delete_theme_asset(theme_id, asset_id)
    if ticker:
        flash(f"已删除监控标的 {ticker}", "success")
    else:
        flash("标的不存在或已删除", "error")
    return redirect(url_for('investments.detail', theme_id=theme_id))


@bp.route('/<int:theme_id>/articles/<int:article_id>/delete', methods=['POST'])
def delete_article(theme_id, article_id):
    title = delete_theme_article(theme_id, article_id)
    if title:
        flash(f"已删除文章：{title}", "success")
    else:
        flash("文章不存在或已删除", "error")
    return redirect(url_for('investments.detail', theme_id=theme_id))


@bp.route('/<int:theme_id>/add_article', methods=['POST'])
def add_article(theme_id):
    title = request.form.get('title', '').strip()
    url = request.form.get('url', '').strip()
    summary = request.form.get('summary', '').strip()

    if not title:
        flash("文章标题不能为空", "error")
    else:
        add_theme_article(theme_id, title, url, summary)
        flash("文章已添加", "success")

    return redirect(url_for('investments.detail', theme_id=theme_id))
