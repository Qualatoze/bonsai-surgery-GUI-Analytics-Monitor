"""Matplotlib-канвасы в Qt для всех графиков (динамическая тема)."""
from __future__ import annotations

import matplotlib
matplotlib.use("QtAgg")

import numpy as np
import pandas as pd
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout

from data_loader import aggregate
from i18n import t
from theme import get_colors

# Текущая тема для новых канвасов (обновляется в apply_chart_theme).
_CURRENT_CHART_THEME = "one_dark"
_RCPARAMS_APPLIED = False


def apply_chart_theme(theme_name: str = "one_dark", force: bool = False) -> None:
    """Обновляет глобальные rcParams matplotlib под заданную цветовую схему."""
    global _CURRENT_CHART_THEME, _RCPARAMS_APPLIED
    if not force and theme_name == _CURRENT_CHART_THEME and _RCPARAMS_APPLIED:
        return
    _CURRENT_CHART_THEME = theme_name
    _RCPARAMS_APPLIED = True
    c = get_colors(theme_name)
    palette = c.get("palette", ["#6C5CE7", "#00D2FF", "#FF7675"])
    rcParams.update({
        "figure.facecolor": c["bg"],
        "axes.facecolor": c["card_bg"],
        "savefig.facecolor": c["card_bg"],
        "text.color": c["text"],
        "axes.labelcolor": c["muted"],
        "axes.titlecolor": c["text"],
        "xtick.color": c["muted"],
        "ytick.color": c["muted"],
        "axes.edgecolor": c["border"],
        "grid.color": c["border"],
        "grid.alpha": 0.15,
        "font.family": "Segoe UI",
        "font.size": 8,
        "axes.titlesize": 10,
        "axes.titleweight": "bold",
    })


class BaseChart(QFrame):
    """Базовый matplotlib-канвас в Qt. Поддерживает динамическую смену темы."""

    def __init__(self, title: str = "", figsize=(7, 3.5), parent=None,
               theme_name: str | None = None):
        super().__init__(parent)
        self._theme_name = theme_name or _CURRENT_CHART_THEME
        self._colors = get_colors(self._theme_name)
        # FIX: применяем rcParams ДО создания Figure, иначе фон будет белым
        apply_chart_theme(self._theme_name)
        self.setStyleSheet(self._frame_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.figure = Figure(figsize=figsize, tight_layout=True)
        # FIX: явно задаём facecolor фигуры (rcParams не всегда подхватываются)
        self.figure.set_facecolor(self._colors["bg"])
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas)
        self._title = title

    def _frame_style(self) -> str:
        c = self._colors
        return (
            f"QFrame {{ background-color: {c['card_bg']}; "
            f"border: 1px solid {c['border']}; border-radius: 8px; }}"
        )

    def _palette(self) -> list[str]:
        """Возвращает палитру текущей темы."""
        return self._colors.get("palette", ["#6C5CE7", "#00D2FF", "#FF7675"])

    def set_theme(self, theme_name: str) -> None:
        """Переключает тему этого канваса и обновляет rcParams глобально."""
        self._theme_name = theme_name
        self._colors = get_colors(theme_name)
        self.setStyleSheet(self._frame_style())
        apply_chart_theme(theme_name, force=True)
        # FIX: обновляем facecolor существующей фигуры и её осей
        self.figure.set_facecolor(self._colors["bg"])
        for ax in self.figure.axes:
            ax.set_facecolor(self._colors["card_bg"])
        self.redraw()

    def redraw(self) -> None:
        self.canvas.draw_idle()

    def _clear(self) -> None:
        self.figure.clear()

    def _render_empty_state(self, message: str = "") -> None:
        """Renders a dark placeholder with centered text when there's no data."""
        self._clear()
        ax = self.figure.add_subplot(111)
        c = self._colors
        ax.set_facecolor(c["card_bg"])
        ax.axis("off")
        display_msg = message or "—"
        ax.text(0.5, 0.5, display_msg,
                ha="center", va="center",
                color=c["muted"], fontsize=12,
                transform=ax.transAxes)
        self.redraw()

    def close(self) -> None:
        """Clear chart content without destroying the canvas."""
        try:
            self._clear()
            if getattr(self, "canvas", None) is not None:
                self.canvas.draw_idle()
        except Exception:
            pass


