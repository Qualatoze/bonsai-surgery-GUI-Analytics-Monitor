"""Runtime hook for PyInstaller frozen execution.

Fixes common issues with matplotlib/Qt in onedir builds:
- MPLBACKEND not set → matplotlib falls back to Agg (no Qt)
- QT_API not set → wrong Qt binding selected
- Qt platform plugin not found → GUI crashes on startup
- DLL search path missing → shiboken6 / PySide6 native libs fail to load
"""

import os
import sys
from pathlib import Path


def _set_if_absent(name: str, value: str) -> None:
    if not os.environ.get(name):
        os.environ[name] = value


if getattr(sys, "frozen", False):
    # matplotlib backend — must be set before any matplotlib import
    _set_if_absent("MPLBACKEND", "QtAgg")

    # Qt API binding
    _set_if_absent("QT_API", "pyside6")

    # Help find the Qt platform plugin if the standard mechanism fails.
    # In onedir builds, plugins live under _internal/PySide6/plugins/platforms/
    if "QT_QPA_PLATFORM_PLUGIN_PATH" not in os.environ:
        exe_dir = Path(sys.executable).resolve().parent

        candidates = [
            exe_dir / "_internal" / "PySide6" / "plugins" / "platforms",
            exe_dir / "PySide6" / "plugins" / "platforms",
            getattr(sys, "_MEIPASS", None) and Path(sys._MEIPASS) / "PySide6" / "plugins" / "platforms",
        ]

        for cand in candidates:
            if cand is not None and cand.exists():
                _set_if_absent("QT_QPA_PLATFORM_PLUGIN_PATH", str(cand))
                break

    # Windows DLL search path — PyInstaller onedir puts native libs in _internal/
    if hasattr(os, "add_dll_directory"):
        exe_dir = Path(sys.executable).resolve().parent

        dll_candidates = [
            exe_dir / "_internal",
            exe_dir / "_internal" / "PySide6",
            exe_dir / "bin",
        ]

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dll_candidates.insert(0, Path(meipass))
            dll_candidates.insert(1, Path(meipass) / "PySide6")

        for dll_dir in dll_candidates:
            if dll_dir.exists():
                try:
                    os.add_dll_directory(str(dll_dir))
                except Exception:
                    pass
