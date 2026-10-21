"""Tab 2 — Мониторинг процесса: KPI + live-график + логи."""
from __future__ import annotations

import time as _time
from collections import deque
from datetime import datetime

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from charts_widgets import LiveResourceChart
from resource_monitor import system_ram
from i18n import t
from widgets import HintLabel, KpiRow, SectionTitle


class MonitorTab(QWidget):
    """FIX-A9: показывает stderr и индикатор «Запуск…» во время загрузки модели."""

    # After this many seconds of process being alive, we stop using /health gate.
    _STARTUP_TIMEOUT_S = 30.0
    # Cache TTL for /health check (seconds) — avoids blocking HTTP every refresh.
    _HEALTH_CACHE_TTL_S = 2.0

    def __init__(self, controller, parent=None):
        super().__init__()
        self.controller = controller
        self.cfg = controller.cfg
        self.mgr = controller.mgr
        self.pm = controller.pm
        self.store = controller.store

        # Track when the server process was first seen (for startup detection).
        self._server_start_time: float | None = None

        # In-memory buffer for live chart (avoids 60s DB flush delay).
        self._live_samples: deque[dict] = deque(maxlen=600)

        # BUG fix: cache /health result to avoid blocking UI thread.
        self._health_cache: dict[str, float] = {}

        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

        # FIX-A9: отдельный быстрый таймер для старта (1 сек вместо refresh_interval)
        self._startup_timer = QTimer(self)
        self._startup_timer.timeout.connect(self._refresh_startup_tail)

        controller.collector.sample_ready.connect(self._on_live_sample)

        # Live apply: new refresh interval from the Settings tab
        self.controller.settings_saved.connect(self._on_settings_changed)

    def _on_settings_changed(self) -> None:
        """Apply new refresh interval from the Settings tab."""
        self.set_refresh_interval(self.cfg.refresh_interval_s)

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)

        # FIX-A9: индикатор старта (скрыт по умолчанию)
        self.startup_label = QLabel("⏳ Загрузка модели…")
        self.startup_label.setStyleSheet(
            "color: #F39C12; font-size: 14px; font-weight: bold; padding: 8px;"
        )
        self.startup_label.setVisible(False)
        v.addWidget(self.startup_label)

        v.addWidget(SectionTitle(t("monitor.process_metrics")))
        self.kpis = KpiRow()
        for key, label in (
            ("pid", "PID"), ("cpu", "CPU"), ("ram", "RAM RSS"),
            ("pagefile", "Pagefile / VMS"), ("vram", "VRAM (PID)"),
            ("sys_ram", "System RAM"),
        ):
            self.kpis.add_card(key, label)
        v.addWidget(self.kpis)

        self.no_server_hint = HintLabel(
            t("monitor.no_server"))
        self.no_server_hint.setStyleSheet(
            "color: #FDCB6E; font-size: 13px;")
        v.addWidget(self.no_server_hint)

        v.addWidget(SectionTitle(t("monitor.live_chart_title")))
        self.live_chart = LiveResourceChart(figsize=(9, 2.8))
        v.addWidget(self.live_chart)

        # FIX point 4: single stderr view (no QTabWidget with stdout/combined).
        v.addWidget(SectionTitle(t("monitor.logs_title")))
        mono = QFont("Consolas", 9)
        self.stderr_view = QPlainTextEdit()
        self.stderr_view.setReadOnly(True)
        self.stderr_view.setFont(mono)
        self.stderr_view.setPlaceholderText("(stderr пуст — сервер не запущен)")
        v.addWidget(self.stderr_view, stretch=1)


    def showEvent(self, e):
        super().showEvent(e)
        self._timer.start(max(1, int(self.cfg.refresh_interval_s)) * 1000)
        self.refresh()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()
        self._startup_timer.stop()

    def set_refresh_interval(self, seconds: int) -> None:
        if self._timer.isActive():
            self._timer.start(max(1, seconds) * 1000)

    def _on_live_sample(self, sample: dict) -> None:
        """FIX 2b: VRAM из StatsCollector — без блокировки UI."""
        vram = sample.get("vram_mib")
        gpu_total = sample.get("gpu_total_mib")
        if vram is not None or gpu_total is not None:
            # FIX: when vram is 0 (not None), show "0 MiB" not "N/A".
            value = f"{vram} MiB" if vram is not None else "N/A"
            sub = (f"GPU total {gpu_total} MiB" if gpu_total else "")
            self.kpis.set_value("vram", value, sub)

        # Append to in-memory buffer for live chart.
        self._live_samples.append(sample)

    def _is_server_ready(self) -> bool:
        """FIX-A9: быстрая проверка /health с кэшем — True если сервер готов.

        Uses a time-based cache (2s TTL) to avoid blocking the UI thread
        with repeated HTTP calls during startup polling.
        """
        now = _time.time()
        key = f"http://{self.cfg.host}:{self.cfg.port}/health"
        cached = self._health_cache.get(key)
        if cached is not None:
            ts, result = cached
            if now - ts < self._HEALTH_CACHE_TTL_S:
                return result

        import urllib.request
        import urllib.error
        try:
            with urllib.request.urlopen(
                key, timeout=1) as r:
                result = (r.status == 200)
        except (urllib.error.URLError, OSError):
            result = False

        self._health_cache[key] = (now, result)
        return result

    def _refresh_startup_tail(self) -> None:
        """FIX-A9: живой tail stderr раз в секунду во время старта."""
        info = self.mgr.current()
        if info is None:
            # Процесс умер — останавливаем startup-режим
            self.startup_label.setVisible(False)
            self._startup_timer.stop()
            return

        # Если сервер уже готов — выходим из startup-режима
        if self._is_server_ready():
            self.startup_label.setVisible(False)
            self._startup_timer.stop()
            self.refresh()
            return

        # Показываем tail stderr (only stderr, no stdout/combined)
        tail = self.mgr.tail_stderr(50) or "(stderr ещё пуст — модель грузится…)"
        self.stderr_view.setPlainText(tail)

    def refresh(self) -> None:
        """Public entry point for timer-driven UI update."""
        try:
            info = self.mgr.current()
            if info is None:
                # H9: reset startup timer when server is stopped
                self._server_start_time = None
                # FIX-A9: если процесс мёртв — останавливаем startup-режим
                self.startup_label.setVisible(False)
                self._startup_timer.stop()
                self.no_server_hint.setVisible(True)
                for key in ("pid", "cpu", "ram", "pagefile", "vram", "sys_ram"):
                    self.kpis.set_value(key, "—", "")
                return

            # FIX-A9: процесс жив. Определяем режим: startup или normal.
            if self._server_start_time is None:
                self._server_start_time = _time.time()

            elapsed = _time.time() - self._server_start_time

            # During first 30s after process start, use /health to detect model loading.
            # After that, trust the process — it's alive and serving (or processing).
            if elapsed < self._STARTUP_TIMEOUT_S:
                # H8: skip /health check during first 5s (server still initializing,
                # avoids blocking HTTP call in main thread)
                if elapsed >= 5 and not self._is_server_ready():
                    self.startup_label.setVisible(True)
                    self.no_server_hint.setVisible(False)
                    if not self._startup_timer.isActive():
                        self._startup_timer.start(1000)
                    self.kpis.set_value("pid", str(info.pid), "загрузка…")
                    for key in ("cpu", "ram", "pagefile", "vram", "sys_ram"):
                        self.kpis.set_value(key, "—", "")
                    tail = self.mgr.tail_stderr(50) or "(stderr ещё пуст — модель грузится…)"
                    self.stderr_view.setPlainText(tail)
                    return

            # Normal mode: process is alive and we're past startup window.
            # Show metrics regardless of /health response (it may be busy with a request).
            self.startup_label.setVisible(False)
            if self._startup_timer.isActive():
                self._startup_timer.stop()

            self.no_server_hint.setVisible(False)
            metrics = self.pm.get(info.pid)
            if metrics is None:
                self.kpis.set_value("pid", str(info.pid), "процесс пропал")
                tail = self.mgr.tail_stderr(60) or ""
                note = "[!] ПРОЦЕСС ЗАВЕРШЕН\n" if not tail else ""
                self.stderr_view.setPlainText(note + (tail or "(stderr пуст)"))
                return

            sys_ram = system_ram()

            page_label = ("Pagefile" if metrics["pagefile_mb"] is not None
                          else "VMS")
            page_val = (metrics["pagefile_mb"]
                        if metrics["pagefile_mb"] is not None
                        else metrics["vms_mb"])

            self.kpis.set_value("pid", str(metrics["pid"]),
                                f"status: {metrics['status']}")
            self.kpis.set_value(
                "cpu", f"{metrics['cpu_pct']:.0f}%",
                f"{metrics['cpu_cores_used']:.1f} из "
                f"{metrics['cpu_count']} ядер")
            self.kpis.set_value("ram", f"{metrics['rss_mb']:.0f} MB", "процесс")
            self.kpis.set_value("pagefile", f"{page_val:.0f} MB", page_label)

            self.kpis.set_value(
                "sys_ram",
                f"{sys_ram['ram_used_mb']:.0f}/"
                f"{sys_ram['ram_total_mb']:.0f} MB",
                f"{sys_ram['ram_percent']:.0f}% · "
                f"swap {sys_ram['swap_used_mb']:.0f} MB")

            # Always show stderr (no tab switching)
            self.stderr_view.setPlainText(
                self.mgr.tail_stderr(200) or "(пусто)")

            self._refresh_live_chart()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("refresh() crashed: %s", exc)

    def _set_text(self, widget, text: str) -> None:
        """Безопасно устанавливает текст в QPlainTextEdit, не дёргая лишний раз."""
        if widget.toPlainText() != text:
            widget.setPlainText(text)

    def _refresh_live_chart(self) -> None:
        """Render live chart from in-memory buffer (no DB delay)."""
        if not self._live_samples:
            return
        try:
            import pandas as pd
            df = pd.DataFrame(list(self._live_samples))
            # Ensure required columns exist for the chart renderer.
            if "ts" not in df.columns or "cpu_pct" not in df.columns:
                return
            self.live_chart.render(df, window_minutes=10)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Live chart render failed: %s", exc)
