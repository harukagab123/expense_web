from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = f"sqlite:///{(PROJECT_ROOT / 'data' / 'app.db').as_posix()}"
DEFAULT_STORAGE_DIR = PROJECT_ROOT / "storage" / "files"


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


@dataclass(frozen=True)
class Settings:
    app_env: str
    backend_host: str
    backend_port: int
    frontend_url: str
    database_url: str
    log_level: str
    storage_dir: Path
    max_upload_bytes: int

    @property
    def frontend_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_url.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    return Settings(
        app_env=_env("APP_ENV", "development"),
        backend_host=_env("BACKEND_HOST", "127.0.0.1"),
        backend_port=int(_env("BACKEND_PORT", "8000")),
        frontend_url=_env(
            "FRONTEND_URL",
            "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5174,http://localhost:5174",
        ),
        database_url=_env("DATABASE_URL", DEFAULT_DATABASE_URL),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        storage_dir=Path(_env("STORAGE_DIR", str(DEFAULT_STORAGE_DIR))),
        max_upload_bytes=int(_env("MAX_UPLOAD_BYTES", "26214400")),
    )