class ClickableStackedBarChart(BaseChart):
    """Стековый бар с drill-down: клик по сегменту → (model, date_str)."""

    bar_clicked = Signal(str, str)

    def __init__(self, title: str = "", figsize=(7, 3.5), parent=None):
        super().__init__(title, figsize, parent)
        self._bar_meta: list = []
        self.canvas.mpl_connect("button_press_event", self._on_click)

    def render(self, df: pd.DataFrame, granularity: str = "daily") -> None:
        self._clear()
        self._bar_meta.clear()
        if df.empty:
            self._render_empty_state(t("analytics.no_data"))
            return
        agg = aggregate(df, granularity)
        if agg.empty:
            self._render_empty_state(t("analytics.no_data"))
            return
        pivot = agg.pivot_table(
            index="timestamp", columns="model_name",
            values="cost_cny", aggfunc="sum", fill_value=0,
        )
        pivot = pivot.fillna(0.0)
        if pivot.empty or float(pivot.values.sum()) == 0.0:
            self._render_empty_state(t("analytics.no_cost_data"))
            return

        ax = self.figure.add_subplot(111)
        n = len(pivot)
        x = np.arange(n)
        bottoms = np.zeros(n)
        pal = self._palette()
        c = self._colors

        for i, col in enumerate(pivot.columns):
            values = pivot[col].values
            bars = ax.bar(
                x, values, bottom=bottoms,
                color=pal[i % len(pal)],
                width=0.8, edgecolor="none", label=str(col),
            )
            for j, rect in enumerate(bars):
                date_str = str(pivot.index[j].date())
                self._bar_meta.append((rect, str(col), date_str))
            bottoms = bottoms + values

        ax.set_xticks(x)
        labels = [str(idx.date()) for idx in pivot.index]
        ax.set_xticklabels(labels)
        step = max(1, n // 12)
        for i, lab in enumerate(ax.get_xticklabels()):
            lab.set_visible(i % step == 0)

        ax.set_title(t("analytics.chart_title"), fontsize=10, color=c["text"])
        ax.set_ylabel(t("chart.y_cost"), fontsize=8, color=c["muted"])
        ax.grid(axis="y", alpha=0.15)
        ax.legend(loc="upper left", frameon=False, fontsize=7)
        self.redraw()

    def _on_click(self, event) -> None:
        if event.inaxes is None:
            return
        for rect, model, date_str in reversed(self._bar_meta):
            try:
                if rect.contains(event)[0]:
                    self.bar_clicked.emit(model, date_str)
                    return
            except Exception:
                continue

    def close(self) -> None:
        """Release drill-down bar metadata before the base teardown."""
        try:
            self._bar_meta.clear()
        except Exception:
            pass
        super().close()


class LiveResourceChart(BaseChart):
    def render(self, samples_df: pd.DataFrame, window_minutes: int = 10) -> None:
        self._clear()
        if samples_df.empty:
            self._render_empty_state(t("analytics.no_data"))
            return
        import matplotlib.dates as mdates
        df = samples_df.copy()
        # FIX: actually use window_minutes to filter the data range.
        if window_minutes > 0 and "ts" in df.columns:
            cutoff_ts = float(df["ts"].max()) - window_minutes * 60
            df = df[df["ts"] >= cutoff_ts]
            if df.empty:
                self._render_empty_state(t("analytics.no_data"))
                return
        df["dt"] = pd.to_datetime(df["ts"], unit="s")

        ax = self.figure.add_subplot(111)
        pal = self._palette()
        c = self._colors

        # Neon line colors from theme palette: emerald, blue, purple
        ax.plot(df["dt"], df["rss_mb"], color=pal[0],
                label=t("monitor.ram"), linewidth=1.5)
        ax.plot(df["dt"], df["vms_mb"], color=pal[1],
                label="VMS (MB)", linewidth=1, linestyle="--")
        ax.set_ylabel(t("monitor.ram"), fontsize=8, color=c["muted"])
        ax.grid(axis="y", alpha=0.15)

        ax2 = ax.twinx()
        ax2.plot(df["dt"], df["cpu_pct"], color=pal[2],
                label=t("monitor.cpu"), linewidth=1, alpha=0.8)
        ax2.set_ylabel(t("monitor.cpu"), color=pal[2])
        ax2.tick_params(axis="y", colors=pal[2])

        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2,
                  loc="upper left", frameon=False, fontsize=7)

        ax.set_title(t("monitor.live_chart_title"), fontsize=10, color=c["text"])
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        for lab in ax.get_xticklabels():
            lab.set_rotation(0)
            lab.set_ha("center")
        self.redraw()


