"""Tab 1 — Model selection and server launch (compact 1280×720 layout)."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QScrollArea,
    QVBoxLayout, QWidget,
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
        "ram_budget_cache_mib": 0, "ram_budget_ckpts": 8, "pool_mib": 42,
        "ckpt_every": 8192, "shared_pool": True,
        "top_k": 20, "temp": 0.6, "top_p": 0.95, "repeat_penalty": 1.1,
        "ubatch": 0, "batch_size": 0, "ngl": 999,
        "prefill_f16": False, "fa_chunk": False, "think": True,
        "harness_proof": False, "backend_sampling": True, "kq_mask_packed": False,
        "reasoning_budget_message": "Now produce the complete answer.",
        "reasoning_effort_fallback": "medium",
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
            on_error=lambda e: self.gpu_label.setText(f"⚠️ GPU query error: {e}"),
        )
        self._refresh_models()
        self._refresh_status()

    # ------------------------------------------------------------------
    # UI construction — compact single-column layout for 1280×720
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(4)

        # --- Top row: Preset selector + Save button ---
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        self.preset_combo = QComboBox()
        self._populate_presets()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_row.addWidget(QLabel(t("launch.preset")))
        preset_row.addWidget(self.preset_combo)

        save_btn = QPushButton(t("launch.save_preset"))
        save_btn.clicked.connect(self._save_preset)
        preset_row.addWidget(save_btn)
        root.addLayout(preset_row)

        # --- GPU / RAM info (compact, 2 lines) ---
        self.gpu_label = QLabel("—")
        self.gpu_label.setWordWrap(True)
        self.ram_label = QLabel("—")
        self.ram_label.setWordWrap(True)
        root.addWidget(self.gpu_label)
        root.addWidget(self.ram_label)

        # --- Model selection ---
        root.addWidget(SectionTitle(t("launch.model")))
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        rescan_btn = QPushButton(t("launch.rescan"))
        rescan_btn.clicked.connect(self._refresh_models)
        model_row.addWidget(self.model_combo, stretch=1)
        model_row.addWidget(rescan_btn)
        root.addLayout(model_row)
        self.model_hint = HintLabel("")
        root.addWidget(self.model_hint)

        # --- Context length row (ContextKvRow pattern) ---
        ctx_row = ContextKvRow(t("launch.context_length"))
        for c in (32768, 65536, 131072, 262144):
            ctx_row.combo.addItem(str(c), c)
        idx = ctx_row.combo.findData(self.cfg.default_context_length)
        if idx >= 0:
            ctx_row.combo.setCurrentIndex(idx)
        self.ctx_row = ctx_row
        root.addLayout(ctx_row)

        # --- KV cache type row (ContextKvRow pattern) ---
        kv_row = ContextKvRow(t("launch.kv_cache"))
        for kv in ("q8_0", "q5_0", "q4_0", "f16"):
            kv_row.combo.addItem(kv, kv)
        if self.cfg.default_kv_cache_type in ("q8_0", "q5_0", "q4_0", "f16"):
            kv_row.combo.setCurrentText(self.cfg.default_kv_cache_type)
        self.kv_row = kv_row
        root.addLayout(kv_row)

        # --- MTP toggle ---
        mtp_row = QHBoxLayout()
        mtp_row.setSpacing(4)
        self.mtp_switch = QCheckBox(t("launch.mtp"))
        self.mtp_switch.toggled.connect(
            lambda _: self._update_tkc(self.model_combo.currentData()))
        mtp_row.addWidget(self.mtp_switch)
        root.addLayout(mtp_row)

        # TKC depends on ctx and kv, so recompute on change
        self.ctx_row.combo.currentIndexChanged.connect(
            lambda _: self._update_tkc(self.model_combo.currentData()))
        self.ctx_row.custom_edit.textChanged.connect(
            lambda _: self._update_tkc(self.model_combo.currentData()))
        self.kv_row.combo.currentIndexChanged.connect(
            lambda _: self._update_tkc(self.model_combo.currentData()))

        # --- TKC KPI card ---
        tkc_card = KpiCard(t("launch.tkc_title"))
        self.tkc_value_label = tkc_card._value
        self.tkc_value_label.setStyleSheet(
            "font-size: 16px; font-weight: bold;"
        )
        root.addWidget(tkc_card)

        # --- Status / Start / Stop section ---
        root.addSpacing(4)
        root.addWidget(SectionTitle(t("status.running")))
        self.status_label = QLabel("—")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

        # FIX #4: LAN URL hint (shown when server is running)
        self.lan_hint = HintLabel("")
        root.addWidget(self.lan_hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.start_btn = QPushButton(t("launch.start_server"))
        self.start_btn.setProperty("role", "primary")
        self.start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_btn)

        self.stop_btn = QPushButton(t("launch.stop_server"))
        self.stop_btn.setProperty("role", "danger")
        self.stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self.stop_btn)
        root.addLayout(btn_row)

        self.error_label = QLabel("")
        self.error_label.setProperty("role", "err")
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.error_label)

        # --- Inline advanced settings (two-column scrollable layout) ---
        root.addSpacing(4)
        root.addWidget(SectionTitle(t("launch.advanced_settings")))
        self._build_advanced_inline()

    def _build_advanced_inline(self) -> None:
        """Build inline two-column advanced settings in a QScrollArea."""
        # Widget storage
        self._adv_int_edits: dict[str, QLineEdit] = {}
        self._adv_float_edits: dict[str, QLineEdit] = {}
        self._adv_bool_checks: dict[str, QCheckBox] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setContentsMargins(0, 0, 0, 0)

        inner_widget = QWidget()
        outer_layout = QVBoxLayout(inner_widget)
        outer_layout.setContentsMargins(12, 12, 12, 12)
        outer_layout.setSpacing(15)

        def _make_group(title: str):
            g = QGroupBox(title)
            f = QFormLayout(g)
            f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            f.setHorizontalSpacing(15)
            f.setVerticalSpacing(8)
            g.setContentsMargins(12, 16, 12, 10)
            return g, f

        def add_int(name: str, default: int, form):
            edit = QLineEdit(str(default))
            edit.setToolTip(t(f"adv.tooltip.{name}"))
            self._adv_int_edits[name] = edit
            form.addRow(t(f"adv.{name}"), edit)

        def add_float(name: str, default: float, form):
            edit = QLineEdit(str(default))
            edit.setToolTip(t(f"adv.tooltip.{name}"))
            self._adv_float_edits[name] = edit
            form.addRow(t(f"adv.{name}"), edit)

        def add_bool(name: str, default: bool, form):
            check = QCheckBox(t(f"adv.{name}"))
            check.setChecked(default)
            check.setToolTip(t(f"adv.tooltip.{name}"))
            self._adv_bool_checks[name] = check
            form.addRow("", check)

        # --- Group 1: Speculative Decoding ---
        g_spec, f_spec = _make_group(t("adv.group.spec_decoding"))
        add_int("spec_depth", 24576, f_spec)
        add_int("spec_deep", 4, f_spec)
        add_int("draft_window", 16384, f_spec)
        add_int("lookup_n", 32, f_spec)
        outer_layout.addWidget(g_spec)

        # --- Group 2: Memory & KV Cache ---
        g_mem, f_mem = _make_group(t("adv.group.memory_kv"))
        add_int("kv_vram_cells", 0, f_mem)
        add_int("stage_cells", 0, f_mem)
        add_int("ram_budget_cache_mib", 0, f_mem)
        add_int("ram_budget_ckpts", 8, f_mem)
        add_int("pool_mib", 42, f_mem)
        add_int("ckpt_every", 8192, f_mem)
        add_bool("shared_pool", True, f_mem)
        outer_layout.addWidget(g_mem)

        # --- Group 3: Sampling ---
        g_samp, f_samp = _make_group(t("adv.group.sampling"))
        add_int("top_k", 20, f_samp)
        add_float("temp", 0.6, f_samp)
        add_float("top_p", 0.95, f_samp)
        add_float("repeat_penalty", 1.1, f_samp)
        outer_layout.addWidget(g_samp)

        # --- Group 4: Batch & Compute ---
        g_batch, f_batch = _make_group(t("adv.group.batch_compute"))
        add_int("ubatch", 0, f_batch)
        add_int("batch_size", 0, f_batch)
        add_int("ngl", 999, f_batch)
        add_bool("prefill_f16", False, f_batch)
        add_bool("fa_chunk", False, f_batch)
        add_bool("think", True, f_batch)
        add_bool("harness_proof", False, f_batch)
        add_bool("backend_sampling", True, f_batch)
        add_bool("kq_mask_packed", False, f_batch)
        outer_layout.addWidget(g_batch)

        # --- Group 5: Other ---
        g_other, f_other = _make_group(t("adv.group.other"))
        self._extra_args_edit = QLineEdit()
        self._extra_args_edit.setPlaceholderText("")
        f_other.addRow(t("launch.extra_args"), self._extra_args_edit)

        self._reasoning_msg_edit = QLineEdit()
        self._reasoning_msg_edit.setPlaceholderText("Now produce the complete answer.")
        f_other.addRow(t("adv.reasoning_budget_message"), self._reasoning_msg_edit)

        self._reasoning_fallback_edit = QLineEdit()
        self._reasoning_fallback_edit.setPlaceholderText("medium")
        f_other.addRow(t("adv.reasoning_effort_fallback"), self._reasoning_fallback_edit)
        outer_layout.addWidget(g_other)

        scroll.setWidget(inner_widget)
        self.layout().addWidget(scroll)

    def _read_adv_opts(self) -> dict:
        """Read all inline advanced settings into a dict."""
        opts = {}
        for name, edit in self._adv_int_edits.items():
            try:
                opts[name] = int(edit.text().strip() or "0")
            except ValueError:
                pass
        for name, edit in self._adv_float_edits.items():
            try:
                opts[name] = float(edit.text().strip() or "0.0")
            except ValueError:
                pass
        for name, check in self._adv_bool_checks.items():
            opts[name] = check.isChecked()
        opts["extra_args"] = self._extra_args_edit.text()
        opts["reasoning_budget_message"] = self._reasoning_msg_edit.text().strip()
        opts["reasoning_effort_fallback"] = self._reasoning_fallback_edit.text().strip() or "medium"
        return opts

    def _write_adv_opts(self, opts: dict) -> None:
        """Write a dict of advanced settings into the inline widgets."""
        for name, edit in self._adv_int_edits.items():
            if name in opts:
                edit.setText(str(opts[name]))
        for name, edit in self._adv_float_edits.items():
            if name in opts:
                edit.setText(str(opts[name]))
        for name, check in self._adv_bool_checks.items():
            if name in opts:
                check.setChecked(bool(opts[name]))
        if "extra_args" in opts:
            self._extra_args_edit.setText(opts["extra_args"])
        if "reasoning_budget_message" in opts:
            self._reasoning_msg_edit.setText(opts["reasoning_budget_message"])
        if "reasoning_effort_fallback" in opts:
            self._reasoning_fallback_edit.setText(opts["reasoning_effort_fallback"])

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
                "effort": "medium",       # harness-proofing: safe for all clients
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
                "effort": "medium",       # harness-proofing: safe for all clients
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
            on_error=lambda e: self.gpu_label.setText(f"⚠️ GPU query error: {e}"),
        )

    def _on_gpu_snapshot(self, snap) -> None:
        """Handle GPU snapshot result (runs in main thread via Qt signal)."""
        gpus = snap["gpus"]
        self._gpu = gpus[0] if gpus else None

        if self._gpu:
            self.gpu_label.setText(
                f"<b>{self._gpu.name}</b> · VRAM "
                f"{self._gpu.used_mib}/{self._gpu.total_mib} MiB · "
                f"free <b>{self._gpu.free_mib} MiB</b>")
        else:
            self.gpu_label.setText(
                "⚠️ nvidia-smi unavailable — VRAM planning limited")

        ram_info = compute_ram_budget(self.cfg)
        pc_bytes = ram_info.get("prompt_cache_bytes")
        pc_mib = int(pc_bytes / (1024 * 1024)) if pc_bytes else 0
        ck = ram_info.get("checkpoint_count", 0)
        self.ram_label.setText(
            f"RAM: <b>{ram_info['total_gb']:.1f} GB</b> total · "
            f"<b>{ram_info['free_gb']:.1f} GB</b> free · "
            f"prompt cache <code>{pc_mib if pc_mib else 'default'} MiB</code> · "
            f"checkpoints <code>{ck if ck else 'default'}</code>")

    def _refresh_models(self) -> None:
        """Rescan models. Crash-proof: signals are always released in finally."""

        def on_done(models):
            self._models = models
            try:
                self.model_combo.blockSignals(True)
                self.model_combo.clear()
                if not models:
                    self.model_combo.addItem("— no .gguf —", None)
                    self.model_hint.setText(
                        f"No .gguf > {self.cfg.model_min_size_gb} GB found in "
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
                f'<span style="color:#2ecc71">● Running · '
                f'PID <b>{info.pid}</b></span>')
            self.info_label.setText(
                f"model <code>{info.model_name}</code> · "
                f"ctx <code>{info.ctx_size}</code> · "
                f"kv <code>{info.kv_type}</code> · "
                f"started "
                f"{datetime.fromtimestamp(info.started_at).strftime('%H:%M:%S')}")
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

        # H5: PS1 logic — small GPU (≤8704 MiB) gets reduced spec params
        if self._gpu and int(self._gpu.total_mib) <= 8704:
            if opts.get("use_mtp"):
                opts["spec_n_max"] = 1
            opts["spec_deep"] = 1
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
