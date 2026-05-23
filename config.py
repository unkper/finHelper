import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# 这一行会自动找到 .env 文件并把它里面的键值对注入到系统环境变量中
load_dotenv(BASE_DIR / ".env")

class Config:
    # 直接使用 os.environ.get 读取，因为 load_dotenv 已经把值塞进去了
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev")
    API_PROXY = os.environ.get("API_PROXY")
    DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
    DATABASE_PATH = BASE_DIR / "assets.db"

    # 飞书应用配置
    FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
    FEISHU_ENCRYPT_KEY = os.environ.get("FEISHU_ENCRYPT_KEY", "")
    FEISHU_ALERT_RECEIVER_ID = os.environ.get("FEISHU_ALERT_RECEIVER_ID", "")
    FEISHU_ALERT_RECEIVER_TYPE = os.environ.get("FEISHU_ALERT_RECEIVER_TYPE", "open_id")

    # Financial Modeling Prep（美股行情）
    FMP_API_KEY = os.environ.get("FMP_API_KEY", "")

# 这样你的 app 初始化时，直接 app.config.from_object(Config) 即可，不需要再调 from_env() 了