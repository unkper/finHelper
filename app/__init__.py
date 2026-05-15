from flask import Flask
from config import Config

def create_app(config: Config = None) -> Flask:
    if config is None:
        config = Config.from_env()
    
    app = Flask(__name__)
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
    
    return app