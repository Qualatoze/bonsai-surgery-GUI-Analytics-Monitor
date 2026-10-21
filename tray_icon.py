"""Иконка в системном трее + контекстное меню для Performance Mode."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMenu, QMessageBox, QSystemTrayIcon,
)


def make_icon(color: str = "#6C5CE7", size: int = 64) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, size - 8, size - 8)
    p.setBrush(QBrush(QColor("#00D2FF")))
    p.drawEllipse(size // 3, size // 3, size // 3, size // 3)
    p.end()
    return QIcon(pix)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setIcon(make_icon())
        self.setToolTip("Bonsai 2 27B — Control Panel")

        menu = QMenu()

        self.action_open = QAction("Открыть Control Panel", menu)
        self.action_open.triggered.connect(self._open_gui)
        menu.addAction(self.action_open)

        self.action_perf = QAction("⚡ Performance Mode", menu)
        self.action_perf.setCheckable(True)
        self.action_perf.toggled.connect(self._toggle_perf)
        menu.addAction(self.action_perf)

        menu.addSeparator()

        self.action_status = QAction("Сервер: —", menu)
        self.action_status.setEnabled(False)
        menu.addAction(self.action_status)

        menu.addSeparator()

        self.action_quit = QAction("Выход", menu)
        self.action_quit.triggered.connect(self._quit)
        menu.addAction(self.action_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self._refresh_status()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._open_gui()

    def _open_gui(self):
        if self.controller.performance_mode:
            self.controller.set_performance_mode(False)
        if self.controller.window:
            self.controller.window.show_window()

    def _toggle_perf(self, checked: bool):
        self.controller.set_performance_mode(checked)

    def _refresh_status(self):
        info = self.controller.mgr.current()
        if info:
            self.action_status.setText(f"Сервер: PID {info.pid} · работает")
            self.setToolTip(f"Bonsai · PID {info.pid}")
        else:
            self.action_status.setText("Сервер: остановлен")
            self.setToolTip("Bonsai · сервер остановлен")

    def notify(self, title: str, message: str, msec: int = 3000):
        if not self.controller.cfg.show_tray_notifications:
            return
        self.showMessage(title, message, QSystemTrayIcon.Information, msec)

    def _quit(self):
        info = self.controller.mgr.current()
        stop = False
        if info:
            r = QMessageBox.question(
                self.controller.window, "Выход",
                f"Сервер работает (PID {info.pid}).\n"
                "Остановить его перед выходом?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if r == QMessageBox.Cancel:
                return
            stop = (r == QMessageBox.Yes)
        self.controller.shutdown(stop_server=stop)
        QApplication.instance().quit()
