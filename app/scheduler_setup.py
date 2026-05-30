from app import scheduler


def _run_milestone_check(app) -> None:
    with app.app_context():
        from app.services.monitor import check_upcoming_milestones
        check_upcoming_milestones()


def _run_price_alert_check(app) -> None:
    with app.app_context():
        from app.services.price_monitor import check_asset_price_alerts
        check_asset_price_alerts()


def _run_macd_alert_check(app) -> None:
    with app.app_context():
        from app.services.macd_monitor import check_macd_alerts
        check_macd_alerts()


def _run_earnings_reminder_check(app) -> None:
    with app.app_context():
        from app.services.earnings_monitor import check_earnings_reminders
        check_earnings_reminders()


def configure_monitor_jobs(app) -> int:
    """按全局配置注册/更新监控定时任务，返回当前间隔（分钟）。"""
    with app.app_context():
        from app.services.settings import ensure_default_settings, get_monitor_interval_minutes
        from app.services.features import is_earnings_enabled
        ensure_default_settings()
        interval = get_monitor_interval_minutes()
        earnings_enabled = is_earnings_enabled()

    for job_id in ("milestone_job", "price_alert_job", "macd_alert_job", "earnings_reminder_job"):
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

    scheduler.add_job(
        id="milestone_job",
        func=lambda: _run_milestone_check(app),
        trigger="interval",
        minutes=interval,
        replace_existing=True,
    )
    scheduler.add_job(
        id="price_alert_job",
        func=lambda: _run_price_alert_check(app),
        trigger="interval",
        minutes=interval,
        replace_existing=True,
    )
    scheduler.add_job(
        id="macd_alert_job",
        func=lambda: _run_macd_alert_check(app),
        trigger="interval",
        minutes=interval,
        replace_existing=True,
    )
    if earnings_enabled:
        scheduler.add_job(
            id="earnings_reminder_job",
            func=lambda: _run_earnings_reminder_check(app),
            trigger="interval",
            minutes=interval,
            replace_existing=True,
        )
    return interval