class DeepDiveChart(BaseChart):
    def render(self, df: pd.DataFrame, model_name: str,
               granularity: str = "daily") -> None:
        self._clear()
        if df.empty:
            self._render_empty_state(t("analytics.no_data"))
            return
        freq = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}.get(
            granularity, "D")
        agg = (
            df.set_index("timestamp")
              .groupby(pd.Grouper(freq=freq))
              .agg(
                  prompt_tokens=("prompt_tokens", "sum"),
                  completion_tokens=("completion_tokens", "sum"),
                  cost_cny=("cost_cny", "sum"),
              )
              .reset_index()
        )
        ax = self.figure.add_subplot(111)
        pal = self._palette()
        c = self._colors

        ax.plot(agg["timestamp"], agg["prompt_tokens"],
                color=pal[0], marker="o", linewidth=2,
                label=t("analytics.kpi_output_1m").split("(")[0].strip())
        ax.plot(agg["timestamp"], agg["completion_tokens"],
                color=pal[1], marker="o", linewidth=2,
                label="Completion")
        ax.set_ylabel(t("chart.y_cost"), fontsize=8, color=c["muted"])
        ax.grid(axis="y", alpha=0.15)

        ax2 = ax.twinx()
        ax2.plot(agg["timestamp"], agg["cost_cny"],
                color=pal[2], linestyle="--", linewidth=2,
                marker="s", markersize=4, label=t("chart.y_cost"))
        ax2.set_ylabel(t("chart.y_cost"), color=c["digit_highlight"])
        ax2.tick_params(axis="y", colors=c["digit_highlight"])

        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left",
                  frameon=False, fontsize=7)

        ax.set_title(t("analytics.deep_dive", model=model_name), fontsize=10, color=c["text"])
        for label in ax.get_xticklabels():
            label.set_rotation(0)
            label.set_ha("center")
        self.redraw()


class HeatmapChart(BaseChart):
    def render(self, df: pd.DataFrame, model_name: str) -> None:
        self._clear()
        if df.empty:
            self._render_empty_state(t("analytics.no_data"))
            return
        d = df.copy()
        d["date"] = d["timestamp"].dt.date.astype(str)
        d["hour"] = d["timestamp"].dt.hour
        pivot = d.pivot_table(
            index="hour", columns="date",
            values="cost_cny", aggfunc="sum", fill_value=0,
        )
        if pivot.empty:
            self._render_empty_state(t("analytics.no_data"))
            return
        if pivot.shape[1] > 60:
            pivot = pivot.iloc[:, -60:]

        ax = self.figure.add_subplot(111)
        c = self._colors
        im = ax.imshow(pivot.values, aspect="auto",
                       cmap="viridis", origin="upper")
        cbar = self.figure.colorbar(im, ax=ax, pad=0.02)
        cbar.set_label(t("chart.y_cost"), color=c["text"])
        cbar.ax.tick_params(colors=c["muted"])

        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels(pivot.index)
        ax.set_ylabel(t("chart.y_hour"), fontsize=8, color=c["muted"])

        n = pivot.shape[1]
        step = max(1, n // 8)
        ax.set_xticks(range(0, n, step))
        ax.set_xticklabels([pivot.columns[i] for i in range(0, n, step)],
                          rotation=0, ha="center")

        ax.set_title(t("analytics.heatmap", model=model_name), fontsize=10, color=c["text"])
        self.redraw()
