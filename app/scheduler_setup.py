from app import scheduler


def _run_monitor_digest(app) -> None:
    with app.app_context():
        from app.services.notification import run_monitor_digest
        run_monitor_digest()


def configure_monitor_jobs(app) -> int:
    """按全局配置注册/更新监控定时任务，返回当前间隔（分钟）。"""
    with app.app_context():
        from app.services.settings import ensure_default_settings, get_monitor_interval_minutes
        ensure_default_settings()
        interval = get_monitor_interval_minutes()

    if scheduler.get_job("monitor_digest_job"):
        scheduler.remove_job("monitor_digest_job")

    for legacy_job_id in ("milestone_job", "price_alert_job", "macd_alert_job", "earnings_reminder_job"):
        if scheduler.get_job(legacy_job_id):
            scheduler.remove_job(legacy_job_id)

    scheduler.add_job(
        id="monitor_digest_job",
        func=lambda: _run_monitor_digest(app),
        trigger="interval",
        minutes=interval,
        replace_existing=True,
    )
    return interval
