"""Dark theme tokens and the application stylesheet."""

BG = "#151517"
PANEL = "#1c1c1f"
PANEL2 = "#222226"
CARD = "#2a2a2f"
CARD_HOVER = "#33333a"
BORDER = "#34343b"
TEXT = "#ececf0"
MUTED = "#8c8c97"
ACCENT = "#3d8bfd"
ACCENT_HOVER = "#5c9dff"
DANGER = "#ff5a5f"
OK = "#3ddc84"
WARN = "#ffb020"

QSS = f"""
* {{ outline: none; }}
QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px 8px; border-radius: 6px; }}

#sidebar, #inspector {{ background: {PANEL}; }}
#sidebar QWidget, #inspector QWidget {{ background: transparent; }}
#topbar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
#topbar QWidget {{ background: transparent; }}
#statusbar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
#statusbar QWidget {{ background: transparent; }}
#card {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 10px; }}
#card QWidget {{ background: transparent; }}
#cardTitle {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
#muted {{ color: {MUTED}; }}
#h1 {{ font-size: 15px; font-weight: 700; }}
#crumb {{ color: {MUTED}; background: transparent; border: none; padding: 3px 6px; border-radius: 5px; }}
#crumb:hover {{ color: {TEXT}; background: {CARD}; }}
#crumbLast {{ color: {TEXT}; font-weight: 700; }}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 9px;
    selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: #4a4a54; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: {MUTED}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QComboBox {{ padding-right: 24px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px;
    selection-background-color: {CARD_HOVER}; selection-color: {TEXT}; outline: none;
}}

QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {CARD_HOVER}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {MUTED}; background: {PANEL2}; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#danger {{ color: {DANGER}; }}
QPushButton#flat, QToolButton#flat {{ background: transparent; border: none; border-radius: 7px; padding: 6px; }}
QPushButton#flat:hover, QToolButton#flat:hover {{ background: {CARD}; }}
QPushButton#flat:disabled, QToolButton#flat:disabled {{ background: transparent; }}
QToolButton {{ background: transparent; border: none; border-radius: 7px; padding: 5px; }}
QToolButton:hover {{ background: {CARD}; }}
QToolButton::menu-indicator {{ image: none; }}

QMenu {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 5px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {CARD_HOVER}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a3a42; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4b4b55; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #3a3a42; border-radius: 3px; min-width: 30px; }}

QTreeWidget {{ background: transparent; border: none; }}
QTreeWidget::item {{ padding: 2px 0; border-radius: 7px; margin: 1px 6px; }}
QTreeWidget::item:hover {{ background: {CARD}; }}
QTreeWidget::item:selected {{ background: {CARD_HOVER}; color: {TEXT}; }}
QTreeWidget::branch {{ background: transparent; }}

QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ border-radius: 8px; padding: 4px; }}
QListWidget::item:hover {{ background: {CARD}; }}
QListWidget::item:selected {{ background: {ACCENT}; color: white; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}

QSplitter::handle {{ background: {BORDER}; }}
"""
