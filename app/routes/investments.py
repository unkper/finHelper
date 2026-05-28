# app/routes/investments.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from app.database import get_db
from app.services.investment import (
    fetch_assistants_with_themes, fetch_all_assistants, fetch_theme_by_id,
    fetch_theme_details, fetch_theme_score, create_theme, create_assistant,
    move_theme_to_assistant, delete_theme,
    add_theme_asset, add_theme_milestone, update_theme_milestone, add_theme_article,
    delete_theme_milestone, delete_theme_asset, delete_theme_article,
    build_milestone_index,
)
from app.services.settings import (
    get_macd_alert_settings,
    set_macd_alert_death_cross_below_zero,
    set_macd_alert_golden_cross_above_zero,
    get_earnings_settings,
    set_earnings_horizon_days,
    set_earnings_remind_days_before,
    set_earnings_remind_enabled,
)
from app.services.earnings_calendar import build_earnings_payload, is_earnings_api_configured
from app.services.stock_charts import build_stock_chart_payload
from app.services.rate_limit import consume_rate_limit, get_client_ip
from app.scheduler_setup import configure_monitor_jobs

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


@bp.route('/stocks')
def stocks():
    return render_template("investments/stocks.html")


@bp.route('/stocks/api/chart-data')
def stocks_chart_data():
    ip = get_client_ip()
    force_refresh = request.args.get("refresh") == "1"
    if force_refresh:
        allowed, retry_after = consume_rate_limit(
            f"chart-refresh:{ip}", max_calls=5, window_seconds=300
        )
    else:
        allowed, retry_after = consume_rate_limit(
            f"chart-data:{ip}", max_calls=60, window_seconds=60
        )
    if not allowed:
        return jsonify({
            "error": "请求过于频繁，请稍后再试",
            "retry_after": retry_after,
        }), 429

    return jsonify(build_stock_chart_payload(force_refresh=force_refresh))


@bp.route('/api/macd-alerts', methods=['POST'])
def macd_alerts():
    data = request.get_json(silent=True) or {}
    golden = bool(data.get("golden_cross_above_zero"))
    death = bool(data.get("death_cross_below_zero"))
    set_macd_alert_golden_cross_above_zero(golden)
    set_macd_alert_death_cross_below_zero(death)
    configure_monitor_jobs(current_app._get_current_object())
    return jsonify({
        "status": "ok",
        "macd_alerts": get_macd_alert_settings(),
    })


@bp.route('/earnings')
def earnings():
    return render_template(
        "investments/earnings.html",
        earnings_settings=get_earnings_settings(),
        api_configured=is_earnings_api_configured(),
    )


@bp.route('/earnings/api/calendar')
def earnings_calendar_api():
    ip = get_client_ip()
    force_refresh = request.args.get("refresh") == "1"
    if force_refresh:
        allowed, retry_after = consume_rate_limit(
            f"earnings-refresh:{ip}", max_calls=5, window_seconds=300
        )
    else:
        allowed, retry_after = consume_rate_limit(
            f"earnings-calendar:{ip}", max_calls=30, window_seconds=60
        )
    if not allowed:
        return jsonify({
            "error": "请求过于频繁，请稍后再试",
            "retry_after": retry_after,
        }), 429

    horizon = request.args.get("horizon_days", type=int)
    if horizon is None:
        horizon = get_earnings_settings()["horizon_days"]
    payload = build_earnings_payload(horizon_days=horizon, force_refresh=force_refresh)
    payload["settings"] = get_earnings_settings()
    return jsonify(payload)


@bp.route('/earnings/api/settings', methods=['POST'])
def earnings_settings_api():
    data = request.get_json(silent=True) or {}
    horizon = data.get("horizon_days")
    remind_before = data.get("remind_days_before")
    remind_enabled = data.get("remind_enabled")

    if horizon is not None:
        set_earnings_horizon_days(int(horizon))
    if remind_before is not None:
        set_earnings_remind_days_before(int(remind_before))
    if remind_enabled is not None:
        set_earnings_remind_enabled(bool(remind_enabled))

    configure_monitor_jobs(current_app._get_current_object())
    return jsonify({
        "status": "ok",
        "settings": get_earnings_settings(),
    })


