"""Tab 3 — Data Analytics: filters, cache-aware KPIs, drill-down chart (compact)."""
from __future__ import annotations

import datetime as _dt
import time

import pandas as pd

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from charts_widgets import ClickableStackedBarChart, DeepDiveChart
from data_loader import (apply_filters, load_logs, compute_cost_totals,
                        resolve_usage_path)
from i18n import t
from widgets import HintLabel, KpiRow, SectionTitle, run_async


class AnalyticsTab(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.cfg = controller.cfg
        self.store = controller.store
        self._df: pd.DataFrame | None = None
        self._filtered: pd.DataFrame | None = None
        self._build_ui()

        self.controller.settings_saved.connect(self._on_settings_changed)
        self._last_sample_reload = 0.0

        if hasattr(self.controller, "agent_collector"):
            self.controller.agent_collector.sample_ready.connect(self._on_agent_sample)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        v.addWidget(SectionTitle(t("analytics.title")))
        f = QHBoxLayout()
        f.setSpacing(4)

        f.addWidget(QLabel(t("analytics.model_filter") + ":"))
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._apply_filters)
        f.addWidget(self.model_combo, stretch=1)

        f.addWidget(QLabel(t("analytics.date_from")))
        self.from_year = QSpinBox(); self.from_year.setRange(2000, 2100); self.from_year.setValue(2024)
        self.from_month = QSpinBox(); self.from_month.setRange(1, 12); self.from_month.setValue(1)
        self.from_day = QSpinBox(); self.from_day.setRange(1, 31); self.from_day.setValue(1)
        for w in (self.from_year, self.from_month, self.from_day):
            w.setFixedWidth(64)
            f.addWidget(w)
        for w in (self.from_year, self.from_month, self.from_day):
            w.valueChanged.connect(self._on_date_changed)

        f.addWidget(QLabel(t("analytics.date_to")))
        self.to_year = QSpinBox(); self.to_year.setRange(2000, 2100); self.to_year.setValue(2024)
        self.to_month = QSpinBox(); self.to_month.setRange(1, 12); self.to_month.setValue(1)
        self.to_day = QSpinBox(); self.to_day.setRange(1, 31); self.to_day.setValue(1)
        for w in (self.to_year, self.to_month, self.to_day):
            w.setFixedWidth(64)
            f.addWidget(w)
        for w in (self.to_year, self.to_month, self.to_day):
            w.valueChanged.connect(self._on_date_changed)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(2)
        for label, days in (("7d", 7), ("30d", 30), ("90d", 90)):
            btn = QPushButton(label)
            btn.setFixedWidth(48)
            btn.clicked.connect(lambda _, d=days: self._set_preset(d))
            preset_row.addWidget(btn)
        ytd_btn = QPushButton("YTD")
        ytd_btn.setFixedWidth(48)
        ytd_btn.clicked.connect(lambda: self._set_preset(None))
        preset_row.addWidget(ytd_btn)
        f.addLayout(preset_row, stretch=1)

        reload_btn = QPushButton(t("analytics.reload"))
        reload_btn.clicked.connect(self.reload)
        f.addWidget(reload_btn)
        v.addLayout(f)

        self.hint = HintLabel("")
        v.addWidget(self.hint)

        self.kpis = KpiRow()
        self.kpis.add_card("input", "")
        self.kpis.add_card("output", "")
        self.kpis.add_card("cached_input", "")
        self.kpis.add_card("agent_cost", "")
        self._update_kpi_labels()
        v.addWidget(self.kpis)

        v.addWidget(SectionTitle(t("analytics.chart_title")))
        self.trend_chart = ClickableStackedBarChart(figsize=(9, 2.6))
        self.trend_chart.bar_clicked.connect(self._on_bar_clicked)
        v.addWidget(self.trend_chart)

        v.addWidget(SectionTitle(t("analytics.deep_dive", model="")))
        self.deep_chart = DeepDiveChart(figsize=(9, 2.6))
        v.addWidget(self.deep_chart)
        v.addStretch(1)

    # ------------------------------------------------------------------
    def _from_spinboxes(self) -> QDate:
        return QDate(self.from_year.value(), self.from_month.value(), self.from_day.value())

    def _to_spinboxes(self) -> QDate:
        return QDate(self.to_year.value(), self.to_month.value(), self.to_day.value())

    def _set_from_date(self, d: QDate) -> None:
        for w in (self.from_year, self.from_month, self.from_day):
            w.blockSignals(True)
        self.from_year.setValue(d.year()); self.from_month.setValue(d.month()); self.from_day.setValue(d.day())
        for w in (self.from_year, self.from_month, self.from_day):
            w.blockSignals(False)

    def _set_to_date(self, d: QDate) -> None:
        for w in (self.to_year, self.to_month, self.to_day):
            w.blockSignals(True)
        self.to_year.setValue(d.year()); self.to_month.setValue(d.month()); self.to_day.setValue(d.day())
        for w in (self.to_year, self.to_month, self.to_day):
            w.blockSignals(False)

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
        start = today.addDays(-days + 1) if days is not None else QDate(today.year(), 1, 1)
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
        try:
            current = self.controller.mgr.current()
            if current is not None and current.model_name:
                idx = self.model_combo.findData(current.model_name)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
        except Exception:
            pass
        if not getattr(self, "_dates_set_by_user", False):
            dmin = self._df["timestamp"].min().date()
            dmax = self._df["timestamp"].max().date()
            self._set_from_date(QDate(dmin.year, dmin.month, dmin.day))
            self._set_to_date(QDate(dmax.year, dmax.month, dmax.day))

    def showEvent(self, e):
        super().showEvent(e)
        if self._df is None or self._df.empty:
            self.reload()

    def _on_settings_changed(self) -> None:
        try:
            self._update_kpi_labels()
            self.reload()
        except Exception as e:
            import sys
            sys.stderr.write(f"[AnalyticsTab] _on_settings_changed error: {type(e).__name__}: {e}\n")

    def _update_kpi_labels(self) -> None:
        self.kpis.set_label("input", t("analytics.kpi_input"))
        self.kpis.set_label("output", t("analytics.kpi_output"))
        self.kpis.set_label("cached_input", t("analytics.kpi_cached_input"))
        self.kpis.set_label("agent_cost", t("analytics.kpi_agent_cost"))

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

    def _on_agent_sample(self, _sample: dict) -> None:
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
                import sys
                sys.stderr.write(f"[AnalyticsTab.reload] on_done error: {type(e).__name__}: {e}\n")

        def on_error(msg):
            try:
                self.hint.setText(f"Load error: {msg}")
            except Exception:
                pass

        path = resolve_usage_path(self.cfg.data_path or "")
        if path is not None:
            run_async(lambda: load_logs(str(path), costs, global_prices),
                      on_done=on_done, on_error=on_error)
        else:
            def _load_from_sqlite():
                df = self.store.get_agent_usage_df()
                if df.empty:
                    return pd.DataFrame()
                rename_map = {
                    "ts": "timestamp", "model": "model_name",
                    "cached_tokens": "prompt_cached_tokens", "cost": "cost_cny",
                }
                df = df.rename(columns=rename_map)
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", errors="coerce")
                if "request_count" not in df.columns:
                    df["request_count"] = 1
                return df
            run_async(_load_from_sqlite, on_done=on_done, on_error=on_error)

    def _apply_filters(self) -> None:
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
            return

        model = self.model_combo.currentData()
        d_from = self._from_spinboxes().toPython()
        d_to = self._to_spinboxes().toPython()
        models = [model] if model else None
        filtered = apply_filters(self._df, models, (d_from, d_to), None)
        self._filtered = filtered

        if filtered.empty:
            self.hint.setText(t("analytics.no_data"))
            self.kpis.set_value("input", "$0.0000", f"0.0000M tok @ ${pi:.4f}/M")
            self.kpis.set_value("output", "$0.0000", f"0.0000M tok @ ${po:.4f}/M")
            self.kpis.set_value("cached_input", "$0.0000", f"0.0000M tok @ ${pc:.4f}/M")
            self.kpis.set_value("agent_cost", "$0.0000", "in $0.0000 + cache $0.0000 + out $0.0000")
            self.trend_chart.render(pd.DataFrame(), self.cfg.chart_granularity)
            self.deep_chart.render(pd.DataFrame(), "", self.cfg.chart_granularity)
            return

        has_prices = (pi > 0 or po > 0 or pc > 0)
        self.hint.setText(
            "⚠ Set Input / Output / Cached prices in Settings to compute cost."
            if not has_prices else "")

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
        cached_total = (pd.to_numeric(filtered[cached_col], errors="coerce").fillna(0).sum()
                        if cached_col else 0.0)

        costs = compute_cost_totals(prompt_total, completion_total, cached_total, pi, po, pc)
        cost_input, cost_cached, cost_output = costs["input"], costs["cached"], costs["output"]

        self.kpis.set_value("input", f"${cost_input:.4f}",
                            f"{prompt_total/1e6:.4f}M tok @ ${pi:.4f}/M")
        self.kpis.set_value("output", f"${cost_output:.4f}",
                            f"{completion_total/1e6:.4f}M tok @ ${po:.4f}/M")
        self.kpis.set_value("cached_input", f"${cost_cached:.4f}",
                            f"{cached_total/1e6:.4f}M tok @ ${pc:.4f}/M")
        cost_overall = cost_input + cost_cached + cost_output
        self.kpis.set_value("agent_cost", f"${cost_overall:.4f}",
                            f"in ${cost_input:.4f} + cache ${cost_cached:.4f} + out ${cost_output:.4f}")

        self.trend_chart.render(filtered, self.cfg.chart_granularity)
        valid_models = filtered["model_name"].dropna()
        chosen = (model if model
                  else (valid_models.mode().iloc[0] if not valid_models.empty else None))
        if chosen is not None:
            sub = filtered[filtered["model_name"] == chosen]
            self.deep_chart.render(sub, str(chosen), self.cfg.chart_granularity)

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
        self.hint.setText(f"Drill-down: {model} · {date_str}")
