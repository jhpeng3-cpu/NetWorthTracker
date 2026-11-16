# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

构建：
    pyinstaller NetWorthTracker.spec --noconfirm

输出：
    dist/NetWorthTracker/NetWorthTracker.exe

Alembic 迁移脚本通过 datas 打包进应用，运行时可从 _MEIPASS 找到。
config.ini 与 networth.log 会生成在 exe 所在目录。
图表使用 Qt 原生绘制，不再打包 matplotlib/numpy/Pillow。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_dir = Path(SPECPATH)
hiddenimports = collect_submodules("alembic") + [
    "logging.config",
    "logging.handlers",
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
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "matplotlib",
        "numpy",
        "PIL",
        "cryptography",
        "contourpy",
        "kiwisolver",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtNetwork",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
    ],
    noarchive=False,
    optimize=0,
)

# ---- 精简 Qt 运行时：只保留 Widgets 所需组件 ----
_KEEP_QT_DLLS = {"qt6core.dll", "qt6gui.dll", "qt6widgets.dll"}
_KEEP_PYDS = {"qtcore.pyd", "qtgui.pyd", "qtwidgets.pyd"}
_KEEP_PLUGINS = (
    "/platforms/qwindows.dll",
    "/styles/",
    "/imageformats/qico.dll",
)


def _normalized(name: str) -> str:
    return name.replace("\\", "/").lower()


def _keep_binary(dest: str) -> bool:
    path = "/" + _normalized(dest)
    filename = path.rsplit("/", 1)[-1]
    if filename == "opengl32sw.dll":
        return False
    if "/pyside6/qt6" in path and path.endswith(".dll"):
        return filename in _KEEP_QT_DLLS
    if "/pyside6/qt" in path and path.endswith(".pyd"):
        return filename in _KEEP_PYDS
    if "/pyside6/plugins/" in path:
        return any(marker in path for marker in _KEEP_PLUGINS)
    if "/pyside6/translations/" in path or "/pyside6/qml/" in path:
        return False
    return True


def _keep_data(dest: str) -> bool:
    path = _normalized(dest)
    return not (
        "/pyside6/translations/" in path
        or "/pyside6/qml/" in path
        or path.startswith("pyside6/translations/")
        or path.startswith("pyside6/qml/")
    )


a.binaries = [entry for entry in a.binaries if _keep_binary(entry[0])]
a.datas = [entry for entry in a.datas if _keep_data(entry[0])]

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
