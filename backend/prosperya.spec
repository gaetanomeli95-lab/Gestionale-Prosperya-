# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Prosperya Preview desktop build.

Produces a onedir bundle: dist/Prosperya/Prosperya.exe + _internal/.
Bundles: FastAPI backend, frontend production build, Alembic migrations,
pywebview (Edge WebView2) for the native window.

Build:  ..\\.venv\\Scripts\\pyinstaller.exe prosperya.spec --clean --noconfirm
Set PROSPERYA_CONSOLE=1 to build with a console for debugging.
"""
import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve()                  # backend/ (spec lives here)
REPO = ROOT.parent                               # repo root
CONSOLE = os.environ.get("PROSPERYA_CONSOLE") == "1"

datas = [
    (str(REPO / "frontend" / "dist"), "frontend_dist"),
    (str(ROOT / "alembic"), "alembic"),
]

hiddenimports = [
    "app.models_all",
    # uvicorn[standard] extras
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.loops.asyncio",
    "httptools",
    "websockets",
    "watchfiles",
    # auth / validation
    "argon2",
    "argon2.low_level",
    "_cffi_backend",
    "email_validator",
    # native window (pywebview → Edge WebView2 via pythonnet/winforms)
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr_loader",
    "pythonnet",
    "proxy_tools",
    "bottle",
]

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff", "psycopg", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Prosperya",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    disable_windowed_traceback=False,
    icon=str(ROOT / "scripts" / "prosperya.ico"),
    version=str(ROOT / "scripts" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Prosperya",
)
