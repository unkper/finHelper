from flask import Flask
from config import Config
import os


def create_app(config: Config = None) -> Flask:
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

    return app