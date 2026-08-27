from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


PRODUCT_NAME = "Personal Finance Manager"
HOST = "127.0.0.1"
PREFERRED_PORT = 8765


def _message(title: str, body: str, *, error: bool = False) -> None:
    if os.name == "nt":
        flags = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(None, body, title, flags)
    else:
        print(f"{title}: {body}", file=sys.stderr if error else sys.stdout)


def _mutex_is_duplicate() -> tuple[bool, object | None]:
    if os.name != "nt":
        return False, None
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PersonalFinanceManager-9A57B1D0")
    return ctypes.windll.kernel32.GetLastError() == 183, handle


def _state_path() -> Path:
    base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "PersonalFinanceManager" / "config" / "running.json"


def _health(port: int, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health/app", timeout=timeout) as response:
            data = json.loads(response.read())
        return data.get("app_id") == "personal-finance-manager" and data.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _existing_port() -> int | None:
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        port = int(state["port"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    return port if _health(port) else None


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
            return True
        except OSError:
            return False


def _select_port() -> int:
    if _port_available(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def _open_when_ready(port: int) -> None:
    for _ in range(120):
        if _health(port):
            webbrowser.open(f"http://{HOST}:{port}/")
            return
        time.sleep(0.25)
    _message(PRODUCT_NAME, "The application did not become ready. See the Maintenance logs for details.", error=True)


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--prepare-update":
        os.environ["APP_ENV"] = "production"
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("STORAGE_DIR", None)
        from app.core.config import get_settings
        from app.services.maintenance.backups import create_backup, validate_backup
        from app.services.maintenance.startup import initialize_directories

        settings = get_settings()
        initialize_directories(settings)
        if settings.database_path and settings.database_path.exists():
            target = sys.argv[2] if len(sys.argv) >= 3 else "next"
            backup = create_backup(kind="automatic", label=f"pre-update-to-{target}", settings=settings)
            validate_backup(backup)
        return 0

    duplicate, mutex = _mutex_is_duplicate()
    if duplicate:
        port = _existing_port()
        if port:
            webbrowser.open(f"http://{HOST}:{port}/")
        else:
            _message(PRODUCT_NAME, "The application is already starting. Please wait a moment and try again.")
        return 0

    os.environ["APP_ENV"] = "production"
    os.environ["BACKEND_HOST"] = HOST
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("STORAGE_DIR", None)
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.services.maintenance.startup import prepare_application

    settings = get_settings()
    configure_logging()
    if not settings.frontend_dist_dir.joinpath("index.html").is_file():
        _message(PRODUCT_NAME, "Required application files are missing. Reinstall the application.", error=True)
        return 1
    try:
        prepare_application(settings)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).exception("Safe startup preparation failed")
        _message(
            PRODUCT_NAME,
            f"The application could not start safely. Your existing data was preserved.\n\n{exc}\n\nSee the logs folder for details.",
            error=True,
        )
        return 1

    port = _select_port()
    state_path = _state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()
    try:
        import uvicorn

        uvicorn.run("app.main:app", host=HOST, port=port, reload=False, log_config=None, access_log=False)
        return 0
    except Exception as exc:
        _message(PRODUCT_NAME, f"The application could not start.\n\n{exc}", error=True)
        return 1
    finally:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("pid") == os.getpid():
                state_path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass
        _ = mutex


if __name__ == "__main__":
    raise SystemExit(main())
