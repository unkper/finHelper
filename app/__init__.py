from flask import Flask
from flask_apscheduler import APScheduler

from config import Config
import os

scheduler = APScheduler()

def create_app(config: Config = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 注册数据库和蓝图
    from app.database import close_db, init_db_command
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

    from app.routes.main import bp as main_bp
    from app.routes.investments import bp as investments_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(investments_bp)

    # ================= 核心：定时任务配置 =================
    scheduler.init_app(app)

    # 将监控任务包装在应用上下文中执行 (因为 get_db 需要 app_context)
    @scheduler.task('cron', id='milestone_job', hour=9, minute=0)  # 每天早上 9:00 执行
    def scheduled_milestone_check():
        with app.app_context():
            from app.services.monitor import check_upcoming_milestones
            check_upcoming_milestones()

    @scheduler.task('interval', id='test_job', seconds=10)
    def test_milestone_check():
        with app.app_context():
            from app.services.monitor import check_upcoming_milestones
            check_upcoming_milestones()

    scheduler.start()

    if config is None:
        config = Config.from_env()

    # 获取项目根目录（finHelper文件夹）
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 指定模板和静态文件的路径（与app同级）
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, 'templates'),
        static_folder=os.path.join(project_root, 'static')
    )


    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["API_PROXY"] = config.API_PROXY
    app.config["DEBUG"] = config.DEBUG
    app.config["DATABASE_PATH"] = config.DATABASE_PATH

    from .database import init_db_command, get_db, close_db
    app.cli.add_command(init_db_command)

    @app.teardown_appcontext
    def teardown_db(error):
        close_db(error)

    from .routes import bp
    app.register_blueprint(bp)

    from app.routes.investments import bp as investments_bp
    app.register_blueprint(investments_bp)

    from app.routes.main import bp as main_bp
    from app.routes.investments import bp as investments_bp
    from app.routes.bot import bp as bot_bp  # 导入机器人蓝图

    app.register_blueprint(main_bp)
    app.register_blueprint(investments_bp)
    app.register_blueprint(bot_bp)  # 注册蓝图

    return app