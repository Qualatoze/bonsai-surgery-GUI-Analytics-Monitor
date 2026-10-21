"""Settings tab: global token price, paths, UI parameters, statistics."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from config import save_config
from i18n import set_language, t
from theme import THEMES
from widgets import HintLabel, SectionTitle


class SettingsTab(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.cfg = controller.cfg
        self._accent = self.cfg.accent_color
        self._build_ui()
        self._load_into_ui()

    # ------------------------------------------------------------------
    # UI construction — no QTableWidget, pure QVBoxLayout of rows
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(6)

        # --- Token costs (three separate prices per 1M tokens, always USD) ---
        v.addWidget(SectionTitle(t("settings.token_costs")))

        # Three separate price fields: input / output / cached input
        prices_box = QGroupBox()
        prices_form = QFormLayout(prices_box)
        self.price_input_edit = QLineEdit()
        self.price_input_edit.setPlaceholderText("0.0")
        prices_form.addRow(t("settings.price_input_1m"), self.price_input_edit)
        self.price_output_edit = QLineEdit()
        self.price_output_edit.setPlaceholderText("0.0")
        prices_form.addRow(t("settings.price_output_1m"), self.price_output_edit)
        self.price_cached_edit = QLineEdit()
        self.price_cached_edit.setPlaceholderText("0.0")
        prices_form.addRow(t("settings.price_cached_1m"), self.price_cached_edit)
        v.addWidget(prices_box)

        # --- Theme selector (7 color schemes) ---
        v.addWidget(SectionTitle(t("settings.theme")))
        theme_row = QHBoxLayout()
        theme_row.setSpacing(4)
        self.theme_combo = QComboBox()
        for key, label in _THEME_LABELS.items():
            self.theme_combo.addItem(label, key)
        theme_row.addWidget(QLabel(t("settings.color_scheme") + ":"))
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch(1)
        v.addLayout(theme_row)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        # --- Paths and network ---
        v.addWidget(SectionTitle(t("settings.paths")))
        paths_box = QGroupBox()
        form = QFormLayout(paths_box)
        self.data_path_edit = QLineEdit()
        self.api_key_edit = QLineEdit()
        self.api_endpoint_edit = QLineEdit()
        self.models_dir_edit = QLineEdit()
        form.addRow(t("settings.data_path_label"), self.data_path_edit)
        form.addRow(t("settings.api_key_label"), self.api_key_edit)
        form.addRow(t("settings.api_endpoint_label"), self.api_endpoint_edit)
        form.addRow(t("settings.models_dir_label"), self.models_dir_edit)

        # llama-server.exe path with browse button (issue #3)
        self.llama_exe_edit = QLineEdit()
        exe_row = QHBoxLayout()
        exe_row.addWidget(self.llama_exe_edit, stretch=1)
        exe_browse = QPushButton(t("settings.browse_btn"))
        exe_browse.clicked.connect(self._browse_llama_exe)
        exe_row.addWidget(exe_browse)
        form.addRow(t("settings.llama_exe_label"), exe_row)

        v.addWidget(paths_box)

        # --- UI settings (with language selector) ---
        v.addWidget(SectionTitle(t("settings.ui_settings")))
        ui_box = QGroupBox()
        ui_form = QFormLayout(ui_box)

        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(1, 30)
        self.refresh_spin.setSuffix(" s")
        ui_form.addRow(t("settings.refresh_interval_label"), self.refresh_spin)

        self.gran_combo = QComboBox()
        self.gran_combo.addItems(["daily", "weekly", "monthly"])
        ui_form.addRow(t("settings.granularity_label"), self.gran_combo)

        # Language selector
        lang_row = QHBoxLayout()
        self.lang_combo = QComboBox()
        for code, label in (("en", "English"), ("ru", "Русский"), ("cn", "中文")):
            self.lang_combo.addItem(label, code)
        ui_form.addRow(t("settings.language"), self.lang_combo)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)

        accent_row = QHBoxLayout()
        self.accent_label = QLabel()
        self._update_accent_label()
        pick_btn = QPushButton(t("settings.pick_color_btn"))
        pick_btn.clicked.connect(self._pick_accent)
        accent_row.addWidget(self.accent_label, stretch=1)
        accent_row.addWidget(pick_btn)
        ui_form.addRow(t("settings.accent_color_label"), accent_row)
        v.addWidget(ui_box)

        # --- Statistics ---
        v.addWidget(SectionTitle(t("settings.stats")))
        stats_box = QGroupBox()
        stats_form = QFormLayout(stats_box)
        self.stats_db_edit = QLineEdit()
        stats_form.addRow(t("settings.stats_db_label"), self.stats_db_edit)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 3650)
        self.retention_spin.setSuffix(" days")
        stats_form.addRow(t("settings.retention_label"), self.retention_spin)

        self.sample_interval_spin = QSpinBox()
        self.sample_interval_spin.setRange(1, 60)
        self.sample_interval_spin.setSuffix(" s")
        stats_form.addRow(t("settings.sample_interval_label"), self.sample_interval_spin)

        self.start_perf_check = QCheckBox(t("perf.mode_on"))
        stats_form.addRow("", self.start_perf_check)
        v.addWidget(stats_box)

        # --- Server Network (FIX #4) ---
        v.addWidget(SectionTitle("Server Network"))
        net_box = QGroupBox()
        net_form = QFormLayout(net_box)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("0.0.0.0")
        net_form.addRow("Bind address", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8080)
        net_form.addRow("Port", self.port_spin)

        self.lan_urls_label = QLabel("—")
        self.lan_urls_label.setWordWrap(True)
        net_form.addRow("LAN URLs", self.lan_urls_label)

        fw_row = QHBoxLayout()
        fw_row.addStretch(1)
        self.fw_btn = QPushButton("Add Windows Firewall Rule…")
        self.fw_btn.clicked.connect(self._add_firewall_rule)
        fw_row.addWidget(self.fw_btn)
        net_form.addRow("", fw_row)

        net_form.addRow("", HintLabel(
            "0.0.0.0 = access from LAN · 127.0.0.1 = local only. "
            "Changes take effect after server restart."))
        v.addWidget(net_box)

        # --- Save button ---
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        save_btn = QPushButton(t("settings.save"))
        save_btn.setProperty("role", "primary")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        v.addLayout(btn_row)
        v.addStretch(1)

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------
    def _load_into_ui(self) -> None:
        self.price_input_edit.setText(str(self.cfg.price_input_per_1m))
        self.price_output_edit.setText(str(self.cfg.price_output_per_1m))
        self.price_cached_edit.setText(str(self.cfg.price_cached_input_per_1m))

        # Theme selector
        theme_idx = self.theme_combo.findData(self.cfg.theme_name)
        if theme_idx >= 0:
            self.theme_combo.setCurrentIndex(theme_idx)

        self.data_path_edit.setText(self.cfg.data_path)
        self.api_key_edit.setText(self.cfg.api_key_path)
        self.api_endpoint_edit.setText(self.cfg.api_endpoint)
        self.models_dir_edit.setText(self.cfg.models_dir)
        self.llama_exe_edit.setText(self.cfg.llama_server_exe)
        self.refresh_spin.setValue(self.cfg.refresh_interval_s)
        if self.cfg.chart_granularity in ("daily", "weekly", "monthly"):
            self.gran_combo.setCurrentText(self.cfg.chart_granularity)

        # Language selector
        lang_idx = self.lang_combo.findData(self.cfg.language)
        if lang_idx >= 0:
            self.lang_combo.setCurrentIndex(lang_idx)

        self.stats_db_edit.setText(self.cfg.stats_db_path)
        self.retention_spin.setValue(self.cfg.stats_retention_days)
        self.sample_interval_spin.setValue(self.cfg.sample_interval_s)
        self.start_perf_check.setChecked(self.cfg.start_in_performance_mode)

        # Server Network (FIX #4)
        self.host_edit.setText(self.cfg.host)
        self.port_spin.setValue(self.cfg.port)
        self._refresh_lan_urls()

    def _update_accent_label(self) -> None:
        self.accent_label.setText(self._accent)
        self.accent_label.setStyleSheet(
            f"background-color: {self._accent}; color: white; "
            f"border-radius: 6px; padding: 4px 10px; font-weight: 600;"
        )

    def _pick_accent(self) -> None:
        c = QColorDialog.getColor(QColor(self._accent), self, t("settings.accent_color_label"))
        if c.isValid():
            self._accent = c.name()
            self._update_accent_label()

    def _browse_llama_exe(self) -> None:
        """Open a file dialog to pick the llama-server.exe binary."""
        path, _ = QFileDialog.getOpenFileName(
            self, t("settings.browse_btn"),
            self.cfg.llama_server_exe,
            "Executable files (*.exe);;All files (*)")
        if path:
            self.llama_exe_edit.setText(path)

    @staticmethod
    def _parse_price(text: str) -> float:
        """Parse a price string; clamp to [0.0, 1e6]. Return 0.0 for empty/invalid/non-finite input."""
        try:
            v = float(text.strip() or "0.0")
        except (ValueError, TypeError):
            return 0.0
        if not math.isfinite(v):
            return 0.0
        # BUG 5: clamp to reasonable range [0.0, 1e6]
        return max(0.0, min(v, 1e6))

    def _save(self) -> None:
        # Prices (invalid / non-finite input falls back to 0.0, clamped to [0, 1e6])
        self.cfg.price_input_per_1m = self._parse_price(self.price_input_edit.text())
        self.cfg.price_output_per_1m = self._parse_price(self.price_output_edit.text())
        self.cfg.price_cached_input_per_1m = self._parse_price(self.price_cached_edit.text())

        # Theme
        theme_name = self.theme_combo.currentData()
        if theme_name in THEMES:
            self.cfg.theme_name = theme_name

        # Language
        lang_code = self.lang_combo.currentData()
        if lang_code in ("en", "ru", "cn"):
            self.cfg.language = lang_code
            set_language(lang_code)

        # Paths
        self.cfg.data_path = self.data_path_edit.text()
        self.cfg.api_key_path = self.api_key_edit.text()
        self.cfg.api_endpoint = self.api_endpoint_edit.text()
        self.cfg.models_dir = self.models_dir_edit.text()
        self.cfg.llama_server_exe = self.llama_exe_edit.text()

        # UI settings
        self.cfg.refresh_interval_s = self.refresh_spin.value()
        self.cfg.chart_granularity = self.gran_combo.currentText()
        self.cfg.accent_color = self._accent

        # Stats
        self.cfg.stats_db_path = self.stats_db_edit.text()
        self.cfg.stats_retention_days = self.retention_spin.value()
        self.cfg.sample_interval_s = self.sample_interval_spin.value()
        self.cfg.start_in_performance_mode = self.start_perf_check.isChecked()

        # Server Network (FIX #4)
        new_host = self.host_edit.text().strip() or "0.0.0.0"
        new_port = self.port_spin.value()

        # Only provide a default when endpoint is empty; let validation
        # reject invalid values instead of silently rewriting them.
        if not self.cfg.api_endpoint:
            self.cfg.api_endpoint = f"http://localhost:{new_port}/v1"

        self.cfg.host = new_host
        self.cfg.port = new_port
        self._refresh_lan_urls()

        # --- Validation before save ---
        errors = self.cfg.validate()
        if errors:
            QMessageBox.critical(
                self, t("settings.validation_error"), "\n".join(errors)
            )
            return

        try:
            save_config(self.cfg)
        except OSError as e:
            QMessageBox.critical(self, t("settings.save_error").format(msg=str(e)), str(e))
            return

        # Live apply: notify all tabs that settings changed
        self.controller.settings_saved.emit()

        self.controller.collector.set_interval(self.cfg.sample_interval_s)
        self.controller.store.insert_settings(
            json.dumps(self.cfg.to_dict(), ensure_ascii=False))

        if self.window() and hasattr(self.window(), "statusBar"):
            self.window().statusBar().showMessage(t("settings.saved"), 3000)

    def _on_theme_changed(self, index: int) -> None:
        """Handle theme combo change — delegate to controller."""
        if index < 0:
            return
        key = self.theme_combo.currentData()
        if key and isinstance(key, str):
            self.controller.set_theme(key)

    def _on_language_changed(self, index: int) -> None:
        """Live language switch — delegate to controller."""
        code = self.lang_combo.currentData()
        if isinstance(code, str):
            self.controller.set_language(code)

    # ------------------------------------------------------------------
    # FIX #4: LAN helpers
    # ------------------------------------------------------------------
    def _refresh_lan_urls(self) -> None:
        """Show current LAN URLs based on detected IPs and port."""
        from config import detect_lan_ips
        port = self.port_spin.value()
        ips = detect_lan_ips()
        if not ips:
            self.lan_urls_label.setText("(no external interfaces)")
            return
        self.lan_urls_label.setText(
            "<br>".join(f"http://{ip}:{port}/v1  ·  {iface}"
                        for iface, ip in ips))

    def _add_firewall_rule(self) -> None:
        """Add a Windows Firewall inbound rule for llama-server.exe."""
        if sys.platform != "win32":
            QMessageBox.information(self, "Firewall",
                                    "Helper is Windows-only.")
            return
        exe = Path(self.cfg.llama_server_exe)
        if not exe.is_file():
            QMessageBox.warning(self, "Firewall",
                                f"llama-server.exe not found:\n{exe}")
            return

        import tempfile
        import subprocess
        script = (
            '$ErrorActionPreference = "Stop"\n'
            'Remove-NetFirewallRule -DisplayName "Bonsai llama-server" '
            '-ErrorAction SilentlyContinue\n'
            f'New-NetFirewallRule -DisplayName "Bonsai llama-server" '
            f'-Direction Inbound -Program "{exe}" -Action Allow '
            f'-Profile Private,Domain\n'
            'Write-Host "OK. Press Enter to close."\n'
            'Read-Host\n'
        )
        tmp = Path(tempfile.gettempdir()) / "add_bonsai_firewall.ps1"
        tmp.write_text(script, encoding="utf-8")
        try:
            subprocess.Popen(
                ["powershell", "-Command",
                 f"Start-Process powershell -Verb RunAs "
                 f"-ArgumentList '-ExecutionPolicy','Bypass','-File','{tmp}'"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            QMessageBox.information(
                self, "Firewall",
                "UAC prompt will appear — accept to add the rule.")
        except Exception as e:
            QMessageBox.warning(self, "Firewall", f"Launch error: {e}")


# --- Theme display labels (human-readable names for the 7 schemes) ---
_THEME_LABELS: dict[str, str] = {
    "dracula": "Dracula",
    "solarized_dark": "Solarized Dark",
    "solarized_light": "Solarized Light",
    "nord": "Nord",
    "monokai": "Monokai",
    "one_dark": "One Dark Pro",
    "github_dark": "GitHub Dark",
    "tokyo_night": "Tokyo Night",
}
