# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Bonsai Control Panel — onedir Windows x64 build."""

import os
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    copy_metadata,
)

# ------------------------------------------------------------------
# Settings via environment variables
# ------------------------------------------------------------------
APP_NAME = os.environ.get("BONSAI_APP_NAME", "Bonsai")
ENTRY = os.environ.get("BONSAI_ENTRY", "main.py")
CONSOLE = os.environ.get("BONSAI_CONSOLE", "0") == "1"

entry_path = Path(ENTRY)
if not entry_path.exists():
    candidates = [
        Path("main.py"),
        Path("app.py"),
        Path("bonsai.py"),
        Path("run.py"),
        Path("src/main.py"),
        Path("src/app.py"),
    ]
    found = None
    for c in candidates:
        if c.exists():
            found = c
            break
    if found is None:
        raise SystemExit(
            f"Entry point not found: {ENTRY}. "
            f"Set BONSAI_ENTRY or edit bonsai.spec."
        )
    entry_path = found

ENTRY = str(entry_path)

# ------------------------------------------------------------------
# Path configuration
# ------------------------------------------------------------------
pathex = [str(Path.cwd())]

if entry_path.parent.resolve() != Path.cwd().resolve():
    pathex.append(str(entry_path.parent.resolve()))

src_dir = Path("src")
if src_dir.is_dir():
    pathex.append(str(src_dir.resolve()))

# ------------------------------------------------------------------
# Data / binaries / hidden imports collection
# ------------------------------------------------------------------
datas = []
binaries = []
hiddenimports = []


def add_collect_all(pkg: str) -> None:
    global datas, binaries, hiddenimports
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
        print(f"[spec] collect_all({pkg}) OK")
    except Exception as exc:
        print(f"[spec] collect_all({pkg}) skipped: {exc}")


# Heavy packages — full collection for data + binaries + hidden imports
for pkg in [
    "matplotlib",
    "pandas",
    "psutil",
    "PIL",
    "dateutil",
    "pytz",
    "packaging",
    "pyparsing",
    "cycler",
    "kiwisolver",
]:
    add_collect_all(pkg)

# ------------------------------------------------------------------
# PySide6 — only required modules (skip WebEngine/3D/etc.)
# ------------------------------------------------------------------
pyside_modules = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    "PySide6.QtPrintSupport",
    "PySide6.QtConcurrent",
]

hiddenimports += pyside_modules

try:
    datas += collect_data_files("PySide6")
except Exception as exc:
    print(f"[spec] collect_data_files(PySide6) skipped: {exc}")

for dist_name in ["PySide6", "PySide6-Essentials", "PySide6-Addons"]:
    try:
        datas += copy_metadata(dist_name)
    except Exception:
        pass

# ------------------------------------------------------------------
# Project modules (hidden imports for safety)
# ------------------------------------------------------------------
project_modules = [
    "agent_cost_collector",
    "app_controller",
    "bonsai_env",
    "charts_widgets",
    "config",
    "data_loader",
    "i18n",
    "layer_manager",
    "main_window",
    "presets",
    "resource_monitor",
    "server_manager",
    "spill_guard",
    "stats_collector",
    "stats_store",
    "theme",
    "tray_icon",
    "widgets",
]

hiddenimports += project_modules

# Tabs package
hiddenimports += [
    "tabs",
    "tabs.analytics_tab",
    "tabs.launch_tab",
    "tabs.monitor_tab",
    "tabs.settings_tab",
]

# ------------------------------------------------------------------
# Standard library and service modules
# ------------------------------------------------------------------
hiddenimports += [
    "csv",
    "ctypes",
    "ipaddress",
    "json",
    "logging",
    "logging.handlers",
    "socket",
    "sqlite3",
    "subprocess",
    "urllib.request",
]

# ------------------------------------------------------------------
# matplotlib Qt backend — critical for charts
# ------------------------------------------------------------------
hiddenimports += [
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_agg",
    "matplotlib.dates",
    "matplotlib.ticker",
    "matplotlib.legend",
    "matplotlib.text",
    "matplotlib.colors",
]

# ------------------------------------------------------------------
# pandas/numpy C extensions (hidden imports for PyInstaller)
# ------------------------------------------------------------------
hiddenimports += [
    "numpy.core._multiarray_umath",
    "numpy.core._dtype",
    "pandas._libs.tslibs.base",
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.c_timestamp",
]

# ------------------------------------------------------------------
# PySide6 / shiboken
# ------------------------------------------------------------------
hiddenimports += [
    "shiboken6",
    "shiboken6.shiboken",
]

# ------------------------------------------------------------------
# Windows-specific
# ------------------------------------------------------------------
hiddenimports += [
    "psutil._pswindows",
]

# ------------------------------------------------------------------
# Excludes — remove unnecessary packages to reduce size
# ------------------------------------------------------------------
excludes = [
    "PyQt5",
    "PyQt6",
    "PySide2",
    "pytest",
    "IPython",
    "jupyter",
    "notebook",
    "tkinter",
]

# ------------------------------------------------------------------
# Optional local resource directories (pack if they exist)
# ------------------------------------------------------------------
optional_resource_dirs = [
    "assets",
    "i18n",
    "themes",
    "resources",
]

for d in optional_resource_dirs:
    p = Path(d)
    if p.is_dir():
        datas.append((d, d))
        print(f"[spec] adding local resource dir: {d}")

# ------------------------------------------------------------------
# Runtime hook
# ------------------------------------------------------------------
runtime_hooks = []
if Path("hook-runtime.py").exists():
    runtime_hooks.append("hook-runtime.py")

# ------------------------------------------------------------------
# Icon and version info (optional)
# ------------------------------------------------------------------
icon_file = None
for candidate in [
    "assets/icon.ico",
    "resources/icon.ico",
    "icon.ico",
]:
    if Path(candidate).exists():
        icon_file = candidate
        break

version_file = None
for candidate in [
    "version_info.txt",
    "version.txt",
]:
    if Path(candidate).exists():
        version_file = candidate
        break

# ------------------------------------------------------------------
# Deduplicate hidden imports
# ------------------------------------------------------------------
hiddenimports = sorted(set(hiddenimports))

# ------------------------------------------------------------------
# PyInstaller Analysis
# ------------------------------------------------------------------
a = Analysis(
    [ENTRY],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=runtime_hooks,
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    icon=icon_file,
    version=version_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
