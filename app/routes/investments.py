# app/routes/investments.py
from flask import Blueprint, render_template, request, flash, redirect, url_for
from app.services.investment import (
    fetch_all_themes, fetch_theme_by_id, fetch_theme_details, create_theme, add_theme_asset, add_theme_milestone
)

bp = Blueprint('investments', __name__, url_prefix='/investments')


@bp.route('/')
def index():
    themes = fetch_all_themes()
    return render_template("investments/index.html", themes=themes)


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
        articles=details['articles'],
        assets=details['assets'],
        milestones=details['milestones']
    )


@bp.route('/create', methods=['POST'])
def create():
    title = request.form.get('title')
    description = request.form.get('description')
    if not title:
        flash("标题不能为空", "error")
    else:
        create_theme(title, description)
        flash("新投资主题已创建", "success")
    return redirect(url_for('investments.index'))


@bp.route('/<int:theme_id>/add_asset', methods=['POST'])
def add_asset(theme_id):
    ticker = request.form.get('ticker', '').upper().strip()
    exchange = request.form.get('exchange', 'US').upper().strip()

    # 将前端传来的价格字符串转换为浮点数
    try:
        target_buy = float(request.form.get('target_buy', 0))
        target_sell = float(request.form.get('target_sell', 0))
    except ValueError:
        flash("价格输入格式错误，请输入数字", "error")
        return redirect(url_for('investments.detail', theme_id=theme_id))

    if not ticker:
        flash("股票代码不能为空", "error")
    else:
        add_theme_asset(theme_id, ticker, exchange, target_buy, target_sell)
        flash(f"已添加监控标的: {ticker}", "success")

    return redirect(url_for('investments.detail', theme_id=theme_id))


@bp.route('/<int:theme_id>/add_milestone', methods=['POST'])
def add_milestone(theme_id):
    event_date = request.form.get('event_date')
    description = request.form.get('description', '').strip()

    if not event_date or not description:
        flash("日期和描述不能为空", "error")
    else:
        add_theme_milestone(theme_id, event_date, description)
        flash("时间线节点已更新", "success")

    return redirect(url_for('investments.detail', theme_id=theme_id))