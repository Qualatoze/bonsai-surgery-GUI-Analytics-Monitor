"""Центральный оркестратор: держит ресурсы, координирует GUI ↔ трей ↔ статистику."""
from __future__ import annotations

import gc

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QSystemTrayIcon

from config import load_config, save_config
from resource_monitor import ProcessMetrics
from server_manager import ServerManager
from stats_collector import StatsCollector
from stats_store import StatsStore
from agent_cost_collector import AgentCostCollector
from spill_guard import SpillGuard
from layer_manager import LayerManager


class AppController(QObject):
    performance_mode_changed = Signal(bool)
    theme_changed = Signal(str)
    settings_saved = Signal()
    language_changed = Signal(str)

    _instance: "AppController | None" = None

    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        AppController._instance = self
        self.cfg = cfg if cfg is not None else load_config()
        self.mgr = ServerManager(self.cfg)
        self.pm = ProcessMetrics()
        self.store = StatsStore(self.cfg.stats_db_path)
        self.collector = StatsCollector(
            self.mgr, self.store, self.pm,
            interval_s=self.cfg.sample_interval_s,
            small_gpu_mib=self.cfg.small_gpu_threshold_mib,
        )
        # NEW: сборщик работы AI-агента (работает и в Performance Mode)
        self.agent_collector = AgentCostCollector(self.cfg, self.mgr, self.store)
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()

        # PS1 parity: spill guard + Bonsai layer proxy (started on server start)
        self.spill_guard = SpillGuard(self)
        self.layer_manager = LayerManager(self)
        self.spill_guard.spilled.connect(self._on_spill)

        self._performance_mode = False
        self.window = None
        self.tray = None
        self._shutdown_called = False

    # --- lifecycle ---
    def start(self) -> None:
        try:
            deleted = self.store.cleanup_older_than(self.cfg.stats_retention_days)
            if deleted:
                self.store.insert_event("cleanup", details=f"deleted {deleted} rows")
        except Exception:
            pass
        self.collector.start()
        self.agent_collector.start()   # NEW
        self.store.insert_event("app_started")

    # --- theme management ---
    def set_theme(self, theme_name: str) -> None:
        """Set the active color scheme, persist to config, emit signal."""
        if theme_name == self.cfg.theme_name:
            return
        self.cfg.theme_name = theme_name
        try:
            save_config(self.cfg)
        except Exception:
            pass
        self.theme_changed.emit(theme_name)

    def set_language(self, lang_code: str) -> None:
        """Set the UI language live, persist to config, emit signal."""
        if lang_code not in ("en", "ru", "cn"):
            return
        if lang_code == self.cfg.language:
            return
        from i18n import set_language as _set_lang
        self.cfg.language = lang_code
        try:
            save_config(self.cfg)
        except Exception:
            pass
        _set_lang(lang_code)
        self.language_changed.emit(lang_code)

    def shutdown(self, stop_server: bool = False) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        AppController._instance = None
        self.store.insert_event("app_stopped",
                                details=f"stop_server={stop_server}")
        self.collector.stop()
        self.agent_collector.stop()    # NEW
        self.spill_guard.stop()
        self.layer_manager.stop()
        if stop_server:
            try:
                self.mgr.stop()
            except Exception:
                pass
        else:
            info = self.mgr.current()
            if info:
                self.store.insert_event("app_left_server_running",
                                        pid=info.pid,
                                        model_name=info.model_name)
        try:
            from PySide6.QtCore import QThreadPool
            QThreadPool.globalInstance().waitForDone(500)
        except Exception:
            pass

    def start_server_side_services(self) -> None:
        """Start spill guard and layer manager when the server is running."""
        try:
            self.spill_guard.start()
        except Exception as exc:
            print(f"[spill-guard] failed to start: {exc}")
        try:
            self.layer_manager.start()
        except Exception as exc:
            print(f"[layer-manager] failed to start: {exc}")

    def _on_spill(self, msg: str) -> None:
        """Handle spill guard warning — surface it in the launch tab."""
        if self.window:
            try:
                tab = self.window.launch_tab
                tab.info_label.setText(msg)
            except Exception:
                pass

    # --- performance mode ---
    @property
    def performance_mode(self) -> bool:
        return self._performance_mode

    def set_performance_mode(self, enabled: bool) -> None:
        if enabled == self._performance_mode:
            return
        self._performance_mode = enabled
        if enabled:
            self._enter()
        else:
            self._exit()
        self.performance_mode_changed.emit(enabled)

    def toggle_performance_mode(self) -> None:
        self.set_performance_mode(not self._performance_mode)

    def _enter(self) -> None:
        if self.window:
            self.window.clear_chart_memory()
            self.window.hide_window()
        gc.collect()
        if self.tray:
            from i18n import t
            self.tray.notify(
                t("perf.notify_title"),
                t("perf.notify_body"),
            )

    def _exit(self) -> None:
        if self.window:
            self.window.show_window()
            tab = self.window.analytics_tab
            if getattr(tab, "_df", None) is not None:
                tab._apply_filters()
