from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

from app.core.resources import SOURCE_ROOT, bundled_path

PROJECT_ROOT = SOURCE_ROOT


def _default_user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "PersonalFinanceManager"


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


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
    data_dir: Path
    backups_dir: Path
    logs_dir: Path
    config_dir: Path
    frontend_dist_dir: Path
    automatic_backup_retention: int

    @property
    def database_path(self) -> Path | None:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix) or self.database_url.endswith(":memory:"):
            return None
        return Path(self.database_url[len(prefix) :])

    @property
    def frontend_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_url.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    app_env = _env("APP_ENV", "development")
    production = app_env.lower() == "production"
    user_data_root = Path(_env("PFM_DATA_DIR", str(_default_user_data_dir()))).expanduser()
    data_dir = user_data_root / "data" if production else PROJECT_ROOT / "data"
    storage_dir = user_data_root / "storage" if production else PROJECT_ROOT / "storage" / "files"
    backups_dir = user_data_root / "backups" if production else PROJECT_ROOT / "backups"
    logs_dir = user_data_root / "logs" if production else PROJECT_ROOT / "logs"
    config_dir = user_data_root / "config" if production else PROJECT_ROOT / "config"

    return Settings(
        app_env=app_env,
        backend_host=_env("BACKEND_HOST", "127.0.0.1"),
        backend_port=int(_env("BACKEND_PORT", "8000")),
        frontend_url=_env(
            "FRONTEND_URL",
            "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5174,http://localhost:5174",
        ),
        database_url=_env("DATABASE_URL", _sqlite_url(data_dir / "finance.db" if production else data_dir / "app.db")),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        storage_dir=Path(_env("STORAGE_DIR", str(storage_dir))).expanduser(),
        max_upload_bytes=int(_env("MAX_UPLOAD_BYTES", "26214400")),
        data_dir=data_dir,
        backups_dir=Path(_env("BACKUPS_DIR", str(backups_dir))).expanduser(),
        logs_dir=Path(_env("LOGS_DIR", str(logs_dir))).expanduser(),
        config_dir=Path(_env("CONFIG_DIR", str(config_dir))).expanduser(),
        frontend_dist_dir=Path(_env("FRONTEND_DIST_DIR", str(bundled_path("frontend", "dist")))).expanduser(),
        automatic_backup_retention=max(1, int(_env("AUTOMATIC_BACKUP_RETENTION", "10"))),
    )
