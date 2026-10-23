"""Tab 3 — Data Analytics: filters (spinbox dates + presets), cache-aware KPIs, drill-down, heatmap."""
from __future__ import annotations

import datetime as _dt
import time
from pathlib import Path

import pandas as pd

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSpinBox, QTableView, QVBoxLayout, QWidget,
)

from charts_widgets import ClickableStackedBarChart, DeepDiveChart, HeatmapChart
from data_loader import (DISPLAY_COLUMNS, apply_filters, load_logs,
                        compute_cost_totals, resolve_usage_path)
from i18n import t
from widgets import HintLabel, KpiRow, SectionTitle, run_async


class DataFrameModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self._df = df.reset_index(drop=True)

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if role == Qt.DisplayRole:
            try:
                val = self._df.iloc[row, col]
            except Exception:
                return None
            if isinstance(val, float):
                return f"{val:.4f}"
            return str(val)
        if role == Qt.TextAlignmentRole:
            # FIX: .iloc[row, col] returns a scalar (Timestamp/str) with no .dtype.
            # Check the whole column's dtype instead to decide numeric alignment.
            try:
                if self._df.iloc[:, col].dtype.kind in "if":
                    return int(Qt.AlignRight | Qt.AlignVCenter)
            except Exception:
                pass
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    def update(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df.reset_index(drop=True)
        self.endResetModel()


class AnalyticsTab(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.cfg = controller.cfg
        self.store = controller.store
        self._df: pd.DataFrame | None = None
        self._filtered: pd.DataFrame | None = None
        self._build_ui()

        # Live apply: update labels + reload when settings change
        self.controller.settings_saved.connect(self._on_settings_changed)

        # BUG 4: initialize throttle timer before connecting signal.
        self._last_sample_reload = 0.0

        # Real-time agent cost updates from collector
        if hasattr(self.controller, "agent_collector"):
            self.controller.agent_collector.sample_ready.connect(self._on_agent_sample)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)

        # --- Filters row ---
        v.addWidget(SectionTitle(t("analytics.title")))
        f = QHBoxLayout()

        # Model filter
        f.addWidget(QLabel(t("analytics.model_filter") + ":"))
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._apply_filters)
        f.addWidget(self.model_combo, stretch=1)

        # From date: Y/M/D spinboxes
        f.addWidget(QLabel(t("analytics.date_from")))
        self.from_year = QSpinBox(); self.from_year.setRange(2000, 2100); self.from_year.setValue(2024)
        self.from_month = QSpinBox(); self.from_month.setRange(1, 12); self.from_month.setValue(1)
        self.from_day = QSpinBox(); self.from_day.setRange(1, 31); self.from_day.setValue(1)
        for w in (self.from_year, self.from_month, self.from_day):
            f.addWidget(w)
        self.from_year.valueChanged.connect(self._on_date_changed)
        self.from_month.valueChanged.connect(self._on_date_changed)
        self.from_day.valueChanged.connect(self._on_date_changed)

        # To date: Y/M/D spinboxes
        f.addWidget(QLabel(t("analytics.date_to")))
        self.to_year = QSpinBox(); self.to_year.setRange(2000, 2100); self.to_year.setValue(2024)
        self.to_month = QSpinBox(); self.to_month.setRange(1, 12); self.to_month.setValue(1)
        self.to_day = QSpinBox(); self.to_day.setRange(1, 31); self.to_day.setValue(1)
        for w in (self.to_year, self.to_month, self.to_day):
            f.addWidget(w)
        self.to_year.valueChanged.connect(self._on_date_changed)
        self.to_month.valueChanged.connect(self._on_date_changed)
        self.to_day.valueChanged.connect(self._on_date_changed)

        # Quick presets
        preset_row = QHBoxLayout()
        for label, days in (("7d", 7), ("30d", 30), ("90d", 90)):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, d=days: self._set_preset(d))
            preset_row.addWidget(btn)
        ytd_btn = QPushButton("YTD")
        ytd_btn.clicked.connect(lambda: self._set_preset(None))
        preset_row.addWidget(ytd_btn)
        f.addLayout(preset_row, stretch=1)

        reload_btn = QPushButton(t("analytics.reload"))
        reload_btn.clicked.connect(self.reload)
        f.addWidget(reload_btn)
        v.addLayout(f)

        self.hint = HintLabel("")
        v.addWidget(self.hint)

        # --- KPI row (3-price + agent cost) ---
        self.kpis = KpiRow()
        self.kpis.add_card("input", "")
        self.kpis.add_card("output", "")
        self.kpis.add_card("cached_input", "")
        self.kpis.add_card("agent_cost", "")
        self._update_kpi_labels()
        v.addWidget(self.kpis)

        # --- Charts ---
        v.addWidget(SectionTitle(t("analytics.chart_title")))
        self.trend_chart = ClickableStackedBarChart(figsize=(9, 3))
        self.trend_chart.bar_clicked.connect(self._on_bar_clicked)
        v.addWidget(self.trend_chart)

        v.addWidget(SectionTitle(t("analytics.deep_dive", model="")))
        self.deep_chart = DeepDiveChart(figsize=(9, 3))
        v.addWidget(self.deep_chart)

        v.addWidget(SectionTitle(t("analytics.heatmap", model="")))
        self.heat_chart = HeatmapChart(figsize=(9, 3))
        v.addWidget(self.heat_chart)

        # --- Data table ---
        v.addWidget(SectionTitle(t("analytics.data_table")))
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setSortingEnabled(True)
        self.table_model = DataFrameModel(pd.DataFrame())
        self.table.setModel(self.table_model)
        v.addWidget(self.table, stretch=1)

    # ------------------------------------------------------------------
    # Date helpers
    # ------------------------------------------------------------------
    def _from_spinboxes(self) -> QDate:
        return QDate(
            self.from_year.value(), self.from_month.value(), self.from_day.value())

    def _to_spinboxes(self) -> QDate:
        return QDate(
            self.to_year.value(), self.to_month.value(), self.to_day.value())

    def _set_from_date(self, d: QDate) -> None:
        self.from_year.blockSignals(True)
        self.from_month.blockSignals(True)
        self.from_day.blockSignals(True)
        self.from_year.setValue(d.year())
        self.from_month.setValue(d.month())
        self.from_day.setValue(d.day())
        self.from_year.blockSignals(False)
        self.from_month.blockSignals(False)
        self.from_day.blockSignals(False)

    def _set_to_date(self, d: QDate) -> None:
        self.to_year.blockSignals(True)
        self.to_month.blockSignals(True)
        self.to_day.blockSignals(True)
        self.to_year.setValue(d.year())
        self.to_month.setValue(d.month())
        self.to_day.setValue(d.day())
        self.to_year.blockSignals(False)
        self.to_month.blockSignals(False)
        self.to_day.blockSignals(False)

    def _on_date_changed(self) -> None:
        d_from = self._from_spinboxes().toPython()
        d_to = self._to_spinboxes().toPython()
        if not (d_from and d_to):
            return
        try:
            _dt.date(d_from.year, d_from.month, d_from.day)
            _dt.date(d_to.year, d_to.month, d_to.day)
        except ValueError:
            return
        self._dates_set_by_user = True
        self._apply_filters()

    def _set_preset(self, days: int | None) -> None:
        today = QDate.currentDate()
        if days is not None:
            start = today.addDays(-days + 1)
        else:  # YTD
            start = QDate(today.year(), 1, 1)
        self._set_from_date(start)
        self._set_to_date(today)
        self._dates_set_by_user = True
        self._apply_filters()

    def _populate_filters(self) -> None:
        if self._df is None or self._df.empty:
            return
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem(t("analytics.all_models"), None)
        for m in sorted(self._df["model_name"].dropna().unique()):
            self.model_combo.addItem(str(m), str(m))
        self.model_combo.blockSignals(False)

        # Point 5: auto-select the currently running model if one exists.
        try:
            current = self.controller.mgr.current()
            if current is not None and current.model_name:
                idx = self.model_combo.findData(current.model_name)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
        except Exception:
            pass

        # FIX P0-5: auto-adjust dates only when user hasn't manually set them.
        # Re-evaluates on every reload so new data extends the range automatically.
        if not getattr(self, "_dates_set_by_user", False):
            dmin = self._df["timestamp"].min().date()
            dmax = self._df["timestamp"].max().date()
            self._set_from_date(QDate(dmin.year, dmin.month, dmin.day))
            self._set_to_date(QDate(dmax.year, dmax.month, dmax.day))

    # ------------------------------------------------------------------
    # Reload / filter / display
    # ------------------------------------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        if self._df is None or self._df.empty:
            self.reload()

    def _on_settings_changed(self) -> None:
        """Обновить заголовки KPI, карточку агента и перезагрузить данные при смене настроек."""
        try:
            self._update_kpi_labels()
            self.reload()
        except Exception as e:
            import sys
            sys.stderr.write(f"[AnalyticsTab] _on_settings_changed error: {type(e).__name__}: {e}\n")

    def _update_kpi_labels(self) -> None:
        """Обновляет заголовки карточек (валюта всегда $)."""
        self.kpis.set_label("input", t("analytics.kpi_input"))
        self.kpis.set_label("output", t("analytics.kpi_output"))
        self.kpis.set_label("cached_input", t("analytics.kpi_cached_input"))
        self.kpis.set_label("agent_cost", t("analytics.kpi_agent_cost"))

    # ------------------------------------------------------------------
    # Agent cost helpers (real-time from collector + recompute with current prices)
    # ------------------------------------------------------------------
    def _current_ts_range(self) -> tuple[float, float]:
        import datetime as _dtm
        import time as _t
        d_from = self._from_spinboxes().toPython()
        d_to = self._to_spinboxes().toPython()
        if not (d_from and d_to):
            return 0.0, _t.time()
        try:
            from_ts = _dtm.datetime(d_from.year, d_from.month, d_from.day, 0, 0, 0).timestamp()
            to_ts = _dtm.datetime(d_to.year, d_to.month, d_to.day, 23, 59, 59).timestamp()
        except (ValueError, OverflowError):
            return 0.0, _t.time()
        return from_ts, to_ts

    def _refresh_agent_cost(self) -> None:
        from_ts, to_ts = self._current_ts_range()
        try:
            totals = self.store.get_agent_totals(from_ts, to_ts)
        except Exception:
            totals = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}

        pi = float(self.cfg.price_input_per_1m)
        po = float(self.cfg.price_output_per_1m)
        pc = float(self.cfg.price_cached_input_per_1m)

        prompt = float(totals["prompt_tokens"])
        completion = float(totals["completion_tokens"])
        cached = min(float(totals["cached_tokens"]), prompt)
        non_cached = max(prompt - cached, 0.0)
        total = (non_cached / 1e6 * pi
                 + cached / 1e6 * pc
                 + completion / 1e6 * po)

        self.kpis.set_value(
            "agent_cost",
            f"${total:.4f}",
            f"in {prompt / 1e6:.3f}M · out {completion / 1e6:.3f}M")

    def _on_agent_sample(self, _sample: dict) -> None:
        # BUG 8: throttle with time.monotonic() (NTP-safe).
        # Realtime: обновляем KPI только если вкладка видима.
        if not self.isVisible():
            return
        now = time.monotonic()
        if now - self._last_sample_reload < 5.0:
            return
        self._last_sample_reload = now
        self.reload()

    def reload(self) -> None:
        costs = self.cfg.model_costs.copy()
        global_prices = {
            "input": self.cfg.price_input_per_1m,
            "output": self.cfg.price_output_per_1m,
            "cached": self.cfg.price_cached_input_per_1m,
        }

        def on_done(df):
            try:
                self._df = df
                self._populate_filters()
                self._apply_filters()
            except Exception as e:
                # P1: catch ALL exceptions (RuntimeError from deleted widgets,
                # AttributeError, etc.) to prevent app crash.
                import sys
                sys.stderr.write(f"[AnalyticsTab.reload] on_done error: {type(e).__name__}: {e}\n")

        def on_error(msg):
            try:
                self.hint.setText(f"Load error: {msg}")
            except Exception as e:
                import sys
                sys.stderr.write(f"[AnalyticsTab.reload] on_error: {type(e).__name__}: {e}\n")

        # FIX P0-cost: data_path may point at a stale/nonexistent usage.csv;
        # fall back to the real artifacts/agent_usage.csv.
        path = resolve_usage_path(self.cfg.data_path or "")

        if path is not None:
            run_async(
                lambda: load_logs(str(path), costs, global_prices),
                on_done=on_done, on_error=on_error)
        else:
            # FIX P0-2/P0-3: read from SQLite agent_usage table as primary source.
            def _load_from_sqlite():
                df = self.store.get_agent_usage_df()
                if df.empty:
                    return pd.DataFrame()
                # Normalize columns to match load_logs schema (P0-4)
                rename_map = {
                    "ts": "timestamp",
                    "model": "model_name",
                    "cached_tokens": "prompt_cached_tokens",
                    "cost": "cost_cny",
                }
                df = df.rename(columns=rename_map)
                # FIX: ts is Unix seconds (float) — convert to datetime64[ns]
                # so that .min().date() / .dt.date work in _populate_filters.
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", errors="coerce")
                # FIX: aggregate() requires request_count column (default 1 per row)
                if "request_count" not in df.columns:
                    df["request_count"] = 1
                return df

            run_async(_load_from_sqlite, on_done=on_done, on_error=on_error)

    def _apply_filters(self) -> None:

        # hoisted: нужны и в пустых ветках, и в основной
        pi = float(self.cfg.price_input_per_1m)
        po = float(self.cfg.price_output_per_1m)
        pc = float(self.cfg.price_cached_input_per_1m)

        if self._df is None or self._df.empty:
            self.kpis.set_value("input", "$0.0000", f"0.0000M tok @ ${pi:.4f}/M")
            self.kpis.set_value("output", "$0.0000", f"0.0000M tok @ ${po:.4f}/M")
            self.kpis.set_value("cached_input", "$0.0000", f"0.0000M tok @ ${pc:.4f}/M")
            self.kpis.set_value("agent_cost", "$0.0000", "in $0.0000 + cache $0.0000 + out $0.0000")

            self.hint.setText(t("analytics.no_data"))
            self.trend_chart.render(pd.DataFrame(), self.cfg.chart_granularity)
            self.deep_chart.render(pd.DataFrame(), "", self.cfg.chart_granularity)
            self.heat_chart.render(pd.DataFrame(), "")
            self.table_model.update(pd.DataFrame())
            return
        model = self.model_combo.currentData()
        d_from = self._from_spinboxes().toPython()
        d_to = self._to_spinboxes().toPython()
        models = [model] if model else None

        filtered = apply_filters(self._df, models, (d_from, d_to), None)
        self._filtered = filtered

        # FIX 1b: return on empty DataFrame — clear table too
        if filtered.empty:
            self.hint.setText(t("analytics.no_data"))
            self.kpis.set_value("input", "$0.0000", f"0.0000M tok @ ${pi:.4f}/M")
            self.kpis.set_value("output", "$0.0000", f"0.0000M tok @ ${po:.4f}/M")
            self.kpis.set_value("cached_input", "$0.0000", f"0.0000M tok @ ${pc:.4f}/M")
            self.kpis.set_value("agent_cost", "$0.0000", "in $0.0000 + cache $0.0000 + out $0.0000")
            self.trend_chart.render(pd.DataFrame(), self.cfg.chart_granularity)
            self.deep_chart.render(pd.DataFrame(), "", self.cfg.chart_granularity)
            self.heat_chart.render(pd.DataFrame(), "")
            self.table_model.update(pd.DataFrame())
            return

        # Подсказка, если цены не заданы
        has_prices = (
            self.cfg.price_input_per_1m > 0
            or self.cfg.price_output_per_1m > 0
            or self.cfg.price_cached_input_per_1m > 0
        )
        if not has_prices:
            self.hint.setText(
                "⚠ Set Input / Output / Cached prices in Settings to compute cost.")
        else:
            self.hint.setText("")

        # --- 3-price KPIs (pi/po/pc определены в начале метода) ---
        prompt_total = pd.to_numeric(
            filtered.get("prompt_tokens", pd.Series(0, index=filtered.index)),
            errors="coerce").fillna(0).sum()

        completion_total = pd.to_numeric(
            filtered.get("completion_tokens", pd.Series(0, index=filtered.index)),
            errors="coerce").fillna(0).sum()

        cached_col = None
        for col in ("prompt_cached_tokens", "cache_hit_tokens"):
            if col in filtered.columns:
                cached_col = col
                break
        cached_total = (
            pd.to_numeric(filtered[cached_col], errors="coerce").fillna(0).sum()
            if cached_col else 0.0
        )
        # FIX P0-cost: disjoint llama.cpp counters — sum both parts, no clamp.
        costs = compute_cost_totals(prompt_total, completion_total, cached_total,
                                    pi, po, pc)
        cost_input = costs["input"]
        cost_cached = costs["cached"]
        cost_output = costs["output"]

        self.kpis.set_value(
            "input",
            f"${cost_input:.4f}",
            f"{prompt_total/1e6:.4f}M tok @ ${pi:.4f}/M")
        self.kpis.set_value(
            "output",
            f"${cost_output:.4f}",
            f"{completion_total/1e6:.4f}M tok @ ${po:.4f}/M")
        self.kpis.set_value(
            "cached_input",
            f"${cost_cached:.4f}",
            f"{cached_total/1e6:.4f}M tok @ ${pc:.4f}/M")

        cost_overall = cost_input + cost_cached + cost_output
        self.kpis.set_value(
            "agent_cost",
            f"${cost_overall:.4f}",
            f"in ${cost_input:.4f} + cache ${cost_cached:.4f} + out ${cost_output:.4f}")

        # --- Charts ---
        self.trend_chart.render(filtered, self.cfg.chart_granularity)
        if not filtered.empty:
            valid_models = filtered["model_name"].dropna()
            chosen = (model if model
                      else (valid_models.mode().iloc[0] if not valid_models.empty else None))
            if chosen is not None:
                sub = filtered[filtered["model_name"] == chosen]
                self.deep_chart.render(sub, str(chosen), self.cfg.chart_granularity)
                self.heat_chart.render(sub, str(chosen))

        # --- Table ---
        cols = [c for c in DISPLAY_COLUMNS if c in filtered.columns]
        extra_cols = ["cache_hit_tokens", "cache_miss_tokens"]
        for ec in extra_cols:
            if ec in filtered.columns and ec not in cols:
                cols.append(ec)

        display = filtered[cols].sort_values("timestamp", ascending=False).head(30).copy()
        if "cost_cny" in display.columns:
            display = display.rename(columns={"cost_cny": "cost ($)"})
        self.table_model.update(display)

        # Point 9: set sensible default column widths.
        for col_idx, col_name in enumerate(self.table_model._df.columns):
            name = str(col_name).lower()
            if "model" in name:
                self.table.setColumnWidth(col_idx, 280)
            elif "cost" in name:
                self.table.setColumnWidth(col_idx, 90)
            elif name == "timestamp":
                self.table.setColumnWidth(col_idx, 160)
            else:
                self.table.setColumnWidth(col_idx, 110)

    def _on_bar_clicked(self, model: str, date_str: str) -> None:
        target = QDate.fromString(date_str, "yyyy-MM-dd")
        if not target.isValid():
            return
        idx = self.model_combo.findData(model)
        if idx >= 0:
            self.model_combo.blockSignals(True)
            self.model_combo.setCurrentIndex(idx)
            self.model_combo.blockSignals(False)
        self._set_from_date(target)
        self._set_to_date(target)
        self._apply_filters()
        self.hint.setText(f"Drill-down: {model} \u00b7 {date_str}")
