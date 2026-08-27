from __future__ import annotations

from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[3]


def bundled_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    return Path(frozen_root) if frozen_root else SOURCE_ROOT


def bundled_path(*parts: str) -> Path:
    return bundled_root().joinpath(*parts)
