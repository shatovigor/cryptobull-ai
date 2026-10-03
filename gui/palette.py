"""
Единая тема приложения.

Правила:
  - Один акцентный цвет (ACCENT) — фиолетово-синий.
  - Зелёный / Красный — ТОЛЬКО для статусов (P&L, ошибки).
  - Оранжевый — предупреждения.
  - Никаких 8 разных цветов, как раньше.
"""


class Palette:
    # ==== ФОН И ТЕКСТ ====
    BG_MAIN     = "#0F1115"      # основной фон
    BG_PANEL    = "#181B22"      # панели, карточки
    BG_INPUT    = "#232731"      # input, combobox
    BG_HOVER    = "#2A2F3A"
    BG_ACTIVE   = "#1F2330"      # активный таб

    BORDER      = "#2A2F3A"
    BORDER_LITE = "#343A46"

    TEXT_MAIN   = "#E6E8EB"
    TEXT_DIM    = "#8B92A0"
    TEXT_MUTED  = "#5A6070"

    # ==== АКЦЕНТ (один) ====
    ACCENT       = "#7C5CFF"
    ACCENT_HOVER = "#9678FF"
    ACCENT_DARK  = "#5B3FCC"

    # ==== СТАТУСЫ ====
    SUCCESS      = "#2ECC71"
    SUCCESS_DARK = "#25A85C"
    DANGER       = "#FF5566"
    DANGER_DARK  = "#CC3344"
    WARNING      = "#FFB020"
    WARNING_DARK = "#CC8A19"
    INFO         = "#4DA3FF"

    # ==== ШРИФТЫ ====
    FONT_UI   = "'Inter', 'Segoe UI', 'Arial', sans-serif"
    FONT_MONO = "'JetBrains Mono', 'Consolas', 'Courier New', monospace"


