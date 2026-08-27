from pathlib import Path

root = Path(SPECPATH).parent
backend = root / "backend"

a = Analysis(
    [str(backend / "app" / "launcher.py")],
    pathex=[str(backend)],
    binaries=[],
    datas=[
        (str(root / "frontend" / "dist"), "frontend/dist"),
        (str(backend / "migrations"), "backend/migrations"),
        (str(backend / "alembic.ini"), "backend"),
    ],
    hiddenimports=[
        "app.main",
        "app.db.base",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "app.models.folder",
        "app.models.file",
        "app.models.statement",
        "app.models.transaction",
        "app.models.infrastructure",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "httpx"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PersonalFinanceManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
