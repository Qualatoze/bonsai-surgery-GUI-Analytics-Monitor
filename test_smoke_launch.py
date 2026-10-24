"""Smoke-test запуска main.py после фикса addLayout (ContextKvRow).

Проверяет:
 1) синтаксис всех файлов проекта (compile());
 2) импорт модулей UI;
 3) запуск main.py в offscreen-режиме без исключений.

Запуск: python test_smoke_launch.py
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Offscreen ДО импорта Qt — иначе платформа уже выбрана.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


# ---------------------------------------------------------------------------
# Test 1: синтаксис всех файлов проекта (top-level + tabs/)
# ---------------------------------------------------------------------------
print("\n[TEST 1] Syntax check")
files = sorted(glob.glob(str(ROOT / "*.py"))) + \
        sorted(glob.glob(str(ROOT / "tabs" / "*.py")))

try:
    for f in files:
        compile(Path(f).read_text(encoding="utf-8"), f, "exec")
except SyntaxError as e:
    check("compile all project files", False, str(e))
else:
    check(f"compiled {len(files)} files without errors", True)

# ---------------------------------------------------------------------------
# Test 2: импорт модулей UI (после фикса не должно падать на импорте)
# ---------------------------------------------------------------------------
print("\n[TEST 2] Module imports")
try:
    import main_window  # noqa: F401
    check("import main_window", True)
except Exception as e:
    check("import main_window", False, str(e))

try:
    from tabs.launch_tab import LaunchTab  # noqa: F401
    check("import tabs.launch_tab.LaunchTab", True)
except Exception as e:
    check("import tabs.launch_tab.LaunchTab", False, str(e))


# ---------------------------------------------------------------------------
# Test 3: запуск main.py в offscreen-режиме (GUI должен дожить до event loop)
# ---------------------------------------------------------------------------
print("\n[TEST 3] Launching main.py (offscreen)")

env = os.environ.copy()
env["QT_QPA_PLATFORM"] = "offscreen"
env.setdefault("PYTHONIOENCODING", "utf-8")

proc = subprocess.Popen(
    [sys.executable, str(ROOT / "main.py")],
    cwd=str(ROOT), env=env,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, encoding="utf-8", errors="replace",
)

try:
    rc = proc.wait(timeout=10)  # дожились либо краша, либо живого процесса 10 с
except subprocess.TimeoutExpired:
    rc = None  # процесс жил все 10 секунд — хороший знак (event loop запущен)

finally:
    if proc.poll() is None:
        proc.terminate()
    try:
        out, _ = proc.communicate(timeout=3) or ("", "")
    except subprocess.TimeoutExpired:
        out = ""

crashed = ("UNHANDLED EXCEPTION" in out) or ("Traceback" in out)
check(
    "main.py did not crash within first 10 seconds",
    not crashed,
    (out[-600:] if crashed else ""),
)
if rc is None:
    check("GUI event loop started up normally (process alive for 10s)", True)
else:
    check(f"unexpected exit code {rc}", False, out[-800:])

# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
total = passed + failed
if total == 0:
    print("No checks executed!")
elif failed == 0:
    print(f"All tests PASSED ({passed}/{total})")
else:
    print(f"{failed} of {total} tests FAILED")

sys.exit(1 if failed else 0)