@bp.route('/<int:theme_id>')
def detail(theme_id):
    theme = fetch_theme_by_id(theme_id)
    if not theme:
        flash("投资主题不存在", "error")
        return redirect(url_for('investments.index'))

    details = fetch_theme_details(theme_id)
    theme_score = fetch_theme_score(theme_id)
    milestones = details["milestones"]
    milestone_index = build_milestone_index(milestones)
    return render_template(
        "investments/detail.html",
        theme=theme,
        theme_score=theme_score,
        assistants=fetch_all_assistants(),
        articles=details['articles'],
        assets=details['assets'],
        milestones=milestones,
        milestone_index=milestone_index,
        macd_alerts=get_macd_alert_settings(),
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


def _parse_milestone_dates(event_date: str, end_date_raw: str | None):
    """解析节点起止日期，默认同一天。"""
    if not event_date:
        raise ValueError("开始日期不能为空")
    end_date = (end_date_raw or event_date).strip() or event_date
    if end_date < event_date:
        raise ValueError("结束日期不能早于开始日期")
    return event_date, end_date


def _parse_milestone_ids_from_form(theme_id: int) -> list[int]:
    """解析表单中选中的时间节点 ID，并校验归属当前主题。"""
    raw_ids = request.form.getlist("milestone_ids")
    milestone_ids: list[int] = []
    for raw in raw_ids:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            milestone_ids.append(int(raw))
        except ValueError:
            raise ValueError("时间节点选择无效")
    if not milestone_ids:
        return []

    db = get_db()
    placeholders = ",".join("?" * len(milestone_ids))
    rows = db.execute(
        f"""
        SELECT id FROM theme_milestones
        WHERE theme_id = ? AND id IN ({placeholders})
        """,
        (theme_id, *milestone_ids),
    ).fetchall()
    found = {row["id"] for row in rows}
    missing = set(milestone_ids) - found
    if missing:
        raise ValueError("所选时间节点不存在或不属于当前主题")
    return milestone_ids


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
        milestone_ids = _parse_milestone_ids_from_form(theme_id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    if not price_alerts and not milestone_ids:
        flash("请至少添加一条价位提醒，或选择要随节点提醒的时间点", "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    add_theme_asset(theme_id, ticker, exchange, price_alerts, milestone_ids)
    parts = []
    if price_alerts:
        parts.append(f"{len(price_alerts)} 条价位提醒")
    if milestone_ids:
        details = fetch_theme_details(theme_id)
        idx = build_milestone_index(details["milestones"])
        labels = [f"#{idx[mid]}" for mid in milestone_ids if mid in idx]
        parts.append(f"随 {'、'.join(labels)} 节点提醒" if labels else f"随 {len(milestone_ids)} 个节点提醒")
    flash(f"已添加监控标的 {ticker}（{'、'.join(parts)}）", "success")
    return redirect(url_for('investments.detail', theme_id=theme_id))


def _normalize_reminder_time(raw: str) -> str:
    """将表单时间规范为 HH:MM，默认 12:00。"""
    value = (raw or "12:00").strip()
    if (len(value) >= 5):
        return value[:5]
    return "12:00"


def _parse_profit_loss(raw: str):
    """解析盈亏金额；空值表示不纳入评分。"""
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        raise ValueError("盈亏金额格式无效，请输入数字")


@bp.route('/<int:theme_id>/delete', methods=['POST'])
def delete_theme_route(theme_id):
    title = delete_theme(theme_id)
    if title:
        flash(f"已删除投资主题：{title}", "success")
    else:
        flash("主题不存在或已删除", "error")
    return redirect(url_for('investments.index'))


@bp.route('/<int:theme_id>/add_milestone', methods=['POST'])
def add_milestone(theme_id):
    event_date = request.form.get('event_date')
    description = request.form.get('description', '').strip()
    reminder_time = _normalize_reminder_time(request.form.get('reminder_time'))

    if not event_date or not description:
        flash("日期和描述不能为空", "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    try:
        profit_loss = _parse_profit_loss(request.form.get('profit_loss'))
        event_date, end_date = _parse_milestone_dates(
            event_date,
            request.form.get('end_date'),
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    add_theme_milestone(theme_id, event_date, description, reminder_time, profit_loss, end_date)
    range_hint = f"{event_date} ~ {end_date}" if end_date != event_date else event_date
    score_hint = f"，盈亏 {profit_loss:+.2f}" if profit_loss is not None else ""
    flash(f"时间线节点已添加，将于 {range_hint} 每日 {reminder_time} 飞书提醒{score_hint}", "success")
    return redirect(url_for('investments.detail', theme_id=theme_id))


@bp.route('/<int:theme_id>/milestones/<int:milestone_id>/edit', methods=['POST'])
def edit_milestone(theme_id, milestone_id):
    event_date = request.form.get('event_date')
    description = request.form.get('description', '').strip()
    reminder_time = _normalize_reminder_time(request.form.get('reminder_time'))
    is_completed = request.form.get('is_completed') == '1'

    if not event_date or not description:
        flash("日期和描述不能为空", "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    try:
        profit_loss = _parse_profit_loss(request.form.get('profit_loss'))
        event_date, end_date = _parse_milestone_dates(
            event_date,
            request.form.get('end_date'),
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    if update_theme_milestone(
        theme_id,
        milestone_id,
        event_date,
        description,
        reminder_time,
        profit_loss,
        is_completed,
        end_date,
    ):
        flash("时间线节点已更新", "success")
    else:
        flash("节点不存在或已删除", "error")
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