def build_stylesheet(theme='dark'):
    """
    Собирает QSS для всего приложения.
    Вызывается ОДИН раз при старте. Не пересобирается при переключении табов.
    """
    p = Palette

    if theme == 'light':
        bg_main, bg_panel, bg_input, bg_hover = "#F5F6F8", "#FFFFFF", "#F0F1F3", "#E8EAED"
        border, text_main, text_dim = "#D8DCE3", "#1A1D24", "#5A6070"
    else:
        bg_main, bg_panel, bg_input, bg_hover = p.BG_MAIN, p.BG_PANEL, p.BG_INPUT, p.BG_HOVER
        border, text_main, text_dim = p.BORDER, p.TEXT_MAIN, p.TEXT_DIM

    return f"""
        /* ==== ОБЩЕЕ ==== */
        QMainWindow, QWidget {{
            background-color: {bg_main};
            color: {text_main};
            font-family: {p.FONT_UI};
            font-size: 13px;
        }}

        QToolTip {{
            background-color: {bg_panel};
            color: {text_main};
            border: 1px solid {border};
            padding: 6px 10px;
            border-radius: 6px;
        }}

        /* ==== КАРТОЧКИ (QFrame с objectName=card) ==== */
        QFrame#card {{
            background-color: {bg_panel};
            border: 1px solid {border};
            border-radius: 12px;
        }}

        QFrame#card_flat {{
            background-color: {bg_panel};
            border: none;
            border-radius: 10px;
        }}

        /* ==== GROUPBOX ==== */
        QGroupBox {{
            background-color: {bg_panel};
            border: 1px solid {border};
            border-radius: 10px;
            margin-top: 14px;
            padding: 16px 12px 12px 12px;
            font-weight: 600;
            color: {text_main};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 8px;
            background-color: {bg_panel};
            color: {p.ACCENT};
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        /* ==== ТАБЫ ==== */
        QTabWidget::pane {{
            border: 1px solid {border};
            background: {bg_panel};
            border-radius: 12px;
            top: -1px;
        }}
        QTabBar::tab {{
            background: transparent;
            color: {text_dim};
            padding: 10px 20px;
            margin-right: 4px;
            border: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            font-weight: 500;
        }}
        QTabBar::tab:selected {{
            background: {bg_panel};
            color: {p.ACCENT};
            border-bottom: 2px solid {p.ACCENT};
        }}
        QTabBar::tab:hover:!selected {{
            color: {text_main};
        }}

        /* ==== INPUT ==== */
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
            background-color: {bg_input};
            color: {text_main};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 7px 10px;
            selection-background-color: {p.ACCENT};
            selection-color: white;
        }}
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QComboBox:focus, QPlainTextEdit:focus {{
            border: 1px solid {p.ACCENT};
        }}
        QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
        QComboBox:disabled {{
            background-color: {bg_main};
            color: {p.TEXT_MUTED};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 22px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {bg_panel};
            color: {text_main};
            border: 1px solid {border};
            border-radius: 6px;
            selection-background-color: {p.ACCENT};
            selection-color: white;
            outline: none;
        }}
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
            width: 16px;
            background: transparent;
            border: none;
        }}

        /* ==== КНОПКИ (базовые) ==== */
        QPushButton {{
            background-color: {bg_input};
            color: {text_main};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 8px 16px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {bg_hover};
            border-color: {p.BORDER_LITE};
        }}
        QPushButton:pressed {{
            background-color: {bg_main};
        }}
        QPushButton:disabled {{
            background-color: {bg_main};
            color: {p.TEXT_MUTED};
            border-color: {border};
        }}

        /* ==== КНОПКА-АКЦЕНТ ==== */
        QPushButton[class="accent"] {{
            background-color: {p.ACCENT};
            color: white;
            border: none;
        }}
        QPushButton[class="accent"]:hover {{
            background-color: {p.ACCENT_HOVER};
        }}
        QPushButton[class="accent"]:pressed {{
            background-color: {p.ACCENT_DARK};
        }}
        QPushButton[class="accent"]:disabled {{
            background-color: {p.ACCENT_DARK};
            color: rgba(255,255,255,0.5);
        }}

        /* ==== КНОПКА-УСПЕХ ==== */
        QPushButton[class="success"] {{
            background-color: {p.SUCCESS_DARK};
            color: white;
            border: none;
        }}
        QPushButton[class="success"]:hover {{
            background-color: {p.SUCCESS};
        }}

        /* ==== КНОПКА-ОПАСНОСТЬ ==== */
        QPushButton[class="danger"] {{
            background-color: {p.DANGER_DARK};
            color: white;
            border: none;
        }}
        QPushButton[class="danger"]:hover {{
            background-color: {p.DANGER};
        }}

        /* ==== КНОПКА-ПРЕДУПРЕЖДЕНИЕ ==== */
        QPushButton[class="warning"] {{
            background-color: {p.WARNING_DARK};
            color: #1A1D24;
            border: none;
        }}
        QPushButton[class="warning"]:hover {{
            background-color: {p.WARNING};
        }}

        /* ==== КНОПКА-ПРИЗРАК (только текст) ==== */
        QPushButton[class="ghost"] {{
            background-color: transparent;
            border: 1px solid {border};
        }}
        QPushButton[class="ghost"]:hover {{
            background-color: {bg_hover};
        }}

        /* ==== ТАБЛИЦЫ ==== */
        QTableWidget, QTableView {{
            background-color: {bg_panel};
            color: {text_main};
            gridline-color: {border};
            border: 1px solid {border};
            border-radius: 10px;
            selection-background-color: {p.ACCENT};
            selection-color: white;
            alternate-background-color: {bg_main};
        }}
        QTableWidget::item, QTableView::item {{
            padding: 6px 8px;
            border: none;
        }}
        QHeaderView::section {{
            background-color: {bg_main};
            color: {text_dim};
            padding: 10px 8px;
            border: none;
            border-bottom: 1px solid {border};
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }}
        QTableCornerButton::section {{
            background-color: {bg_main};
            border: none;
        }}

        /* ==== CHECKBOX ==== */
        QCheckBox {{
            color: {text_main};
            spacing: 8px;
            padding: 3px;
        }}
        QCheckBox::indicator {{
            width: 18px; height: 18px;
            border-radius: 5px;
            border: 2px solid {border};
            background: {bg_input};
        }}
        QCheckBox::indicator:checked {{
            background: {p.ACCENT};
            border: 2px solid {p.ACCENT};
        }}
        QCheckBox::indicator:hover {{
            border: 2px solid {p.ACCENT};
        }}

        /* ==== RADIO ==== */
        QRadioButton {{
            color: {text_main};
            spacing: 8px;
            padding: 3px;
        }}
        QRadioButton::indicator {{
            width: 16px; height: 16px;
            border-radius: 9px;
            border: 2px solid {border};
            background: {bg_input};
        }}
        QRadioButton::indicator:checked {{
            background: {p.ACCENT};
            border: 2px solid {p.ACCENT};
        }}

        /* ==== СКРОЛЛ ==== */
        QScrollBar:vertical {{
            background: {bg_main};
            width: 10px;
            margin: 0;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {p.BG_HOVER};
            min-height: 30px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {p.ACCENT};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}

        QScrollBar:horizontal {{
            background: {bg_main};
            height: 10px;
            margin: 0;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {p.BG_HOVER};
            min-width: 30px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {p.ACCENT};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            height: 0;
        }}

        /* ==== PROGRESSBAR ==== */
        QProgressBar {{
            border: 1px solid {border};
            border-radius: 8px;
            background-color: {bg_main};
            color: {text_main};
            text-align: center;
            height: 24px;
            font-weight: 600;
        }}
        QProgressBar::chunk {{
            background-color: {p.ACCENT};
            border-radius: 7px;
        }}

        /* ==== STATUS BAR ==== */
        QStatusBar {{
            background-color: {bg_panel};
            color: {text_dim};
            border-top: 1px solid {border};
            font-size: 12px;
        }}
        QStatusBar::item {{
            border: none;
        }}

        /* ==== SCROLLAREA ==== */
        QScrollArea {{
            border: none;
            background: transparent;
        }}
        QScrollArea > QWidget > QWidget {{
            background: transparent;
        }}

        /* ==== SPLITTER ==== */
        QSplitter::handle {{
            background: {border};
        }}
        QSplitter::handle:horizontal {{
            width: 2px;
        }}
        QSplitter::handle:vertical {{
            height: 2px;
        }}

        /* ==== LABELS (вспомогательные) ==== */
        QLabel[class="title"] {{
            font-size: 18px;
            font-weight: 700;
            color: {text_main};
        }}
        QLabel[class="subtitle"] {{
            font-size: 13px;
            color: {text_dim};
        }}
        QLabel[class="muted"] {{
            color: {p.TEXT_MUTED};
            font-size: 12px;
        }}
        QLabel[class="success"] {{
            color: {p.SUCCESS};
            font-weight: 600;
        }}
        QLabel[class="danger"] {{
            color: {p.DANGER};
            font-weight: 600;
        }}
        QLabel[class="warning"] {{
            color: {p.WARNING};
            font-weight: 600;
        }}
        QLabel[class="mono"] {{
            font-family: {p.FONT_MONO};
            font-size: 12px;
        }}

        /* ==== TEXT EDIT (логи) ==== */
        QTextEdit[class="log"] {{
            background-color: {bg_main};
            color: {text_main};
            font-family: {p.FONT_MONO};
            font-size: 12px;
            border: 1px solid {border};
            border-radius: 8px;
            padding: 8px;
        }}
    """