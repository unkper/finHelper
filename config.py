from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent

class Config:
    SECRET_KEY: str = "dev"
    API_PROXY: Optional[str] = None
    DEBUG: bool = False
    DATABASE_PATH: Path = BASE_DIR / "assets.db"
    
    @classmethod
    def from_env(cls) -> "Config":
        config = cls()
        try:
            with open(BASE_DIR / ".env", "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        if key == "SECRET_KEY":
                            config.SECRET_KEY = value
                        elif key == "API_PROXY":
                            config.API_PROXY = value if value else None
                        elif key == "DEBUG":
                            config.DEBUG = value.lower() == "true"
        except FileNotFoundError:
            pass
        return config