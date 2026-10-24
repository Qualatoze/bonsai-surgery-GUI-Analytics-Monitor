# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Bonsai 2 Control Panel.

Build:   pyinstaller --clean bonsai.spec
Output:  dist/BonsaiControlPanel/BonsaiControlPanel.exe
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Matplotlib needs its mpl-data (fonts, style files) at runtime.
matplotlib_datas = collect_data_files("matplotlib")
# Pillow needs its image format plugins.
pil_datas = collect_data_files("PIL")

hiddenimports = [
    # --- Pillow (root cause of the ModuleNotFoundError) ---
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageColor",
    "PIL.ImageFilter",
    "PIL.PngImagePlugin",
    "PIL.JpegImagePlugin",
    "PIL._imaging",
    "PIL._tkinter_finder",

    # --- matplotlib backends ---
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_agg",

    # --- pandas timestamps (PyInstaller misses these on some builds) ---
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.period",
    "pandas._libs.tslibs.dtypes",
    "pandas._libs.tslibs.offsets",
    "pandas._libs.tslibs.base",

    # --- PySide6 (explicit, safer) ---
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",

    # --- misc ---
    "psutil",
]

# pynvml is optional (GPU metrics fallback)
try:
    import pynvml  # noqa: F401
    hiddenimports.append("pynvml")
except ImportError:
    pass

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=matplotlib_datas + pil_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib.backends.backend_tkagg",
        "matplotlib.backends._backend_tk",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,          # one-file mode: all binaries embedded in the single .exe
    [],
    exclude_binaries=False,
    name="BonsaiControlPanel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,       # UPX disabled: it corrupts the build (verified A/B)
    console=False,  # production: no console window (UPX disabled — verified A/B)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# (COLLECT removed: one-file build — no folder output anymore)
