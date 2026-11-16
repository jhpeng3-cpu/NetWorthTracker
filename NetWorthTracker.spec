# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

构建：
    pyinstaller NetWorthTracker.spec --noconfirm

输出：
    dist/NetWorthTracker/NetWorthTracker.exe

Alembic 迁移脚本通过 datas 打包进应用，运行时可从 _MEIPASS 找到。
config.ini 与 networth.log 会生成在 exe 所在目录。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_dir = Path(SPECPATH)
hiddenimports = collect_submodules("alembic") + [
    "logging.config",
    "logging.handlers",
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_qt",
]

a = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[
        (str(project_dir / "alembic"), "alembic"),
        (str(project_dir / "alembic.ini"), "."),
        (str(project_dir / "app" / "ui" / "assets"), "app/ui/assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NetWorthTracker",
    icon=str(project_dir / "app" / "ui" / "assets" / "app.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NetWorthTracker",
)
