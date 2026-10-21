"""Точка входа. Запуск: python main.py"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app_controller import AppController
from charts_widgets import apply_chart_theme
from config import load_config
from main_window import MainWindow
from theme import apply_theme
from tray_icon import TrayIcon


def _setup_logging() -> None:
    """FIX-A1: логирование в файл — убирает PID-окно при запуске."""
    cfg = load_config()
    log_dir = Path(cfg.logs_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "gui.log"
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        filemode="a",
    )


def _excepthook(exc_type: type, exc_val: BaseException, exc_tb) -> None:
    """FIX-A4: глобальный обработчик исключений — краш GUI не молчит.

    Печатает traceback в stderr (видно в терминале) И пишет в gui.log.
    Использует os._exit(1), а не sys.exit(), потому что SystemExit внутри
    excepthook не гарантирует код возврата.
    """
    import traceback
    import os as _os

    # 1) СНАЧАЛА в stderr — чтобы пользователь УВИДЕЛ ошибку в терминале
    try:
        sys.stderr.write("\n" + "=" * 60 + "\nUNHANDLED EXCEPTION:\n")
        traceback.print_exception(exc_type, exc_val, exc_tb, file=sys.stderr)
        sys.stderr.write("=" * 60 + "\n")
        sys.stderr.flush()
    except Exception:
        pass

    # 2) Затем в файл лога (на случай если stderr недоступен — frozen exe)
    try:
        cfg = load_config()
        log_dir = Path(cfg.logs_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "gui.log"
        with open(log_file, "a", encoding="utf-8") as f:
            tb_text = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
            f.write(f"\n{'='*60}\nCRASH ({exc_type.__name__}):\n{tb_text}{'='*60}\n")
    except Exception:
        pass

    # 3) Останавливаем сервер и потоки
    try:
        from app_controller import AppController
        controller = AppController._instance
        if controller is not None:
            controller.shutdown(stop_server=True)
    except Exception:
        pass

    # 4) Жёсткий exit — единственный надёжный способ из excepthook
    _os._exit(1)


def main() -> None:
    _setup_logging()
    sys.excepthook = _excepthook
    app = QApplication(sys.argv)
    app.setApplicationName("Bonsai 2 27B — Control Panel")
    app.setOrganizationName("Bonsai")
    app.setQuitOnLastWindowClosed(False)  # критично для трея
    app.setFont(QFont("Segoe UI", 10))

    # FIX: тема из settings.json применяется ДО создания окон/графиков
    cfg = load_config()
    apply_theme(app, cfg.theme_name)
    apply_chart_theme(cfg.theme_name, force=True)

    controller = AppController(cfg=cfg)
    controller.start()

    window = MainWindow(controller)
    controller.window = window

    tray = TrayIcon(controller)
    controller.tray = tray
    tray.show()

    if controller.cfg.start_in_performance_mode and controller.tray_available:
        controller.set_performance_mode(True)
    else:
        window.show()

    try:
        exit_code = app.exec()
    except KeyboardInterrupt:
        print("\nCtrl+C — выход из GUI")
        exit_code = 0

    # FIX-A4: сервер НЕ остаётся висеть в фоне после закрытия GUI
    controller.shutdown(stop_server=True)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
