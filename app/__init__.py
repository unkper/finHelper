import os
from flask import Flask
from flask_apscheduler import APScheduler
from config import Config

# 初始化全局调度器实例
scheduler = APScheduler()

def create_app(config: Config = None) -> Flask:
    # 1. 确保初始化配置类对象
    if config is None:
        config = Config()

    # 2. 计算项目根目录，精准指定模板与静态文件路径
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 3. 实例化唯一的 Flask 对象（结合你的绝对路径要求）
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, 'templates'),
        static_folder=os.path.join(project_root, 'static')
    )

    # 4. 载入基础核心配置
    app.config.from_object(config)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["API_PROXY"] = config.API_PROXY
    app.config["DEBUG"] = config.DEBUG
    app.config["DATABASE_PATH"] = config.DATABASE_PATH

    # 5. 显式载入飞书相关配置（确保从环境或.env中读取到的属性进入Flask config）
    app.config["FEISHU_APP_ID"] = getattr(config, "FEISHU_APP_ID", "")
    app.config["FEISHU_APP_SECRET"] = getattr(config, "FEISHU_APP_SECRET", "")
    app.config["FEISHU_ENCRYPT_KEY"] = getattr(config, "FEISHU_ENCRYPT_KEY", "")
    app.config["FEISHU_ALERT_RECEIVER_ID"] = getattr(config, "FEISHU_ALERT_RECEIVER_ID", "")
    app.config["FEISHU_ALERT_RECEIVER_TYPE"] = getattr(config, "FEISHU_ALERT_RECEIVER_TYPE", "open_id")
    app.config["FMP_API_KEY"] = getattr(config, "FMP_API_KEY", "")
    app.config["ALPHA_VANTAGE_API_KEY"] = getattr(config, "ALPHA_VANTAGE_API_KEY", "")
    app.config["EODHD_API_KEY"] = getattr(config, "EODHD_API_KEY", "")
    app.config["WEB_PASSWORD"] = getattr(config, "WEB_PASSWORD", "")
    app.config["DEEPSEEK_API_KEY"] = getattr(config, "DEEPSEEK_API_KEY", "")
    app.config["DEEPSEEK_BASE_URL"] = getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    app.config["EARNINGS_ENABLED"] = getattr(config, "EARNINGS_ENABLED", False)
    app.config["FINANCIAL_PDF_DIR"] = str(getattr(config, "FINANCIAL_PDF_DIR", ""))
    app.config["FINANCIAL_PDF_MAX_BYTES"] = getattr(config, "FINANCIAL_PDF_MAX_BYTES", 50 * 1024 * 1024)
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 7

    # 6. 注册数据库清理机制与 CLI 初始化命令
    from app.database import close_db, init_db_command
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

    # 7. 统一注册所有的路由蓝图 (去重，每个蓝图只注册一次)
    from app.routes.auth import bp as auth_bp
    from app.routes.main import bp as main_bp
    from app.routes.investments import bp as investments_bp
    from app.routes.bot import bp as bot_bp  # 飞书机器人回调蓝图
    from app.routes.debug import bp as debug_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(investments_bp)
    app.register_blueprint(bot_bp)
    app.register_blueprint(debug_bp)

    from app.services.auth import require_login

    @app.context_processor
    def inject_feature_flags():
        return {"earnings_enabled": app.config.get("EARNINGS_ENABLED", False)}

    @app.before_request
    def enforce_login():
        return require_login()

    # 8. ================= 核心：后台定时任务配置 =================
    scheduler.init_app(app)

    with app.app_context():
        from app.database import init_db
        init_db()
        from app.scheduler_setup import configure_monitor_jobs
        configure_monitor_jobs(app)

    scheduler.start()
    # ====================================================

    return app