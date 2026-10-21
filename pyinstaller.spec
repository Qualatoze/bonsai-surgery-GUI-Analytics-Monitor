# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Bonsai 2 27B Control Panel.

BUG 7 fix: bin/ and models/ are NOT bundled into _internal/.
They must be placed next to the .exe (user copies them manually or
the installer does it). The app resolves paths relative to sys.executable
when frozen, so it finds them there.

Build command:
    pyinstaller --onefile bonsai GUI/pyinstaller.spec
"""

from PyInstaller.utils.hooks import collect_data_files
import os

# --- Collect only lightweight data files (themes, i18n, etc.) ---
# Do NOT include bin/ or models/ — they are large and belong next to the exe.
project_root = os.path.dirname(os.path.abspath(__file__))

# Data files that ARE safe to bundle (small config/theme assets)
bundled_data = []
for root, dirs, files in os.walk(project_root):
    # Skip bin/, models/, artifacts/ — these go next to the exe
    rel = os.path.relpath(root, project_root)
    if any(part in ("bin", "models", "artifacts") for part in rel.split(os.sep)):
        dirs[:] = [d for d in dirs if d not in ("bin", "models", "artifacts")]
        continue
    for f in files:
        if f.endswith((".pyc", ".pyo")) or f.startswith("_"):
            continue
        full = os.path.join(root, f)
        relf = os.path.relpath(full, project_root)
        # Only bundle small text/config assets (< 1 MB)
        if os.path.getsize(full) < 1_048_576 and not f.endswith((".gguf", ".dll", ".exe")):
            bundled_data.append((relf, relf))

# --- Hidden imports for PySide6 + optional deps ---
hiddenimports = [
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "pandas._libs.lib",
    "matplotlib.backends.backend_agg",
]

# Optional: pynvml for NVML fallback (skip if not installed)
try:
    import nvidia_ml_py  # noqa: F401
    hiddenimports.append("nvidia_ml_py")
except ImportError:
    pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=bundled_data,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['pyinstaller', 'PIL', 'tkinter'],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts + a.binaries,
    [],
    exclude_binaries=True,
    name='bonsai_gui',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)

# BUG 7: onedir mode — _internal/ holds only bundled data.
# bin/ and models/ must be placed NEXT TO the exe by the user/installer.
coll = COLLECTEXE(
    exe,
    a.binaries + a.datas,
    strip=False,
    upx=True,
    name='bonsai_gui',
)
