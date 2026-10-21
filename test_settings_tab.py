"""Smoke-test вкладки настроек (SettingsTab): запуск, загрузка значений, сохранение, сигналы."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# Оффскрин-платформа: тест не требует дисплея и не блокируется модалками.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).parent))

# Robust output encoding for Windows consoles (cp1251 lacks some symbols).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("=" * 60)
print("SETTINGS TAB SMOKE TEST")
print("=" * 60)

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


def _store_row_count(db_path: str | Path) -> int:
    """Количество строк в settings_history."""
    with sqlite3.connect(str(db_path)) as c:
        return c.execute("SELECT COUNT(*) FROM settings_history").fetchone()[0]


def _click(btn) -> None:
    """Headless-safe click. On offscreen, btn.clicked() raises TypeError;
    QMetaObject.invokeMethod works in both cases."""
    try:
        btn.clicked()
    except TypeError:
        QMetaObject.invokeMethod(btn, "clicked")


# ---------------------------------------------------------------------------
# Тестовая инфраструктура
# ---------------------------------------------------------------------------
tmp_dir = Path(tempfile.mkdtemp(prefix="bonsai_settings_test_"))
tmp_settings_path = tmp_dir / "settings.json"
tmp_stats_db = tmp_dir / "stats.db"

from PySide6.QtCore import QObject, Signal, QMetaObject  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QMessageBox, QColorDialog, QCheckBox, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox,
)

from config import AppConfig  # noqa: E402
from i18n import t  # noqa: E402
from stats_store import StatsStore  # noqa: E402
from tabs.settings_tab import SettingsTab  # noqa: E402


class FakeCollector:
    """Замена StatsCollector: только set_interval."""

    def __init__(self) -> None:
        self.intervals: list[int] = []

    def set_interval(self, seconds: int) -> None:
        self.intervals.append(seconds)


class FakeController(QObject):
    """Минимальный дубль AppController для SettingsTab."""

    settings_saved = Signal()

    def __init__(self, cfg: AppConfig, store: StatsStore, collector: FakeCollector) -> None:
        super().__init__()
        self.cfg = cfg
        self.store = store
        self.collector = collector
        self.theme_calls: list[str] = []
        self.lang_calls: list[str] = []
        self.saved_count = 0
        self.settings_saved.connect(self._on_settings_saved)

    def _on_settings_saved(self) -> None:
        self.saved_count += 1

    def set_theme(self, theme_name: str) -> None:
        self.theme_calls.append(theme_name)

    def set_language(self, lang_code: str) -> None:
        self.lang_calls.append(lang_code)


# ---------------------------------------------------------------------------
# Тест 1: импорты
# ---------------------------------------------------------------------------
print("\n[TEST 1] Module imports")
check("PySide6 import", True)
check("config import (AppConfig)", AppConfig is not None)
check("i18n import (t)", t("settings.save") != "settings.save")
try:
    from theme import THEMES  # noqa: F401,E402
    check("theme import (THEMES)", len(THEMES) >= 7, f"got {len(THEMES)}")
except Exception as e:
    check("theme import (THEMES)", False, str(e))
try:
    from widgets import SectionTitle  # noqa: F401,E402
    check("widgets import (SectionTitle)", SectionTitle is not None)
except Exception as e:
    check("widgets import (SectionTitle)", False, str(e))

# ---------------------------------------------------------------------------
# Тест 2: запуск вкладки (QApplication + SettingsTab без краша)
# ---------------------------------------------------------------------------
print("\n[TEST 2] Launching SettingsTab")

app = QApplication(sys.argv)
check("QApplication created", app is not None)

cfg = AppConfig()
cfg.settings_path = str(tmp_settings_path)
cfg.stats_db_path = str(tmp_stats_db)
store = StatsStore(tmp_stats_db)
collector = FakeCollector()
controller = FakeController(cfg, store, collector)

tab_ok = False
try:
    tab = SettingsTab(controller)
    tab_ok = True
except Exception as e:
    import traceback
    print(f"  CRASH creating SettingsTab:\n{traceback.format_exc()}")
    check("SettingsTab instantiation", False, str(e))

check("SettingsTab instantiated without crash", tab_ok)

if not tab_ok:
    sys.exit(1)

# ---------------------------------------------------------------------------
# Тест 3: все виджеты вкладки на месте
# ---------------------------------------------------------------------------
print("\n[TEST 3] All widgets present")

expected_widgets = {
    "price_input_edit": QLineEdit,
    "price_output_edit": QLineEdit,
    "price_cached_edit": QLineEdit,
    "theme_combo": QComboBox,
    "data_path_edit": QLineEdit,
    "api_key_edit": QLineEdit,
    "api_endpoint_edit": QLineEdit,
    "models_dir_edit": QLineEdit,
    "llama_exe_edit": QLineEdit,
    "refresh_spin": QSpinBox,
    "gran_combo": QComboBox,
    "lang_combo": QComboBox,
    "accent_label": QLabel,
    "stats_db_edit": QLineEdit,
    "retention_spin": QSpinBox,
    "sample_interval_spin": QSpinBox,
    "start_perf_check": QCheckBox,
}

for name, wtype in expected_widgets.items():
    w = getattr(tab, name, None)
    check(f"widget {name}", isinstance(w, wtype), f"type={type(w)}")

sections = tab.findChildren(SectionTitle)
check("section titles present (>=5)", len(sections) >= 5, f"got {len(sections)}")

save_btn = None
for b in tab.findChildren(QPushButton):
    if b.property("role") == "primary":
        save_btn = b
check("primary save button found", save_btn is not None)

# ---------------------------------------------------------------------------
# Тест 4: значения из cfg загружены в UI
# ---------------------------------------------------------------------------
print("\n[TEST 4] Values loaded from config into UI")

cfg.price_input_per_1m = 0.25
cfg.price_output_per_1m = 3.5
cfg.price_cached_input_per_1m = 0.07
cfg.theme_name = "nord"
cfg.language = "ru"
cfg.refresh_interval_s = 5
cfg.chart_granularity = "weekly"
cfg.stats_retention_days = 90
cfg.sample_interval_s = 20
cfg.start_in_performance_mode = True
cfg.accent_color = "#FF7675"

tab = SettingsTab(controller)

# Перезахват кнопки Save для новой вкладки (старая удалена GC).
save_btn = next(
    b for b in tab.findChildren(QPushButton) if b.property("role") == "primary"
)
check("primary save button found on new tab", save_btn is not None)

check("price input loaded", tab.price_input_edit.text() == "0.25")
check("price output loaded", tab.price_output_edit.text() == "3.5")
check("price cached loaded", tab.price_cached_edit.text() == "0.07")
check("theme loaded (nord)", tab.theme_combo.currentData() == "nord")
check("language loaded (ru)", tab.lang_combo.currentData() == "ru")
check("refresh spin loaded", tab.refresh_spin.value() == 5)
check("granularity loaded (weekly)", tab.gran_combo.currentText() == "weekly")
check("retention spin loaded", tab.retention_spin.value() == 90)
check("sample interval loaded", tab.sample_interval_spin.value() == 20)
check("perf check loaded", tab.start_perf_check.isChecked())
check("accent label loaded", tab.accent_label.text() == "#FF7675")

# ---------------------------------------------------------------------------
# Тест 5: сохранение — значения пишутся в settings.json и cfg
# ---------------------------------------------------------------------------
print("\n[TEST 5] Save flow (settings_saved, collector, store, settings.json)")

before_rows = _store_row_count(tmp_stats_db)

tab.price_input_edit.setText("1.25")
tab.price_output_edit.setText("4.75")
tab.price_cached_edit.setText("0.1")
tab.theme_combo.setCurrentIndex(tab.theme_combo.findData("tokyo_night"))
tab.lang_combo.setCurrentIndex(tab.lang_combo.findData("en"))
tab.data_path_edit.setText(str(tmp_dir / "data.csv"))
tab.api_endpoint_edit.setText("http://localhost:9000/v1")
tab.refresh_spin.setValue(7)
tab.gran_combo.setCurrentText("monthly")
tab.retention_spin.setValue(365)
tab.sample_interval_spin.setValue(30)
tab.start_perf_check.setChecked(False)

_click(save_btn)

check("settings_saved signal emitted", controller.saved_count > 0,
      f"saved_count={controller.saved_count}")
check("collector.set_interval called with 30", collector.intervals == [30],
      f"got {collector.intervals}")
check("store.insert_settings called (row count +1)", _store_row_count(tmp_stats_db) == before_rows + 1,
      f"before={before_rows}, after={_store_row_count(tmp_stats_db)}")

saved_cfg = json.loads(tmp_settings_path.read_text(encoding="utf-8"))
check("settings.json written", tmp_settings_path.exists())
check("price input saved (1.25)", abs(saved_cfg.get("price_input_per_1m", 0) - 1.25) < 1e-9)
check("price output saved (4.75)", abs(saved_cfg.get("price_output_per_1m", 0) - 4.75) < 1e-9)
check("price cached saved (0.1)", abs(saved_cfg.get("price_cached_input_per_1m", 0) - 0.1) < 1e-9)
check("theme saved (tokyo_night)", saved_cfg.get("theme_name") == "tokyo_night")
check("language saved (en)", saved_cfg.get("language") == "en")
check("data_path saved", saved_cfg.get("data_path") == str(tmp_dir / "data.csv"))
check("api_endpoint saved", saved_cfg.get("api_endpoint") == "http://localhost:9000/v1")
check("refresh_interval_s saved (7)", saved_cfg.get("refresh_interval_s") == 7)
check("chart_granularity saved (monthly)", saved_cfg.get("chart_granularity") == "monthly")
check("stats_retention_days saved (365)", saved_cfg.get("stats_retention_days") == 365)
check("sample_interval_s saved (30)", saved_cfg.get("sample_interval_s") == 30)
check("start_in_performance_mode saved (false)", saved_cfg.get("start_in_performance_mode") is False)

# cfg в памяти тоже обновлён
check("cfg.theme_name updated", controller.cfg.theme_name == "tokyo_night")
check("cfg.sample_interval_s updated", controller.cfg.sample_interval_s == 30)

# ---------------------------------------------------------------------------
# Тест 6: валидация — невалидный api_endpoint блокирует сохранение
# ---------------------------------------------------------------------------
print("\n[TEST 6] Validation blocks save on bad api_endpoint")

critical_calls = []

def _fake_critical(*args, **kwargs):
    critical_calls.append(args)

QMessageBox.critical = _fake_critical

tab.api_endpoint_edit.setText("not-a-url")
_click(save_btn)

check("QMessageBox.critical shown for validation", len(critical_calls) >= 1,
      f"got {critical_calls}")
check("settings.json not rewritten (endpoint still valid)",
      json.loads(tmp_settings_path.read_text(encoding="utf-8")).get("api_endpoint") == "http://localhost:9000/v1")

# ---------------------------------------------------------------------------
# Тест 7: нечисловые цены не ломают сохранение (fallback 0.0)
# ---------------------------------------------------------------------------
print("\n[TEST 7] Non-numeric prices fall back to 0.0 without crash")

# TEST 6 left api_endpoint invalid; restore it so this test isolates price handling.
tab.api_endpoint_edit.setText("http://localhost:9000/v1")
tab.price_input_edit.setText("abc")
tab.price_output_edit.setText("")
tab.price_cached_edit.setText("1e999")
_click(save_btn)

check("no validation error for bad prices", len(critical_calls) == 1,
      f"critical calls={len(critical_calls)} (expected only the one from TEST 6)")
saved_cfg = json.loads(tmp_settings_path.read_text(encoding="utf-8"))
check("price input fallback 0.0", saved_cfg.get("price_input_per_1m") == 0.0)
check("price output fallback 0.0", saved_cfg.get("price_output_per_1m") == 0.0)

# ---------------------------------------------------------------------------
# BUG 5: _parse_price clamps to [0.0, 1e6]
check("BUG 5: negative price clamped to 0.0",
      SettingsTab._parse_price("-5.0") == 0.0)
check("BUG 5: huge price clamped to 1e6",
      abs(SettingsTab._parse_price("9999999999") - 1e6) < 1e-9)
check("BUG 5: normal price passes through",
      SettingsTab._parse_price("3.14") == 3.14)
check("BUG 5: empty string returns 0.0",
      SettingsTab._parse_price("") == 0.0)
check("BUG 5: inf returns 0.0",
      SettingsTab._parse_price("inf") == 0.0)

# Тест 8: смена темы/языка через комбо — сигналы контроллера
# ---------------------------------------------------------------------------
print("\n[TEST 8] Theme / language combo changes notify controller")

controller.theme_calls.clear()
controller.lang_calls.clear()

tab.theme_combo.setCurrentIndex(tab.theme_combo.findData("dracula"))
check("set_theme called with dracula", controller.theme_calls == ["dracula"],
      f"got {controller.theme_calls}")

tab.lang_combo.setCurrentIndex(tab.lang_combo.findData("cn"))
check("set_language called with cn", controller.lang_calls == ["cn"],
      f"got {controller.lang_calls}")

# ---------------------------------------------------------------------------
# Тест 9: выбор цвета акцента (QColorDialog заглушен)
# ---------------------------------------------------------------------------
print("\n[TEST 9] Accent color picker")

picked = {"color": None}

def _fake_get_color(*args, **kwargs):
    picked["color"] = QColor("#00D2FF")
    return picked["color"]

QColorDialog.getColor = _fake_get_color

for b in tab.findChildren(QPushButton):
    if b.text() == t("settings.pick_color_btn"):
        _click(b)
        break

check("accent label updated after picker (case-insensitive)",
      tab.accent_label.text().lower() == "#00d2ff",
      f"got {tab.accent_label.text()}")

# ---------------------------------------------------------------------------
# Итоги
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} tests PASSED")
if failed > 0:
    print(f"FAILED: {failed}")
    sys.exit(1)
else:
    print("ALL TESTS PASSED ✓")
sys.exit(0)
