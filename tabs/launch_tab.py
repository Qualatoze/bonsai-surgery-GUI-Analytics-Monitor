"""Tab 1 — Model selection and server launch (compact 1280×720 layout)."""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,
    QTabWidget, QVBoxLayout, QWidget, QSpinBox, QDoubleSpinBox,
    QScrollArea, QFrame,
)

from config import save_config
from i18n import t
from resource_monitor import get_gpu_bandwidth, query_gpu_snapshot
from server_manager import (scan_models, ModelInfo, compute_kv_vram_cells,
                            compute_ram_budget)
from widgets import HintLabel, KpiCard, SectionTitle, run_async


class ContextKvRow(QHBoxLayout):
    """Combo + custom QLineEdit + 'Custom' checkbox for context/KV rows."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(4)

        self._label = QLabel(label)
        self._label.setFixedWidth(90)
        self._label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.combo = QComboBox()
        self.combo.setFixedWidth(120)
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("Custom value…")
        self.custom_edit.setFixedWidth(130)
        self.custom_edit.setEnabled(False)

        self.custom_check = QCheckBox(t("launch.custom"))
        self.custom_check.setCheckable(True)
        self.custom_check.toggled.connect(self._on_custom_toggled)

        # Connect combo → custom (clears custom when preset selected)
        self.combo.currentIndexChanged.connect(
            lambda _: self.custom_edit.clear())

        self.addWidget(self._label)
        self.addWidget(self.combo)
        self.addWidget(self.custom_edit)
        self.addWidget(self.custom_check)

    def _on_custom_toggled(self, checked: bool) -> None:
        if checked:
            self.custom_edit.setEnabled(True)
            self.custom_edit.setFocus()
        else:
            self.custom_edit.clear()
            self.custom_edit.setEnabled(False)

    def get_value(self, default: str | int = "") -> str | int:
        """Return custom value if checkbox is on and field non-empty, else combo data."""
        if self.custom_check.isChecked():
            text = self.custom_edit.text().strip()
            if text:
                return text
        return self.combo.currentData() or default


class LaunchTab(QWidget):
    """FIX-A8: state machine — stopped → starting → running → stopping → stopped."""

    server_state_changed = Signal()

    # Base values for all advanced fields.
    _ADV_DEFAULTS: dict = {
        "spec_depth": 24576, "spec_deep": 4, "draft_window": 16384,
        "lookup_n": 32, "spec_n_max": 2,
        "kv_vram_cells": 0, "stage_cells": 0,
        "ram_budget_cache_mib": 0, "ram_budget_ckpts": 0, "pool_mib": 42,
        "ckpt_every": 8192, "shared_pool": True,
        "top_k": 20, "temp": 1.0, "top_p": 0.95, "repeat_penalty": 1.0,
        "ubatch": 0, "batch_size": 2048, "ngl": 999,
        # PS1 defaults: prefill/fa_chunk/kq_mask/harness_proof are ON for the
        # 8 GB and 12 GB presets; keep the widgets ON too so a plain launch
        # matches PS1 (previously they were OFF → PS1 recipes were NOT applied).
        "prefill_f16": True, "fa_chunk": True, "think": True,
        "harness_proof": True, "backend_sampling": True, "kq_mask_packed": True,
        "think_budget": 20480,
        "reasoning_budget_message": "Now produce the complete answer.",
        "reasoning_effort_fallback": "medium",
        "api_key_enabled": False,           # ← NEW: matches PS1 ($ApiKey = $null)
        "api_key_value": "",                # ← NEW: actual key (empty → fallback to api_key_path file)
    }

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.cfg = controller.cfg
        self.mgr = controller.mgr
        self._models: list[ModelInfo] = []
        self._gpu = None
        # FIX-A8: state machine
        self._state = "stopped"  # stopped | starting | running | stopping
        # Restore advanced opts persisted from presets.
        self._adv_opts: dict = dict(self.cfg.advanced_opts) if self.cfg.advanced_opts else {}
        self._pending_restore_model_name: Optional[str] = None

        self._build_ui()
        self.controller.settings_saved.connect(self._on_settings_changed)

        # Restore persisted advanced opts into the widgets. Defect: previously
        # only self._adv_opts was restored but the widgets kept hardcoded
        # defaults, and _read_adv_opts() reads the WIDGETS — so all advanced
        # settings from cfg.advanced_opts were silently dropped on every start.
        if self._adv_opts:
            try:
                self._write_adv_opts(self._adv_opts)
            except Exception:
                pass

        # Point 6: apply "Recent" preset from last_launch (if any).
        # Applied AFTER build_ui (widgets exist) but BEFORE async refreshes.
        if self.cfg.last_launch:
            try:
                self._apply_preset("recent")
            except Exception:
                pass

        # FIX-A3: async GPU query to avoid ~10s startup freeze.
        run_async(
            lambda: query_gpu_snapshot(self.cfg.small_gpu_threshold_mib),
            on_done=self._on_gpu_snapshot,
            on_error=lambda e: sys_info_label.setText(f"⚠️ GPU query error: {e}"),
        )
        self._refresh_models()
        self._refresh_status()

    # ------------------------------------------------------------------
    # UI construction — compact single-column layout for 1280×720
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Main scroll area to prevent clipping on 1080p screens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(6, 4, 6, 4)  # Уменьшили отступы
        root.setSpacing(4)                   # Уменьшили расстояние между блоками

        # --- Top row: Preset + Save + Start/Stop ---
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(150)
        self._populate_presets()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        top_row.addWidget(QLabel(t("launch.preset")))
        top_row.addWidget(self.preset_combo)

        save_btn = QPushButton(t("launch.save_preset"))
        save_btn.clicked.connect(self._save_preset)
        top_row.addWidget(save_btn)

        top_row.addStretch(1)

        self.start_btn = QPushButton(t("launch.start_server"))
        self.start_btn.setProperty("role", "primary")
        self.start_btn.setMinimumWidth(120)
        self.start_btn.clicked.connect(self._on_start)
        top_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton(t("launch.stop_server"))
        self.stop_btn.setProperty("role", "danger")
        self.stop_btn.setMinimumWidth(120)
        self.stop_btn.clicked.connect(self._on_stop)
        top_row.addWidget(self.stop_btn)

        root.addLayout(top_row)

        # --- Status & Info row (compact) ---
        status_row = QHBoxLayout()
        self.status_label = QLabel("\u2014")
        self.info_label = QLabel("")
        self.info_label.setWordWrap(False)  # Запрещаем перенос строк
        self.lan_hint = HintLabel("")
        self.lan_hint.setStyleSheet("font-size: 11px; color: #6C5CE7;")
        self.lan_hint.setWordWrap(True)  # Разрешаем перенос

        self.error_label = QLabel("")
        self.error_label.setProperty("role", "err")

        status_row.addWidget(self.status_label)
        status_row.addWidget(self.info_label)
        status_row.addStretch(1)

        root.addLayout(status_row)

        # Выносим отдельно, чтобы не сжимался кнопками
        root.addWidget(self.lan_hint)
        root.addWidget(self.error_label)

        # --- GPU / RAM info (merged into 1 label) ---
        self.sys_info_label = QLabel("\u2014")
        root.addWidget(self.sys_info_label)

        # --- Model & Context/KV in a Grid ---
        grid = QGridLayout()
        grid.setSpacing(6)

        grid.addWidget(QLabel(t("launch.model")), 0, 0)
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        grid.addWidget(self.model_combo, 0, 1, 1, 3)

        rescan_btn = QPushButton(t("launch.rescan"))
        rescan_btn.clicked.connect(self._refresh_models)
        grid.addWidget(rescan_btn, 0, 4)

        self.model_hint = HintLabel("")
        grid.addWidget(self.model_hint, 1, 0, 1, 5)

        # Context row
        ctx_row = ContextKvRow(t("launch.context_length"))
        for c in (32768, 65536, 131072, 262144):
            ctx_row.combo.addItem(str(c), c)
        idx = ctx_row.combo.findData(self.cfg.default_context_length)
        if idx >= 0:
            ctx_row.combo.setCurrentIndex(idx)
        self.ctx_row = ctx_row
        grid.addLayout(ctx_row, 2, 0, 1, 2)

        # KV row
        kv_row = ContextKvRow(t("launch.kv_cache"))
        for kv in ("q8_0", "q5_0", "q4_0", "f16"):
            kv_row.combo.addItem(kv, kv)
        if self.cfg.default_kv_cache_type in ("q8_0", "q5_0", "q4_0", "f16"):
            kv_row.combo.setCurrentText(self.cfg.default_kv_cache_type)
        self.kv_row = kv_row
        grid.addLayout(kv_row, 2, 2, 1, 3)

        # MTP toggle & TKC value
        mtp_row = QHBoxLayout()
        self.mtp_switch = QCheckBox(t("launch.mtp"))
        self.mtp_switch.toggled.connect(lambda _: self._update_tkc(self.model_combo.currentData()))
        mtp_row.addWidget(self.mtp_switch)

        mtp_row.addStretch(1)
        self.tkc_value_label = QLabel("\u2014")
        self.tkc_value_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #00D2FF;")
        mtp_row.addWidget(QLabel(t("launch.tkc_title") + ":"))
        mtp_row.addWidget(self.tkc_value_label)

        grid.addLayout(mtp_row, 3, 0, 1, 5)
        root.addLayout(grid)

        # TKC recompute triggers
        self.ctx_row.combo.currentIndexChanged.connect(lambda _: self._update_tkc(self.model_combo.currentData()))
        self.ctx_row.custom_edit.textChanged.connect(lambda _: self._update_tkc(self.model_combo.currentData()))
        self.kv_row.combo.currentIndexChanged.connect(lambda _: self._update_tkc(self.model_combo.currentData()))

        # --- Advanced Settings ---
        root.addSpacing(4)
        root.addWidget(SectionTitle(t("launch.advanced_settings")))
        self._build_advanced_inline(root)

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)
    def _build_advanced_inline(self, target_layout=None) -> None:
        """Compact 3-column layout for advanced settings (no tabs)."""
        self._adv_int_edits: dict[str, QSpinBox] = {}
        self._adv_float_edits: dict[str, QLineEdit] = {}
        self._adv_bool_checks: dict[str, QCheckBox] = {}
        self._adv_combo_edits: dict[str, QComboBox] = {}

        main_layout = QHBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(0, 0, 0, 0)

        def _make_col():
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(10)
            return w, v

        def add_int(name: str, default: int, grid: QGridLayout, row: int):
            spin = QSpinBox()
            spin.setRange(0, 1048576)
            spin.setValue(default)
            spin.setFixedWidth(110)
            spin.setFixedHeight(22)
            spin.setToolTip(t(f"adv.tooltip.{name}"))
            self._adv_int_edits[name] = spin
            grid.addWidget(QLabel(t(f"adv.{name}")), row, 0)
            grid.addWidget(spin, row, 1)
            grid.setColumnStretch(2, 1)

        def add_float(name: str, default: float, grid: QGridLayout, row: int):
            edit = QLineEdit(str(default))
            edit.setFixedWidth(110)
            edit.setFixedHeight(22)
            edit.setStyleSheet("padding: 1px 6px;")
            edit.setToolTip(t(f"adv.tooltip.{name}"))
            self._adv_float_edits[name] = edit
            grid.addWidget(QLabel(t(f"adv.{name}")), row, 0)
            grid.addWidget(edit, row, 1)

        def add_bool(name: str, default: bool, grid: QGridLayout, row: int, col: int = 0):
            check = QCheckBox(t(f"adv.{name}"))
            check.setChecked(default)
            check.setToolTip(t(f"adv.tooltip.{name}"))
            self._adv_bool_checks[name] = check
            grid.addWidget(check, row, col, 1, 2)

        # ===== COLUMN 1: Spec & Sampling =====
        col1, v1 = _make_col()

        gb_spec = QGroupBox(t("adv.group.spec_decoding"))
        grid_spec = QGridLayout(gb_spec)
        grid_spec.setSpacing(6)
        add_int("spec_depth", 24576, grid_spec, 0)
        add_int("spec_deep", 4, grid_spec, 1)
        add_int("draft_window", 16384, grid_spec, 2)
        add_int("lookup_n", 32, grid_spec, 3)
        v1.addWidget(gb_spec)

        gb_sampling = QGroupBox(t("adv.group.sampling"))
        grid_sampling = QGridLayout(gb_sampling)
        grid_sampling.setSpacing(6)
        add_int("top_k", 20, grid_sampling, 0)
        add_float("temp", 1.0, grid_sampling, 1)
        add_float("top_p", 0.95, grid_sampling, 2)
        add_float("repeat_penalty", 1.0, grid_sampling, 3)
        v1.addWidget(gb_sampling)

        # ===== COLUMN 2: Memory & Batch =====
        col2, v2 = _make_col()

        gb_mem = QGroupBox(t("adv.group.memory_kv"))
        grid_mem = QGridLayout(gb_mem)
        grid_mem.setSpacing(6)
        add_int("kv_vram_cells", 0, grid_mem, 0)
        add_int("stage_cells", 0, grid_mem, 1)
        add_int("ram_budget_cache", 0, grid_mem, 2)
        add_int("ram_budget_ckpts", 8, grid_mem, 3)
        add_int("pool_mib", 42, grid_mem, 4)
        add_int("ckpt_every", 8192, grid_mem, 5)
        add_bool("shared_pool", True, grid_mem, 6)
        v2.addWidget(gb_mem)

        gb_batch = QGroupBox(t("adv.group.batch_compute"))
        grid_batch = QGridLayout(gb_batch)
        grid_batch.setSpacing(4)

        add_int("ubatch", 0, grid_batch, 0)
        add_int("batch_size", 2048, grid_batch, 1)
        add_int("ngl", 999, grid_batch, 2)
        # Чекбоксы в две колонки (экономия ~3 строк)
        add_bool("prefill_f16", True, grid_batch, 3, col=0)
        add_bool("fa_chunk", True, grid_batch, 3, col=2)
        add_bool("think", True, grid_batch, 4, col=0)
        add_bool("harness_proof", True, grid_batch, 4, col=2)
        add_bool("backend_sampling", True, grid_batch, 5, col=0)
        add_bool("kq_mask_packed", True, grid_batch, 5, col=2)

        v2.addWidget(gb_batch)

        # ===== COLUMN 3: Other / Paths / API =====
        col3, v3 = _make_col()

        gb_other = QGroupBox(t("adv.group.other"))
        form_other = QFormLayout(gb_other)
        form_other.setSpacing(6)
        form_other.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)

        self._effort_combo = QComboBox()
        for val in ("low", "medium", "high", "xhigh"):
            self._effort_combo.addItem(val, val)
        idx = self._effort_combo.findText(getattr(self.cfg, "effort_mode", "medium"))
        if idx >= 0:
            self._effort_combo.setCurrentIndex(idx)
        form_other.addRow(t("adv.effort_mode"), self._effort_combo)
        self._adv_combo_edits["effort_mode"] = self._effort_combo

        self._force_8gb_combo = QComboBox()
        self._force_8gb_combo.addItem("Auto", -1)
        self._force_8gb_combo.addItem("Force 8 GB preset", 1)
        self._force_8gb_combo.addItem("Never 8 GB preset", 0)
        idx = self._force_8gb_combo.findData(getattr(self.cfg, "force_8gb", -1))
        if idx >= 0:
            self._force_8gb_combo.setCurrentIndex(idx)
        form_other.addRow(t("adv.force_8gb"), self._force_8gb_combo)
        self._adv_combo_edits["force_8gb"] = self._force_8gb_combo

        self._sparse_combo = QComboBox()
        self._sparse_combo.addItem("Auto", -1)
        self._sparse_combo.addItem("Force sparse", 1)
        self._sparse_combo.addItem("Disable", 0)
        idx = self._sparse_combo.findData(getattr(self.cfg, "sparse_mode", -1))
        if idx >= 0:
            self._sparse_combo.setCurrentIndex(idx)
        form_other.addRow(t("adv.sparse_mode"), self._sparse_combo)
        self._adv_combo_edits["sparse_mode"] = self._sparse_combo

        self._rs_replay_combo = QComboBox()
        self._rs_replay_combo.addItem("Auto", -1)
        self._rs_replay_combo.addItem("Force on", 1)
        self._rs_replay_combo.addItem("Off", 0)
        idx = self._rs_replay_combo.findData(getattr(self.cfg, "rs_replay_mode", -1))
        if idx >= 0:
            self._rs_replay_combo.setCurrentIndex(idx)
        form_other.addRow(t("adv.rs_replay_mode"), self._rs_replay_combo)
        self._adv_combo_edits["rs_replay_mode"] = self._rs_replay_combo

        spin_tb = QSpinBox()
        spin_tb.setRange(0, 1048576)
        spin_tb.setValue(int(self.cfg.think_budget or 20480))
        spin_tb.setFixedWidth(100)
        self._adv_int_edits["think_budget"] = spin_tb
        form_other.addRow(t("adv.think_budget"), spin_tb)

        self._reasoning_msg_edit = QLineEdit()
        self._reasoning_msg_edit.setPlaceholderText("Now produce the complete answer.")
        form_other.addRow(t("adv.reasoning_budget_message"), self._reasoning_msg_edit)

        self._reasoning_fallback_edit = QLineEdit()
        self._reasoning_fallback_edit.setPlaceholderText("medium")
        form_other.addRow(t("adv.reasoning_effort_fallback"), self._reasoning_fallback_edit)

        v3.addWidget(gb_other)

        gb_paths = QGroupBox("Paths & API")
        form_paths = QFormLayout(gb_paths)
        form_paths.setSpacing(6)
        form_paths.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._extra_args_edit = QLineEdit()
        form_paths.addRow(t("launch.extra_args"), self._extra_args_edit)

        # --- Multimodal / slot / layer (LT-7) ---
        self._mmproj_edit = QLineEdit()
        self._mmproj_edit.setMaximumWidth(350)  # Увеличили, чтобы путь читался целиком
        self._mmproj_edit.setPlaceholderText("mmproj .gguf path (blank = off)")
        mmproj_row = QHBoxLayout()
        mmproj_row.addWidget(self._mmproj_edit, stretch=0)
        self._mmproj_browse_btn = QPushButton("\u2026")
        self._mmproj_browse_btn.setFixedWidth(32)
        self._mmproj_browse_btn.setToolTip("Browse for mmproj file")
        mmproj_row.addWidget(self._mmproj_browse_btn)
        form_paths.addRow(t("adv.mmproj_path"), mmproj_row)

        self._mmproj_gpu_check = QCheckBox("offload mmproj to GPU")
        form_paths.addRow("", self._mmproj_gpu_check)

        self._slot_save_edit = QLineEdit()
        self._slot_save_edit.setMaximumWidth(350)  # Увеличили, чтобы путь читался целиком
        self._slot_save_edit.setPlaceholderText("slot-save-path (blank = off)")
        form_paths.addRow(t("adv.slot_save_path"), self._slot_save_edit)

        self._layer_check = QCheckBox(t("adv.layer_enabled"))
        form_paths.addRow("", self._layer_check)
        add_int("layer_inner_port", int(getattr(self.cfg, "layer_inner_port", 0)), grid_mem, 99)

        # --- API key (opt-in; matches start-server.ps1 default) ---
        self._api_key_enabled_check = QCheckBox("\u2764 Require API key")
        form_paths.addRow("", self._api_key_enabled_check)

        self._api_key_row = QWidget()
        api_key_layout = QHBoxLayout(self._api_key_row)
        api_key_layout.setContentsMargins(0, 0, 0, 0)
        api_key_layout.setSpacing(4)
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("auto-generated")
        api_key_layout.addWidget(self._api_key_edit, stretch=1)
        self._api_key_gen_btn = QPushButton("\u2764")
        self._api_key_gen_btn.setFixedWidth(32)
        api_key_layout.addWidget(self._api_key_gen_btn)
        self._api_key_row.setVisible(False)
        form_paths.addRow("API key", self._api_key_row)

        self._api_key_enabled_check.toggled.connect(self._on_api_key_enabled_toggled)
        self._api_key_gen_btn.clicked.connect(self._generate_api_key)
        v3.addWidget(gb_paths)

        # Wire up browse / change handlers (LT-7)
        self._mmproj_browse_btn.clicked.connect(lambda _: self._browse_mmproj())
        self._mmproj_edit.textChanged.connect(self._on_mmproj_changed)
        self._slot_save_edit.textChanged.connect(self._on_slot_changed)
        self._layer_check.toggled.connect(self._on_layer_toggled)

        # Убираем раздутые отступы QGroupBox у всех групп Advanced Settings
        for gb in (gb_spec, gb_sampling, gb_mem, gb_batch, gb_other, gb_paths):
            gb.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 0px; padding-top: 14px; }")

        # Убираем setMaximumWidth, чтобы блоки заняли всю ширину экрана

        # Добавляем колонки с коэффициентом растяжения (1)
        main_layout.addWidget(col1, 1)
        main_layout.addWidget(col2, 1)
        main_layout.addWidget(col3, 1)

        main_layout.setAlignment(Qt.AlignTop)

        wrapper = QWidget()
        wrapper.setLayout(main_layout)
        if target_layout is not None:
            target_layout.addWidget(wrapper)
        else:
            self.layout().addWidget(wrapper)

    def _read_adv_opts(self) -> dict:
        """Read all inline advanced settings into a dict."""
        opts = {}
        for name, spin in self._adv_int_edits.items():
            opts[name] = spin.value()
        for name, edit in self._adv_float_edits.items():
            try:
                opts[name] = float(edit.text().strip() or "0.0")
            except ValueError:
                pass
        for name, check in self._adv_bool_checks.items():
            opts[name] = check.isChecked()
        # LT-3: read the PS1-parity combo selectors.
        for name, combo in self._adv_combo_edits.items():
            opts[name] = combo.currentData()
        # LT-7: multimodal / slot / layer widgets.
        opts["mmproj_path"] = self._mmproj_edit.text().strip()
        opts["mmproj_gpu"] = self._mmproj_gpu_check.isChecked()
        opts["slot_save_path"] = self._slot_save_edit.text().strip()
        opts["layer_enabled"] = self._layer_check.isChecked()
        # LT-3: mirror config-level PS1 parity fields into opts (fallback for
        # prepare_launch when a widget value is empty).
        for fname in ("force_8gb", "sparse_mode", "rs_replay_mode"):
            if opts.get(fname) is None:
                opts[fname] = getattr(self.cfg, fname, -1)
        opts["extra_args"] = self._extra_args_edit.text()
        opts["reasoning_budget_message"] = self._reasoning_msg_edit.text().strip()
        opts["reasoning_effort_fallback"] = self._reasoning_fallback_edit.text().strip() or "medium"
        opts["api_key_enabled"] = self._api_key_enabled_check.isChecked()
        opts["api_key_value"] = self._api_key_edit.text().strip()
        return opts

    def _write_adv_opts(self, opts: dict) -> None:
        """Write a dict of advanced settings into the inline widgets."""
        for name, spin in self._adv_int_edits.items():
            if name in opts:
                try:
                    spin.setValue(int(opts[name]))
                except (ValueError, TypeError):
                    pass
        for name, edit in self._adv_float_edits.items():
            if name in opts:
                edit.setText(str(opts[name]))
        for name, check in self._adv_bool_checks.items():
            if name in opts:
                check.setChecked(bool(opts[name]))
        # LT-3: sync the PS1-parity combo selectors.
        for name, combo in self._adv_combo_edits.items():
            if name in opts and opts[name] is not None:
                idx = combo.findData(opts[name])
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        # LT-7: sync multimodal / slot / layer widgets.
        if "mmproj_path" in opts:
            self._mmproj_edit.setText(str(opts["mmproj_path"]))
        if "mmproj_gpu" in opts:
            self._mmproj_gpu_check.setChecked(bool(opts["mmproj_gpu"]))
        if "slot_save_path" in opts:
            self._slot_save_edit.setText(str(opts["slot_save_path"]))
        if "layer_enabled" in opts:
            self._layer_check.setChecked(bool(opts["layer_enabled"]))
        if "api_key_enabled" in opts:
            self._api_key_enabled_check.setChecked(bool(opts["api_key_enabled"]))
        if "api_key_value" in opts:
            self._api_key_edit.setText(str(opts["api_key_value"]))
        if "extra_args" in opts:
            self._extra_args_edit.setText(opts["extra_args"])
        if "reasoning_budget_message" in opts:
            self._reasoning_msg_edit.setText(opts["reasoning_budget_message"])
        if "reasoning_effort_fallback" in opts:
            self._reasoning_fallback_edit.setText(opts["reasoning_effort_fallback"])

    def _on_api_key_enabled_toggled(self, checked: bool) -> None:
        """Show/hide the key field. Auto-generate when enabling with empty field."""
        self._api_key_row.setVisible(checked)
        if checked and not self._api_key_edit.text().strip():
            self._generate_api_key()

    def _generate_api_key(self) -> None:
        """Fill the field with a strong random key (URL-safe, 32 chars)."""
        import secrets
        self._api_key_edit.setText(secrets.token_urlsafe(24))
        self._api_key_edit.setCursorPosition(0)

    # ------------------------------------------------------------------
    # Multimodal / slot / layer helpers (LT-7)
    # ------------------------------------------------------------------
    def _browse_mmproj(self) -> None:
        """Open a file picker for the mmproj .gguf."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "mmproj", str(Path(self.cfg.project_root)),
            "GGUF files (*.gguf);;All files (*)")
        if path:
            self._mmproj_edit.setText(path)
            self._on_mmproj_changed()

    def _on_mmproj_changed(self) -> None:
        """Persist mmproj path + GPU offload choice from Tab 5."""
        try:
            self.cfg.mmproj_path = self._mmproj_edit.text().strip()
            self.cfg.mmproj_gpu = self._mmproj_gpu_check.isChecked()
            save_config(self.cfg)
        except Exception:
            pass

    def _on_slot_changed(self) -> None:
        """Persist slot-save-path from Tab 5."""
        try:
            self.cfg.slot_save_path = self._slot_save_edit.text().strip()
            save_config(self.cfg)
        except Exception:
            pass

    def _on_layer_toggled(self, checked: bool) -> None:
        """Persist layer proxy enable + inner port from Tab 5."""
        try:
            self.cfg.layer_enabled = checked
            port_edit = self._adv_int_edits.get("layer_inner_port")
            if port_edit is not None:
                try:
                    self.cfg.layer_inner_port = int(port_edit.text().strip() or "0")
                except ValueError:
                    pass
            save_config(self.cfg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------
    def _populate_presets(self) -> None:
        """Populate preset combo with 5 built-in + Recent + up to 3 user presets."""
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("— auto —", "auto")

        # Built-in tiers
        builtin = [
            ("Very Fast", "very_fast"),
            ("Fast", "fast"),
            ("Mid", "mid"),
            ("Slow", "slow"),
            ("Very Slow", "very_slow"),
            ("RTX 4070S", "rtx_4070s"),
            # Recipe presets (bonsai-ada-surgery docs)
            ("12GB Fast", "fast_12gb"),
            ("8GB Long Context", "long_ctx_8gb"),
        ]
        for name, tier in builtin:
            self.preset_combo.addItem(f"★ {name}", tier)

        # Recent preset (auto-saved last launch config)
        if self.cfg.last_launch:
            self.preset_combo.addItem("● " + t("launch.preset_recent"), "recent")

        # User presets (up to 3)
        for i, p in enumerate(self.cfg.user_presets):
            pname = p.get("name", f"User {i + 1}")
            self.preset_combo.addItem(f"● {pname}", f"user_{i}")

        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _on_preset_changed(self, idx: int) -> None:
        tier = self.preset_combo.currentData()
        if tier is None or tier == "auto":
            return
        self._apply_preset(tier)

    def _apply_preset(self, tier: str) -> None:
        """Apply preset settings to UI fields (modifies current values)."""
        if tier == "auto":
            return

        # Built-in presets
        builtin_map = {
            "very_fast": {"context_length": 8192, "kv_cache_type": "q4_0",
                          "ngl": 999, "batch_size": 0},
            "fast": {"context_length": 32768, "kv_cache_type": "q4_0",
                     "ngl": 999, "batch_size": 0},
            "mid": {"context_length": 65536, "kv_cache_type": "q4_0",
                    "ngl": 999, "batch_size": 0},
            "slow": {"context_length": 131072, "kv_cache_type": "q5_0",
                     "ngl": 999, "batch_size": 0},
            "very_slow": {"context_length": 262144, "kv_cache_type": "q8_0",
                          "ngl": 999, "batch_size": 0},
            "rtx_4070s": {
                "context_length": 65536, "kv_cache_type": "q8_0",
                "ngl": 200, "batch_size": 1024,
                "spec_depth": 24576, "draft_window": 16384, "lookup_n": 32,
                "ubatch": 256,
                "top_k": 20, "temp": 0.6, "top_p": 0.95,
                "repeat_penalty": 1.1, "think_budget": 20480,
                "ckpt_every": 8192, "ram_budget_cache_mib": 2048,
                "stage_cells": 81920, "kv_vram_cells": 0, "pool_mib": 42,
                "spec_deep": 4, "shared_pool": True,
                "prefill_f16": True, "fa_chunk": True, "think": True,
                "harness_proof": True, "backend_sampling": True,
                "kq_mask_packed": True,
                "reasoning_budget_message": "Now produce the complete answer.",
                "reasoning_effort_fallback": "medium",
            },
            # --- Recipe presets (bonsai-ada-surgery docs) ---
            # Q8_FULL_CONTEXT.md: q8_0 at the full 262k window on a 12 GB card.
            "fast_12gb": {
                "context_length": 262144, "kv_cache_type": "q8_0",
                "ngl": 999, "batch_size": 0,
                "spec_depth": 24576,      # --spec-draft-depth-max (fallback)
                "draft_window": 16384,    # --spec-draft-window 16384
                "ubatch": 0,              # auto
                "ckpt_every": 8192,       # --checkpoint-every-nt inside a message
                "kv_vram_cells": 0,       # auto - tiered KV sized at launch from free VRAM
                "stage_cells": 0,         # auto - host-tail staging on by default
                "pool_mib": 42,           # as in PS1
                "shared_pool": True,      # as in PS1
                "prefill_f16": True,      # binary default = enabled (+9-26% prefill speedup)
                "fa_chunk": True,         # binary default = enabled
                "think": True,            # thinking on (medium is the coding default)
                "effort_mode": "medium",  # harness-proofing: safe for all clients
                "think_budget": 24576,    # reasoning-max-tokens-floor
                "harness_proof": True,    # --reasoning-effort-allow medium + floor
                "backend_sampling": False,
                "kq_mask_packed": True,   # packed 1-bit KQ mask (proven safe)
                "spec_deep": 4,           # large card -> spec_deep 4
            },
            # 8GB.md: long-context mode on an 8 GB card that draws the desktop.
            "long_ctx_8gb": {
                "context_length": 262144, "kv_cache_type": "q4_0",
                "ngl": 999, "batch_size": 0,
                "spec_depth": 24576,      # --spec-draft-depth-max (fallback)
                "draft_window": 16384,    # --spec-draft-window
                "ubatch": 0,              # auto
                "ckpt_every": 8192,       # --checkpoint-every-nt when the engine has it
                "kv_vram_cells": 0,       # auto - sized at launch from free VRAM
                "stage_cells": 81920,     # partial staging: 81,920 staged positions
                "pool_mib": 42,           # as in PS1
                "shared_pool": True,      # GGML_CUDA_SHARED_POOL=1 (~51 MiB)
                "prefill_f16": True,      # binary default = enabled (+9-26% prefill speedup)
                "fa_chunk": True,         # binary default = enabled
                "think": True,
                "effort_mode": "medium",  # harness-proofing: safe for all clients
                "think_budget": 24576,    # reasoning-max-tokens-floor
                "harness_proof": True,    # keep client compatibility (Cline/Kilo/OWebUI)
                "backend_sampling": False,
                "kq_mask_packed": True,   # packed 1-bit KQ mask (now used)
                "spec_deep": 1,           # small card -> spec_deep 1
                "use_mtp": False,         # no MTP on 8GB long-context (draft model doesn't fit)
            },
        }

        if tier == "recent":
            opts = dict(self.cfg.last_launch or {})
            if "context_length" not in opts:
                return
            # Apply advanced opts from recent snapshot to actual UI widgets
            try:
                self._write_adv_opts({
                    k: opts[k] for k in opts
                    if k in LaunchTab._ADV_DEFAULTS or k in (
                        "extra_args", "reasoning_budget_message",
                        "reasoning_effort_fallback")
                })
            except Exception:
                pass
            # MTP toggle
            if "use_mtp" in opts:
                self.mtp_switch.setChecked(bool(opts["use_mtp"]))
        elif tier in builtin_map:
            opts = dict(builtin_map[tier])
        else:
            # User preset: find by index
            user_idx = int(tier.split("_")[1])
            p = self.cfg.user_presets[user_idx]
            opts = {k: v for k, v in p.items() if k in (
                "context_length", "kv_cache_type", "ngl", "batch_size")}

        # Apply to context row — BUG 2 fix: always clear custom_check
        ctx_val = opts.get("context_length")
        if ctx_val is not None:
            self.ctx_row.custom_check.setChecked(False)
            self.ctx_row.custom_edit.clear()
            idx = self.ctx_row.combo.findData(ctx_val)
            if idx >= 0:
                self.ctx_row.combo.setCurrentIndex(idx)

        # Apply to KV row — BUG 2 fix: always clear custom_check
        kv_val = opts.get("kv_cache_type")
        if kv_val is not None:
            self.kv_row.custom_check.setChecked(False)
            self.kv_row.custom_edit.clear()
            idx = self.kv_row.combo.findData(kv_val)
            if idx >= 0:
                self.kv_row.combo.setCurrentIndex(idx)

        # Auto-fill advanced settings. Built-in presets give a complete, clean
        # configuration (dialog defaults + recipe overrides); user presets only
        # snapshot ctx/kv/ngl/batch and must not clobber the current advanced values.
        if tier in builtin_map:
            self._adv_opts = dict(LaunchTab._ADV_DEFAULTS)
            self._adv_opts.update({
                k: v for k, v in opts.items()
                if k not in ("context_length", "kv_cache_type", "ngl", "batch_size")
            })
            # CRITICAL: push the preset into the actual widgets. Without this,
            # _read_adv_opts() (which reads widgets, not self._adv_opts) still
            # returned the hardcoded defaults, and every preset value was lost.
            self._write_adv_opts(self._adv_opts)
            # Persist the resolved advanced configuration so it survives restart.
            self.cfg.advanced_opts = dict(self._adv_opts)
            save_config(self.cfg)
        # long_ctx_8gb: MTP draft doesn't fit in 8GB — disable in UI for consistency
        if tier == "long_ctx_8gb":
            self.mtp_switch.setChecked(False)

        # Update TKC
        model = self.model_combo.currentData()
        if model is not None:
            self._update_tkc(model)

    def _save_preset(self) -> None:
        """Save current settings as a user-named preset (max 3)."""
        if len(self.cfg.user_presets) >= 3:
            QMessageBox.warning(
                self, t("launch.save_preset"),
                "Maximum 3 user presets. Delete one first.")
            return

        name = ""
        # Simple inline dialog via QInputDialog
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, t("launch.save_preset"),
            t("launch.preset_name"))
        if not ok or not name.strip():
            return

        ctx_val = self._get_ctx_value()
        kv_val = self._get_kv_value()

        preset_dict: dict = {
            "name": name,
            "tier": "custom",
            "context_length": ctx_val,
            "kv_cache_type": kv_val,
            "ngl": 999,
            "batch_size": 0,
        }

        self.cfg.user_presets.append(preset_dict)
        self._populate_presets()
        self.preset_combo.setCurrentIndex(
            self.preset_combo.count() - 1)
        save_config(self.cfg)

    # ------------------------------------------------------------------
    # Environment / model refresh
    # ------------------------------------------------------------------
    def _on_settings_changed(self) -> None:
        """Re-apply settings that were changed in the Settings tab.

        Called when SettingsTab emits `settings_saved`. Refreshes models
        (paths may have changed) and re-queries GPU (async, non-blocking).
        """
        try:
            self._refresh_models()
            self._refresh_status()
        except Exception:
            pass

        # GPU query is slow (subprocess nvidia-smi) — keep it async.
        run_async(
            lambda: query_gpu_snapshot(self.cfg.small_gpu_threshold_mib),
            on_done=self._on_gpu_snapshot,
            on_error=lambda e: sys_info_label.setText(f"⚠️ GPU query error: {e}"),
        )

    def _on_gpu_snapshot(self, snap) -> None:
        """Handle GPU snapshot result (runs in main thread via Qt signal)."""
        gpus = snap["gpus"]
        self._gpu = gpus[0] if gpus else None

        gpu_text = "⚠️ nvidia-smi unavailable"
        if self._gpu:
            gpu_text = (f"<b>{self._gpu.name}</b> · VRAM "
                        f"{self._gpu.used_mib}/{self._gpu.total_mib} MiB · "
                        f"free <b>{self._gpu.free_mib} MiB</b>")

        ram_info = compute_ram_budget(self.cfg)
        pc_bytes = ram_info.get("prompt_cache_bytes")
        pc_mib = int(pc_bytes / (1024 * 1024)) if pc_bytes else 0
        ck = ram_info.get("checkpoint_count", 0)
        ram_text = (f"RAM: <b>{ram_info['total_gb']:.1f} GB</b> total · "
                    f"<b>{ram_info['free_gb']:.1f} GB</b> free · "
                    f"cache <code>{pc_mib if pc_mib else 'default'} MiB</code> · "
                    f"ckpt <code>{ck if ck else 'default'}</code>")

        self.sys_info_label.setText(f"{gpu_text} | {ram_text}")

        self._apply_auto_heuristics()

    def _apply_auto_heuristics(self) -> None:
        """LT-4: PS1-equivalent auto-tuning of advanced widgets after GPU/model change.

        Only fills values that are still at their 'auto' defaults (0 / -1),
        never overrides explicit user choices."""
        if self._gpu is None:
            return

        total_mib = int(self._gpu.total_mib)
        small_card = total_mib <= 8704

        # spec_deep: PS1 uses 1 on small cards, 4 on large
        if small_card:
            edit = self._adv_int_edits.get("spec_deep")
            if edit is not None and int(edit.text().strip() or "0") == 0:
                edit.setText("1")

        # stage_cells: PS1 uses partial staging (81920) on small cards only
        if small_card:
            edit = self._adv_int_edits.get("stage_cells")
            if edit is not None and int(edit.text().strip() or "0") == 0:
                edit.setText("81920")

        # spec_n_max: PS1 limits to 1 on small cards when MTP is active
        if small_card and self.mtp_switch.isChecked():
            edit = self._adv_int_edits.get("spec_n_max")
            if edit is not None and int(edit.text().strip() or "0") == 0:
                edit.setText("1")

    def _refresh_models(self) -> None:
        """Rescan models. Crash-proof: signals are always released in finally."""

        def on_done(models):
            self._models = models
            try:
                self.model_combo.blockSignals(True)
                self.model_combo.clear()
                if not models:
                    self.model_combo.addItem("— no .gguf —", None)
                    if self.cfg.model_min_size_gb < 1.0:
                        threshold = f"{self.cfg.model_min_size_gb * 1024:.0f} MB"
                    else:
                        threshold = f"{self.cfg.model_min_size_gb:.1f} GB"
                    self.model_hint.setText(
                        f"No .gguf ≥ {threshold} found in "
                        f"`{self.cfg.models_dir}`")
                else:
                    for m in models:
                        tags = " ".join(m.tags) or "—"
                        self.model_combo.addItem(
                            f"{m.name}  ·  {m.size_gb:.1f} GB  ·  [{tags}]", m)

                # Restore previously-selected model (language-change rebuild).
                restore_name = getattr(self, "_pending_restore_model_name", None)
                if not restore_name and self.cfg.last_selected_model_path:
                    for m in models:
                        if str(m.path) == self.cfg.last_selected_model_path:
                            restore_name = m.name
                            break
                if restore_name:
                    idx = next(
                        (i for i, m in enumerate(models)
                         if m.name == restore_name), -1)
                    if idx >= 0:
                        self.model_combo.setCurrentIndex(idx)
                    else:
                        self.model_combo.setCurrentIndex(0)

                # Unblock signals first so Qt processes the index change cleanly.
                self.model_combo.blockSignals(False)
            except Exception as exc:
                import traceback
                self.error_label.setText(
                    f"Model list error:\n{traceback.format_exc()}")
                try:
                    self.model_combo.blockSignals(False)
                except Exception:
                    pass

            # Call after signals are unblocked to avoid double-invocation.
            try:
                self._on_model_changed()
            except Exception as exc:
                import traceback
                self.error_label.setText(
                    f"Model change error:\n{traceback.format_exc()}")

        run_async(
            lambda: scan_models(self.cfg.models_dir, self.cfg.model_min_size_gb),
            on_done=on_done,
            on_error=lambda e: self.error_label.setText(f"Scan error: {e}"),
        )

    def _on_model_changed(self) -> None:
        m = self.model_combo.currentData()
        if m is None:
            return
        try:
            if m.mtp_path or m.is_mtp_model:
                hint = f"MTP draft: {m.mtp_path.name}" if m.mtp_path else "MTP model (self-contained)"
                self.model_hint.setText(hint)
                self.mtp_switch.setChecked(True)
                self.mtp_switch.setEnabled(True)
            else:
                self.model_hint.setText(
                    "No MTP draft found — speculative decoding unavailable.")
                self.mtp_switch.setChecked(False)
                self.mtp_switch.setEnabled(False)

            # Update TKC card
            self._update_tkc(m)
            # LT-5: re-tune advanced widgets for the new model's MTP state.
            self._apply_auto_heuristics()

            # H7: persist last selection to config for next launch
            try:
                self.cfg.last_selected_model_path = str(m.path)
                self.cfg.last_context_length = int(self._get_ctx_value() or 0)
                self.cfg.last_kv_cache_type = str(self._get_kv_value() or "q8_0")
                save_config(self.cfg)
            except Exception:
                pass
        except Exception as exc:
            import traceback
            self.error_label.setText(
                f"Model change error:\n{traceback.format_exc()}")

    def _update_tkc(self, model: Optional[ModelInfo]) -> None:
        """Theoretical tokens/s (memory-bound). Delegates math to presets.compute_tps."""
        if model is None or not self._gpu:
            self.tkc_value_label.setText("—")
            return

        try:
            size_gb = float(model.size_gb)
            if size_gb <= 0:
                self.tkc_value_label.setText("—")
                return

            from presets import compute_tps

            ctx = int(self._get_ctx_value() or 32768)
            kv_type = str(self._get_kv_value() or "q8_0")

            # Real bandwidth by name (more accurate than VRAM-class fallback)
            bw = get_gpu_bandwidth(self._gpu.name)

            base = compute_tps(
                size_gb, self._gpu.total_mib, ctx, kv_type,
                bandwidth_gb_s=bw,
            )

            # MTP boost: real numbers say +30-70% (+85% at 4k, +0% past ~28k).
            # Mid estimate: +40%.
            mtp_on = self.mtp_switch.isChecked()
            if mtp_on:
                base *= 1.4

            fits_in_vram = size_gb <= (self._gpu.total_mib - self.cfg.vram_margin_mib) / 1024.0

            self.tkc_value_label.setText(f"{base:.1f} tok/s")
            self.tkc_value_label.setToolTip(
                f"Theoretical memory-bound estimate.\n"
                f"GPU: {self._gpu.name} · {bw:.0f} GB/s\n"
                f"Context: {ctx} · KV: {kv_type}"
                + (" · MTP +40%" if mtp_on else "")
                + ("" if fits_in_vram else "\n⚠ Model won't fit in VRAM — real speed will be much lower")
            )
        except Exception as exc:
            import traceback
            self.error_label.setText(f"TKC error:\n{traceback.format_exc()}")

    @staticmethod
    def _kv_bytes_per_token(kv_type: str) -> int:
        mapping = {
            "q8_0": 34816,
            "q5_0": 22528,
            "q5_1": 24576,
            "q4_0": 18432,
            "q4_1": 20480,
            "iq4_nl": 18432,
            "f16": 65536,
        }
        return mapping.get(kv_type, 34816)

    def _get_ctx_value(self) -> int:
        val = self.ctx_row.get_value(32768)
        if isinstance(val, str):
            try:
                return int(val)
            except ValueError:
                return 32768
        return val

    def _get_kv_value(self) -> str:
        val = self.kv_row.get_value("q4_0")
        if isinstance(val, int):
            return "q4_0"
        return val

    # ------------------------------------------------------------------
    # Status / start / stop — FIX-A8: state machine
    # ------------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        """FIX-A8: переключает состояние и кнопки."""
        self._state = state
        if state == "stopped":
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.start_btn.setText(t("launch.start_server"))
            self.stop_btn.setText(t("launch.stop_server"))
        elif state == "starting":
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.start_btn.setText("⏳ Starting…")
        elif state == "running":
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.start_btn.setText(t("launch.start_server"))
            self.stop_btn.setText(t("launch.stop_server"))
        elif state == "stopping":
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("⏳ Stopping…")

    def _refresh_status(self) -> None:
        try:
            info = self.mgr.current()
        except Exception:
            info = None
        if info:
            self.status_label.setText(
                f'<span style="color:#2ecc71">● Running</span>')
            self.info_label.setText(
                f'PID {info.pid} · {info.model_name} · '
                f'ctx {info.ctx_size} · kv {info.kv_type}')
            self._set_state("running")

            # FIX #4: show LAN URLs when server is running
            from config import detect_lan_ips
            ips = detect_lan_ips()
            if ips:
                self.lan_hint.setText(
                    "LAN: " + " · ".join(
                        f"http://{ip}:{self.cfg.port}/v1" for _, ip in ips))
            else:
                self.lan_hint.setText("")
        else:
            self.status_label.setText(
                '<span style="color:#8a8a9a">○ Server stopped</span>')
            self.info_label.setText("")
            self.lan_hint.setText("")
            if self._state != "starting" and self._state != "stopping":
                self._set_state("stopped")

    def _on_start(self) -> None:
        """FIX-A8: Start через worker с wait_for_ready."""
        if self._state != "stopped":
            return

        model = self.model_combo.currentData()
        if model is None:
            QMessageBox.warning(self, t("launch.model"), "No .gguf selected.")
            return

        # Read advanced opts from inline widgets (always current)
        adv_opts = self._read_adv_opts()

        # Point 6: persist this launch as "recent" BEFORE starting,
        # so the preset is available on the next GUI start.
        try:
            self.cfg.last_launch = {
                **adv_opts,
                "context_length": int(self._get_ctx_value() or 0),
                "kv_cache_type": str(self._get_kv_value() or "q8_0"),
                "use_mtp": bool(self.mtp_switch.isChecked()),
                "model_name": getattr(model, "name", "") or "",
                "model_path": str(getattr(model, "path", "")) or "",
            }
            self.cfg.advanced_opts = dict(adv_opts)
            save_config(self.cfg)
        except Exception:
            pass

        # Auto-compute kv_vram_cells only if user hasn't set it explicitly
        auto_kv_cells = None
        if self._gpu:
            ctx_val = int(self._get_ctx_value() or 0)
            kv_type = str(self._get_kv_value() or "q8_0")
            model_size_gb = float(model.size_gb) if model else 0.0
            auto_kv_cells = compute_kv_vram_cells(
                self.cfg, self._gpu, kv_type=kv_type, ctx_size=ctx_val,
                model_size_gb=model_size_gb)

        # Виджеты всегда поверх: adv_opts — «фоновые» значения,
        # а mtp_switch.isChecked() — то, что пользователь видит и выбирает.
        opts = dict(adv_opts)             # сначала «фоновые»
        opts["ctx"] = self._get_ctx_value()
        opts["kv_type"] = self._get_kv_value()
        opts["use_mtp"] = self.mtp_switch.isChecked()  # виджеты всегда сверху

        # H1: pass GPU VRAM so build_args can pick correct -b (PS1 logic)
        if self._gpu:
            opts["_gpu_vram_mib"] = int(self._gpu.total_mib)

        # kv_vram_cells: auto only if user didn't set a non-zero value
        if not opts.get("kv_vram_cells"):
            if auto_kv_cells is not None and auto_kv_cells > 0:
                opts["kv_vram_cells"] = auto_kv_cells

        # H5: PS1 logic — small GPU (≤8704 MiB) gets reduced spec params.
        if self._gpu and int(self._gpu.total_mib) <= 8704:
            if opts.get("use_mtp"):
                opts["spec_n_max"] = 1
            opts["spec_deep"] = 1
            # PS1 only applies partial staging on 8 GB cards. On 12 GB+ the full
            # staging buffer keeps prefill fast past the tiered line. Auto-set only
            # on the small card; user can force it by typing a non-zero stage_cells.
            if not opts.get("stage_cells"):
                opts["stage_cells"] = 81920

        # M4: auto-compute RAM budget for --cache-ram / --ctx-checkpoints.
        # NOTE: compute_ram_budget returns BYTES (prompt_cache_bytes), but
        # --cache-ram expects MiB. Forgetting to divide by 1024*1024 causes
        # llama-server to crash with "stoi argument out of range".
        try:
            ram_budget = compute_ram_budget(self.cfg)
            if not opts.get("ram_budget_cache_mib"):
                pc_bytes = ram_budget.get("prompt_cache_bytes")
                if pc_bytes:
                    opts["ram_budget_cache_mib"] = int(pc_bytes / (1024 * 1024))
            if not opts.get("ram_budget_ckpts"):
                ck_count = ram_budget.get("checkpoint_count")
                if ck_count:
                    opts["ram_budget_ckpts"] = int(ck_count)
        except Exception:
            pass

        # LT-6: PS1-equivalent launch preparation (capability detection + auto-fills).
        try:
            import bonsai_env
            plan = bonsai_env.prepare_launch(
                opts, self.cfg,
                gpu_vram_mib=int(self._gpu.total_mib) if self._gpu else 0,
                gpu_free_mib=int(self._gpu.free_mib) if self._gpu else 0,
                gpu_name=str(self._gpu.name) if self._gpu else "",
                model_path=str(model.path),
                model_size_gb=float(model.size_gb),
                model_has_mtp=bool(model.is_mtp_model or (model.mtp_path is not None)),
            )
            opts["_prepared_env"] = plan.env
            opts["_caps"] = plan.caps
            opts["_listen_host"] = plan.listen_host
            opts["_listen_port"] = plan.listen_port
            # Apply auto-filled effective values back into opts (build_args uses them).
            for k, v in plan.opts.items():
                if not str(k).startswith("_"):
                    opts[k] = v
            if plan.notes:
                self.info_label.setText(" \u00b7 ".join(plan.notes))
        except Exception as exc:
            import traceback
            self.error_label.setText(f"Launch prep error:\n{traceback.format_exc()}")

        # LT-3: mirror PS1-parity fields into top-level cfg so they persist across
        # restarts (prepare_launch reads them via getattr(cfg, ...)).
        for fname in ("force_8gb", "sparse_mode", "rs_replay_mode"):
            if isinstance(opts.get(fname), int):
                setattr(self.cfg, fname, int(opts[fname]))
        if "effort_mode" in opts:
            self.cfg.effort_mode = str(opts["effort_mode"])
        for fname in ("mmproj_path", "slot_save_path"):
            if fname in opts:
                setattr(self.cfg, fname, str(opts[fname] or ""))
        for fname in ("mmproj_gpu", "layer_enabled"):
            if fname in opts:
                setattr(self.cfg, fname, bool(opts[fname]))
        if isinstance(opts.get("layer_inner_port"), int):
            self.cfg.layer_inner_port = int(opts["layer_inner_port"])
        try:
            save_config(self.cfg)
        except Exception:
            pass

        self._set_state("starting")
        self.error_label.setText("")

        def _job():
            info = self.mgr.start(model, opts)
            # FIX-A8: ждём /health — без этого UI показывает "Running"
            # хотя сервер ещё грузит модель (30-120 с для 27B)
            if not self.mgr.wait_for_ready(timeout_s=180, poll_s=1.0):
                tail = (self.mgr.tail_stderr(80) or "").strip() or "(пусто)"
                stdout = (self.mgr.tail_stdout(80) or "").strip() or "(пусто)"
                alive = "жив" if self.mgr.current() else "мёртв"
                raise RuntimeError(
                    f"Сервер не поднялся за 180 с.\n"
                    f"Процесс {alive}.\n\n"
                    f"--- stderr ---\n{tail}\n\n"
                    f"--- stdout ---\n{stdout}")
            return info

        def on_done(info):
            self._set_state("running")
            self._refresh_status()
            self.server_state_changed.emit()
            self.controller.store.insert_event(
                "start", pid=info.pid, model_name=info.model_name,
                ctx=info.ctx_size, kv_type=info.kv_type)
            # AC-4: start spill guard + layer proxy once server is confirmed running
            self.controller.start_server_side_services()

        def on_error(msg):
            # H6: kill the process if it's still running (wait_for_ready timeout)
            try:
                info = self.mgr.current()
                if info is not None and self.mgr.pid_store.is_alive(info):
                    self.mgr.stop(timeout_s=5)
            except Exception:
                pass
            self._set_state("stopped")
            self.error_label.setText(str(msg))
            self.controller.store.insert_event(
                "start_failed", details=str(msg))

        run_async(_job, on_done=on_done, on_error=on_error)

    def _on_stop(self) -> None:
        """FIX-A8: Stop через worker с проверкой is_alive()."""
        if self._state not in ("running", "starting"):
            return

        self._set_state("stopping")

        def _job():
            ok = self.mgr.stop(timeout_s=10)
            if not ok:
                raise RuntimeError(
                    "taskkill не смог завершить процесс; см. gui.log")
            # FIX-A8: гарантированная проверка — процесс реально мёртв
            import time
            time.sleep(0.5)
            if self.mgr.current() is not None:
                raise RuntimeError("Процесс всё ещё виден после stop()")
            return True

        def on_done(_):
            self._set_state("stopped")
            self._refresh_status()
            self.server_state_changed.emit()
            self.controller.store.insert_event("stop")

        def on_error(msg):
            # Процесс, вероятно, жив — возвращаемся в running
            self._set_state("running")
            self.error_label.setText(str(msg))

        run_async(_job, on_done=on_done, on_error=on_error)
