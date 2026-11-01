"""Pre-build import check: verifies all project and third-party modules are importable."""

from pathlib import Path

import importlib
import sys
import traceback

# Add the project root (parent of tools/) to sys.path so project modules resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODULES = [
    # PySide6 core
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    "PySide6.QtPrintSupport",

    # matplotlib + Qt backend
    "matplotlib",
    "matplotlib.backends.backend_qtagg",
    "matplotlib.dates",

    # pandas / numpy
    "pandas",
    "numpy",

    # psutil
    "psutil",

    # Pillow
    "PIL",

    # Project modules — top-level
    "config",
    "bonsai_env",
    "charts_widgets",
    "agent_cost_collector",
    "app_controller",
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

    # Tabs package
    "tabs",
    "tabs.analytics_tab",
    "tabs.launch_tab",
    "tabs.monitor_tab",
    "tabs.settings_tab",
]

failed = []

for name in MODULES:
    try:
        importlib.import_module(name)
        print(f"OK   {name}")
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        traceback.print_exc()
        failed.append(name)

if failed:
    print("\nFailed modules:")
    for name in failed:
        print(f" - {name}")
    sys.exit(1)

print("\nAll checked imports are OK.")
