"""QSS-стили приложения (заменяет Streamlit ui_components.py).

Поддерживает 7 цветовых схем с динамическим применением.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication


# ---------------------------------------------------------------------------
# Color scheme definitions
# ---------------------------------------------------------------------------
THEMES: dict[str, dict] = {
    "dracula": {
        "bg": "#282a36",
        "card_bg": "#1e1f2b",
        "text": "#f8f8f2",
        "accent": "#bd93f9",
        "muted": "#a370f2",
        "border": "#44445a",
        "danger": "#ff7675",
        "ok": "#55e8a1",
        "digit_highlight": "#ff79c6",
        "palette": ["#bd93f9", "#ff79c6", "#55e8a1", "#56d6dd", "#b294ee"],
    },
    "solarized_dark": {
        "bg": "#002b36",
        "card_bg": "#001f29",
        "text": "#839496",
        "accent": "#e5c07b",
        "muted": "#627a88",
        "border": "#1d3a47",
        "danger": "#ee6b6b",
        "ok": "#7ebf7e",
        "digit_highlight": "#9ab7cf",
        "palette": ["#e5c07b", "#ee6b6b", "#7ebf7e", "#2ab7ca", "#9ab7cf"],
    },
    "solarized_light": {
        "bg": "#fdf6e3",
        "card_bg": "#f4ecd8",
        "text": "#657b83",
        "accent": "#857d6c",
        "muted": "#95a5a6",
        "border": "#dcd0b7",
        "danger": "#ee6b6b",
        "ok": "#7ebf7e",
        "digit_highlight": "#2ab7ca",
        "palette": ["#857d6c", "#ee6b6b", "#7ebf7e", "#2ab7ca", "#9ab7cf"],
    },
    "nord": {
        "bg": "#2e3440",
        "card_bg": "#3a4158",
        "text": "#d8dee9",
        "accent": "#7aa2f7",
        "muted": "#627280",
        "border": "#414868",
        "danger": "#e883a8",
        "ok": "#a6e3a1",
        "digit_highlight": "#bb9af7",
        "palette": ["#7aa2f7", "#bb9af7", "#a6e3a1", "#9ece6a", "#f0d79e"],
    },
    "monokai": {
        "bg": "#272822",
        "card_bg": "#2c2d24",
        "text": "#f8f8f2",
        "accent": "#f92672",
        "muted": "#6e737e",
        "border": "#3a3b30",
        "danger": "#f92672",
        "ok": "#a6e22e",
        "digit_highlight": "#f4bf75",
        "palette": ["#f92672", "#a6e22e", "#f4bf75", "#56b6c2", "#989bff"],
    },
    "one_dark": {
        "bg": "#282c34",
        "card_bg": "#1e232b",
        "text": "#abb2bf",
        "accent": "#6C5CE7",
        "muted": "#5a6068",
        "border": "#3d4450",
        "danger": "#f92672",
        "ok": "#55e8a1",
        "digit_highlight": "#7aa2f7",
        "palette": ["#6C5CE7", "#00D2FF", "#FF7675", "#55EFC4", "#FDCB6E"],
    },
    "github_dark": {
        "bg": "#121212",
        "card_bg": "#1a1a1a",
        "text": "#e6edf3",
        "accent": "#58a6ff",
        "muted": "#7c8492",
        "border": "#30363d",
        "danger": "#ff7b72",
        "ok": "#3fb950",
        "digit_highlight": "#7ee787",
        "palette": ["#58a6ff", "#7ee787", "#ff7b72", "#d2995f", "#bc8cff"],
    },
    "tokyo_night": {
        "bg": "#1a1b26",
        "card_bg": "#23243a",
        "text": "#c0caf5",
        "accent": "#7aa2f7",
        "muted": "#898da9",
        "border": "#3e4260",
        "danger": "#ff6b8a",
        "ok": "#9ece6a",
        "digit_highlight": "#bb9af7",
        "palette": ["#7aa2f7", "#bb9af7", "#9ece6a", "#f2cc8f", "#f071e8"],
    },
}


def get_colors(theme_name: str) -> dict[str, str | list]:
    """Return the color palette for a given theme name. Falls back to one_dark."""
    return THEMES.get(theme_name, THEMES["one_dark"])


# ---------------------------------------------------------------------------
# QSS generation (parameterized by theme colors)
# ---------------------------------------------------------------------------
def _blend(hex1: str, hex2: str, ratio: float) -> str:
    """Blend two hex colors. ratio=0 → hex1, ratio=1 → hex2."""
    h1 = int(hex1.lstrip("#"), 16)
    h2 = int(hex2.lstrip("#"), 16)
    r = int(h1 >> 16) + int((int(h2 >> 16) - (h1 >> 16)) * ratio)
    g = int((h1 >> 8) & 0xFF) + int(((int(h2 >> 8) & 0xFF) - ((h1 >> 8) & 0xFF)) * ratio)
    b = int(h1 & 0xFF) + int(((h2 & 0xFF) - (h1 & 0xFF)) * ratio)
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def _qss(c: dict[str, str | list]) -> str:
    bg = c["bg"]
    card_bg = c["card_bg"]
    text = c["text"]
    accent = c["accent"]
    muted = c["muted"]
    border = c["border"]
    danger = c["danger"]
    ok = c["ok"]
    digit_highlight = c["digit_highlight"]
    # FIX: Qt QSS does not support 'opacity'. Simulate hover fade by blending accent toward bg.
    accent_hover = _blend(accent, bg, 0.15)

    return f"""
    QMainWindow, QWidget {{
        background-color: {bg};
        color: {text};
        font-family: "Segoe UI", "system-ui", sans-serif;
        font-size: 11px;
    }}
    QGroupBox {{
        border: 1px solid {border};
        border-radius: 6px;
        margin-top: 1.5em;
        padding-top: 10px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 8px;
        left: 12px;
        color: {accent};
    }}
    QTabWidget::pane {{
        border: 1px solid {border};
        border-radius: 6px;
        background-color: {bg};
        top: -1px; /* Скрываем верхнюю рамку панели под вкладками */
    }}
    QTabBar::tab {{
        background-color: {card_bg};
        color: {text};
        padding: 6px 16px;
        border: 1px solid {border};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
        margin-bottom: 0px;
    }}
    QTabBar::tab:!selected {{
        margin-top: 2px; /* Неактивные вкладки чуть ниже */
    }}
    QTabBar::tab:selected {{
        background-color: {accent};
        color: white;
        border-bottom: 2px solid {accent}; /* Перекрываем линию панели */
        padding-bottom: 7px; /* Компенсация толщины линии */
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {border};
    }}
    QToolBar {{
        background-color: {card_bg};
        border: none;
        spacing: 6px;
        padding: 4px;
    }}
    QPushButton {{
        background-color: {card_bg};
        color: {text};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 5px 12px;
        font-weight: 500;
        min-height: 16px;
    }}
    QPushButton:hover {{
        background-color: {accent};
        color: white;
        border-color: {accent};
    }}
    QPushButton:disabled {{
        background-color: {border};
        color: {muted};
    }}

    /* Role buttons (primary / secondary / danger) share a base style; only the fill differs. */
    QPushButton[role] {{
        color: white;
        border: none;
    }}
    QPushButton[role="primary"], QPushButton[role="secondary"] {{
        background-color: {accent};
    }}
    QPushButton[role="danger"] {{
        background-color: {danger};
    }}
    QPushButton[role]:hover {{
        background-color: {accent_hover};
    }}
    QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QDateEdit {{
        background-color: {card_bg};
        color: {text};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 4px 8px;
        selection-background-color: {accent};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus,
    QTextEdit:focus, QPlainTextEdit:focus, QDateEdit:focus {{
        border: 1px solid {accent};
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background-color: {card_bg};
        color: {text};
        border: 1px solid {border};
        selection-background-color: {accent};
        outline: none;
    }}
    QCheckBox {{ color: {text}; spacing: 6px; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px;
        border-radius: 3px;
        border: 1px solid {border};
        background-color: {card_bg};
    }}
    QCheckBox::indicator:checked {{
        background-color: {accent};
        border-color: {accent};
    }}
    QLabel[kpi="label"] {{
        color: {muted};
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    QLabel[kpi="value"] {{
        color: {digit_highlight};
        font-weight: 700;
        font-size: 20px;
    }}
    QLabel[kpi="sub"] {{
        color: {muted};
        font-size: 10px;
    }}
    QFrame[kpi="card"] {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 8px;
    }}
    QLabel[role="section"] {{
        color: {text};
        font-weight: 600;
        font-size: 12px;
        padding: 6px 0 3px 0;
    }}
    QLabel[role="hint"] {{ color: {muted}; font-size: 11px; }}
    QLabel[role="ok"]   {{ color: {ok}; }}
    QLabel[role="err"]  {{ color: {danger}; }}
    QTableWidget, QTableView {{
        background-color: {card_bg};
        alternate-background-color: {border};
        color: {text};
        gridline-color: {border};
        border: 1px solid {border};
        border-radius: 8px;
        selection-background-color: {accent};
    }}
    QHeaderView::section {{
        background-color: {bg};
        color: {digit_highlight};
        padding: 6px;
        border: none;
        border-bottom: 1px solid {border};
        border-right: 1px solid {border};
        font-weight: 600;
    }}
    QScrollBar:vertical {{
        background-color: {bg};
        width: 10px; border: none;
    }}
    QScrollBar::handle:vertical {{
        background-color: {border};
        border-radius: 5px;
        min-height: 18px;
    }}
    QScrollBar::handle:vertical:hover {{ background-color: {accent}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QSplitter::handle {{
        background-color: {border};
        width: 2px;
    }}
    QStatusBar {{ background-color: {card_bg}; color: {muted}; }}
    QMenu {{
        background-color: {card_bg};
        color: {text};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 6px;
    }}
    QMenu::item {{ padding: 5px 20px; border-radius: 4px; }}
    QMenu::item:selected {{ background-color: {accent}; color: white; }}
    QMenu::separator {{ height: 1px; background-color: {border}; margin: 3px 8px; }}

    /* FIX #3a: белый квадрат в углу таблицы + стык скроллбаров */
    QTableCornerButton::section {{
        background-color: {card_bg};
        border: 1px solid {border};
        border-radius: 4px;
    }}
    QAbstractScrollArea::corner {{
        background-color: {card_bg};
    }}
    """


def apply_theme(app: QApplication, theme_name: str = "one_dark") -> None:
    """Apply a named color scheme to the entire application."""
    c = get_colors(theme_name)
    app.setStyleSheet(_qss(c))
