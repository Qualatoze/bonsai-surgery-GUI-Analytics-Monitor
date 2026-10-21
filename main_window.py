"""Главное окно: QTabWidget + toolbar + Performance Mode hooks."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QPushButton, QSizePolicy, QStatusBar,
    QTabWidget, QToolBar, QWidget,
)

from charts_widgets import apply_chart_theme
from tabs.analytics_tab import AnalyticsTab
from tabs.launch_tab import LaunchTab
from tabs.monitor_tab import MonitorTab
from tabs.settings_tab import SettingsTab
from i18n import t
from theme import apply_theme
from config import save_config


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.cfg = controller.cfg
        self.mgr = controller.mgr

        self.setWindowTitle("🌳 Bonsai 2 27B — Control Panel")
        self.resize(1400, 900)

        self._build_ui()
        self._build_toolbar()
        self._connect_signals()
        self._setup_hotkey()
        self._update_status()

    def _build_ui(self) -> None:
        self.tabs = QTabWidget()
        self.launch_tab = LaunchTab(self.controller)
        self.monitor_tab = MonitorTab(self.controller)
        self.analytics_tab = AnalyticsTab(self.controller)
        self.settings_tab = SettingsTab(self.controller)

        self.tabs.addTab(self.launch_tab, f"🚀 {t('tab.launch')}")
        self.tabs.addTab(self.monitor_tab, f"📊 {t('tab.monitor')}")
        self.tabs.addTab(self.analytics_tab, f"📈 {t('tab.analytics')}")
        self.tabs.addTab(self.settings_tab, f"⚙️ {t('tab.settings')}")
        self.setCentralWidget(self.tabs)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"API: {self.cfg.api_endpoint} · "
            f"DB: {self.cfg.stats_db_path} · "
            f"config: {self.cfg.settings_path}")

    def _recreate_tabs(self) -> None:
        """Rebuild all tabs after a language change so every label is re-translated."""
        # Capture launch-tab selection to restore after rebuild.
        model = getattr(self.launch_tab, "model_combo", None)
        model = model.currentData() if model is not None else None
        selected_model_name = model.name if model else None
        preset_idx = self.launch_tab.preset_combo.currentIndex()

        # BUG 13: don't overwrite last_launch with a partial dict during
        # language change. Only preserve model selection for restore.
        # (The full snapshot lives in LaunchTab._on_start.)

        # Stop monitor timer to avoid double timers during rebuild.
        if hasattr(self.monitor_tab, "_timer"):
            self.monitor_tab._timer.stop()

        # Remove all existing tabs (while-loop to avoid index shifting).
        while self.tabs.count() > 0:
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()

        # Recreate tabs (fresh labels in the new language).
        self.launch_tab = LaunchTab(self.controller)
        self.monitor_tab = MonitorTab(self.controller)
        self.analytics_tab = AnalyticsTab(self.controller)
        self.settings_tab = SettingsTab(self.controller)

        self.tabs.addTab(self.launch_tab, f"🚀 {t('tab.launch')}")
        self.tabs.addTab(self.monitor_tab, f"📊 {t('tab.monitor')}")
        self.tabs.addTab(self.analytics_tab, f"📈 {t('tab.analytics')}")
        self.tabs.addTab(self.settings_tab, f"⚙️ {t('tab.settings')}")

        # Restore launch selection.
        # FIX: block signals to prevent _on_preset_changed from re-applying the preset
        # (which would overwrite user's advanced settings during language change).
        if selected_model_name:
            self.launch_tab._pending_restore_model_name = selected_model_name
        if preset_idx >= 0 and preset_idx < self.launch_tab.preset_combo.count():
            self.launch_tab.preset_combo.blockSignals(True)
            self.launch_tab.preset_combo.setCurrentIndex(preset_idx)
            self.launch_tab.preset_combo.blockSignals(False)

        # Reconnect server_state_changed signal (new LaunchTab instance).
        self.launch_tab.server_state_changed.connect(self._on_server_changed)

    def _build_toolbar(self) -> None:
        tb = QToolBar("main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self.status_pill = QLabel("● —")
        self.status_pill.setStyleSheet(
            "padding: 4px 12px; border-radius: 6px; "
            "background: #16213e; color: #00D2FF; font-weight: 600;")
        tb.addWidget(self.status_pill)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        self.perf_btn = QPushButton("⚡ Performance Mode")
        self.perf_btn.setCheckable(True)
        if not self.controller.tray_available:
            self.perf_btn.setEnabled(False)
            self.perf_btn.setToolTip("Системный трей недоступен")
        else:
            self.perf_btn.setToolTip(
                "Скрыть GUI в трей. Ctrl+Shift+P. Сервер продолжит работу.")
            self.perf_btn.toggled.connect(
                self.controller.set_performance_mode)
        tb.addWidget(self.perf_btn)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status_pill)
        self._status_timer.start(2000)

    def _connect_signals(self) -> None:
        self.launch_tab.server_state_changed.connect(self._on_server_changed)
        self.controller.performance_mode_changed.connect(
            self._on_perf_mode_changed)
        self.controller.theme_changed.connect(self._on_theme_changed)
        self.controller.language_changed.connect(self._recreate_tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _on_theme_changed(self, theme_name: str) -> None:
        """Re-apply QSS, update matplotlib rcParams, and redraw all charts."""
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme_name)
        apply_chart_theme(theme_name)

        # Redraw all chart widgets with the new color scheme
        for tab in (self.analytics_tab, self.monitor_tab):
            for attr in ("trend_chart", "deep_chart", "heat_chart", "live_chart"):
                if hasattr(tab, attr):
                    getattr(tab, attr).set_theme(theme_name)

    def _setup_hotkey(self) -> None:
        if not self.controller.tray_available:
            return
        sc = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        sc.activated.connect(self.controller.toggle_performance_mode)

    def _on_server_changed(self) -> None:
        self._update_status()
        self.monitor_tab.refresh()

    def _on_perf_mode_changed(self, enabled: bool) -> None:
        self.perf_btn.blockSignals(True)
        self.perf_btn.setChecked(enabled)
        self.perf_btn.blockSignals(False)

        # Safety net: explicitly stop/start monitor timer (hideEvent/showEvent
        # may not fire if the window is already hidden/shown).
        if enabled:
            self.monitor_tab._timer.stop()
        else:
            self.monitor_tab.set_refresh_interval(self.cfg.refresh_interval_s)

    def _on_tab_changed(self, idx: int) -> None:
        w = self.tabs.widget(idx)
        if w is self.monitor_tab:
            self.monitor_tab.set_refresh_interval(
                self.cfg.refresh_interval_s)
        elif w is self.analytics_tab:
            self.analytics_tab.reload()

    def _update_status(self) -> None:
        info = self.mgr.current()
        if info:
            self.statusBar().showMessage(
                f"PID {info.pid} · {info.model_name} · ctx {info.ctx_size}")
        else:
            self.statusBar().showMessage("Сервер не запущен")

    def _update_status_pill(self) -> None:
        try:
            info = self.mgr.current()
        except Exception:
            info = None
        if info:
            self.status_pill.setText(f"● PID {info.pid} · работает")
            self.status_pill.setStyleSheet(
                "padding: 4px 12px; border-radius: 6px; "
                "background: #16213e; color: #2ecc71; font-weight: 600;")
        else:
            self.status_pill.setText("○ сервер остановлен")
            self.status_pill.setStyleSheet(
                "padding: 4px 12px; border-radius: 6px; "
                "background: #16213e; color: #8a8a9a; font-weight: 600;")

    def hide_window(self) -> None:
        self.hide()

    def show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def clear_chart_memory(self) -> None:
        """Release all matplotlib Figure objects and force GC.

        FIX #7 (Phase B): the old code called plt.close(fig.number), which only
        removes the figure from pyplot's global registry but leaves the Qt
        canvas + axes alive, so memory leaked on every tab switch. We now delegate
        to each chart's close() (figure + canvas + drill-down bar metadata) and
        force GC.
        """
        import gc

        charts = []
        for tab in (self.analytics_tab, self.monitor_tab):
            for attr in ("trend_chart", "deep_chart",
                         "heat_chart", "live_chart"):
                if hasattr(tab, attr):
                    charts.append(getattr(tab, attr))

        # FIX #14 (Phase B): close() also releases ClickableStackedBarChart._bar_meta
        # (matplotlib Bar patches that reference the figure), so the old figure is
        # fully reclaimed instead of leaking on tab switch.
        for chart in charts:
            try:
                close = getattr(chart, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass

        gc.collect()
