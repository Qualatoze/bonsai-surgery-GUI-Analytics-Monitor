"""Переиспользуемые виджеты + Worker для фоновых задач."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)


class _WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn: Callable, *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(f"{type(e).__name__}: {e}")


_ACTIVE_WORKERS: list[Worker] = []


def run_async(
    fn: Callable,
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> Worker:
    from PySide6.QtCore import QThreadPool
    w = Worker(fn)
    
    # FIX: remove worker from _ACTIVE_WORKERS when it completes (memory leak fix).
    def _cleanup():
        try:
            _ACTIVE_WORKERS.remove(w)
        except ValueError:
            pass
    
    if on_done:
        class _DoneWrapper(QObject):
            @Slot(object)
            def handle(self, result):
                try:
                    on_done(result)
                except Exception as e:
                    import sys
                    sys.stderr.write(f"[run_async] on_done error: {type(e).__name__}: {e}\n")
        
        w._done_wrapper = _DoneWrapper()
        w.signals.finished.connect(w._done_wrapper.handle, Qt.QueuedConnection)
        w.signals.finished.connect(_cleanup, Qt.QueuedConnection)
    if on_error:
        class _ErrorWrapper(QObject):
            @Slot(str)
            def handle(self, msg):
                try:
                    on_error(msg)
                except Exception as e:
                    import sys
                    sys.stderr.write(f"[run_async] on_error error: {type(e).__name__}: {e}\n")
        
        w._error_wrapper = _ErrorWrapper()
        w.signals.error.connect(w._error_wrapper.handle, Qt.QueuedConnection)
        w.signals.error.connect(_cleanup, Qt.QueuedConnection)
    
    QThreadPool.globalInstance().start(w)
    # Keep a strong reference so GC doesn't collect the Worker
    # while it's still executing on the thread pool.
    _ACTIVE_WORKERS.append(w)
    return w


class KpiCard(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setProperty("kpi", "card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)

        self._label = QLabel(label.upper())
        self._label.setProperty("kpi", "label")
        self._value = QLabel("—")
        self._value.setProperty("kpi", "value")
        self._sub = QLabel("")
        self._sub.setProperty("kpi", "sub")

        layout.addWidget(self._label)
        layout.addWidget(self._value)
        layout.addWidget(self._sub)

    def set_value(self, value: str, sub: str = "") -> None:
        self._value.setText(value)
        self._sub.setText(sub)

    def set_label(self, text: str) -> None:
        self._label.setText(text.upper())


class KpiRow(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        self._cards: dict[str, KpiCard] = {}

    def add_card(self, key: str, label: str) -> KpiCard:
        card = KpiCard(label)
        self._cards[key] = card
        self._layout.addWidget(card)
        return card

    def set_value(self, key: str, value: str, sub: str = "") -> None:
        if key in self._cards:
            self._cards[key].set_value(value, sub)

    def set_label(self, key: str, label: str) -> None:
        if key in self._cards:
            self._cards[key].set_label(label)


class SectionTitle(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("role", "section")


class HintLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("role", "hint")
        self.setWordWrap(True)
