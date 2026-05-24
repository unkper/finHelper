from app import scheduler


def _run_milestone_check(app) -> None:
    with app.app_context():
        from app.services.monitor import check_upcoming_milestones
        check_upcoming_milestones()


def _run_price_alert_check(app) -> None:
    with app.app_context():
        from app.services.price_monitor import check_asset_price_alerts
        check_asset_price_alerts()


def configure_monitor_jobs(app) -> int:
    """按全局配置注册/更新监控定时任务，返回当前间隔（分钟）。"""
    with app.app_context():
        from app.services.settings import ensure_default_settings, get_monitor_interval_minutes
        ensure_default_settings()
        interval = get_monitor_interval_minutes()

    for job_id in ("milestone_job", "price_alert_job"):
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
    return interval
