"""
Переиспользуемые UI-компоненты.
Всё, что раньше было скопировано 5 раз в gui_auto.py, теперь здесь.
"""
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox,
    QSizePolicy, QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QColor

from .palette import Palette


# ============================================================
# КНОПКИ
# ============================================================
def make_button(text, kind='default', tooltip=None):
    """
    Фабрика кнопок. kind: 'default' | 'accent' | 'success' | 'danger' | 'warning' | 'ghost'
    """
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    if kind != 'default':
        btn.setProperty('class', kind)

    if tooltip:
        btn.setToolTip(tooltip)

    return btn


class LoadingButton(QPushButton):
    """
    Кнопка с состоянием загрузки.
    При start() — текст меняется на "⏳ ...", кнопка дизейблится.
    При stop() — возвращается к обычному состоянию.
    """

    def __init__(self, text, loading_text=None, kind='default', parent=None):
        super().__init__(text, parent)
        self._original_text = text
        self._loading_text = loading_text or f"⏳ {text}"
        self._is_loading = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if kind != 'default':
            self.setProperty('class', kind)

    def start(self):
        if self._is_loading:
            return
        self._is_loading = True
        self.setText(self._loading_text)
        self.setEnabled(False)

    def stop(self):
        if not self._is_loading:
            return
        self._is_loading = False
        self.setText(self._original_text)
        self.setEnabled(True)


# ============================================================
# ЗАГОЛОВКИ И РАЗДЕЛИТЕЛИ
# ============================================================
class SectionTitle(QLabel):
    """Заголовок раздела с опциональным подзаголовком."""

    def __init__(self, title, subtitle=None, parent=None):
        super().__init__(parent)
        if subtitle:
            self.setText(f'<span style="font-size:15px;font-weight:700;">{title}</span>'
                         f'<br><span style="font-size:12px;color:{Palette.TEXT_DIM};">{subtitle}</span>')
            self.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.setText(title)
            self.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {Palette.TEXT_MAIN};")


def vline():
    """Вертикальный разделитель для верхних панелей."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setStyleSheet(f"color: {Palette.BORDER}; background: {Palette.BORDER};")
    sep.setFixedWidth(1)
    sep.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    return sep


def hline():
    """Горизонтальный разделитель."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color: {Palette.BORDER}; background: {Palette.BORDER};")
    sep.setFixedHeight(1)
    return sep


# ============================================================
# КАРТОЧКА
# ============================================================
class Card(QFrame):
    """
    Панель с рамкой и скруглением.
    Использование: card = Card(); card.layout().addWidget(...)
    """

    def __init__(self, padding=16, parent=None):
        super().__init__(parent)
        self.setObjectName('card')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(padding, padding, padding, padding)
        lay.setSpacing(10)


# ============================================================
# СТАТ-КАРТОЧКА (для верха главного экрана)
# ============================================================
class StatCard(Card):
    """
    Карточка с одной метрикой: заголовок, значение, подпись.
    Пример: StatCard("Баланс", "$540.12", "USDT", color=Palette.SUCCESS)
    """

    def __init__(self, title, value, hint="", color=None, parent=None):
        super().__init__(padding=14, parent=parent)
        color = color or Palette.TEXT_MAIN

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.5px; background: transparent;"
        )
        self.layout().addWidget(title_lbl)

        self.value_lbl = QLabel(value)
        self.value_lbl.setStyleSheet(
            f"color: {color}; font-size: 22px; font-weight: 700; background: transparent;"
        )
        self.layout().addWidget(self.value_lbl)

        self.hint_lbl = QLabel(hint)
        self.hint_lbl.setStyleSheet(
            f"color: {Palette.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        self.layout().addWidget(self.hint_lbl)

    def set_value(self, value, color=None, hint=None):
        self.value_lbl.setText(str(value))
        if color:
            self.value_lbl.setStyleSheet(
                f"color: {color}; font-size: 22px; font-weight: 700; background: transparent;"
            )
        if hint is not None:
            self.hint_lbl.setText(str(hint))


# ============================================================
# HINT-ROW: поле + подсказка "сейчас/стандарт"
# ============================================================
class HintRow(QWidget):
    """
    Обёртка над QSpinBox / QDoubleSpinBox / QLineEdit:
    [ поле ]  сейчас: X   стандарт: Y

    Если текущее значение != стандартному — подсвечивается оранжевым.
    """

    def __init__(self, widget, current_value, default_value, suffix="", parent=None):
        super().__init__(parent)
        self._widget = widget
        self._suffix = suffix
        self._default = default_value

        widget.setMinimumWidth(120)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget)

        self._hint = QLabel()
        layout.addWidget(self._hint)
        layout.addStretch()

        self.refresh(current_value, default_value)

    @staticmethod
    def _fmt(v):
        if isinstance(v, bool):
            return "ON" if v else "OFF"
        if isinstance(v, float):
            return f"{v:g}"
        return str(v)

    def refresh(self, current_value, default_value=None):
        if default_value is not None:
            self._default = default_value

        cur_str = f"{self._fmt(current_value)}{self._suffix}"
        def_str = f"{self._fmt(self._default)}{self._suffix}"
        is_changed = (cur_str != def_str)

        color = Palette.WARNING if is_changed else Palette.TEXT_MUTED
        weight = "600" if is_changed else "400"

        self._hint.setText(
            f'  сейчас: {cur_str}   <span style="color:{Palette.TEXT_MUTED};">'
            f'стандарт: {def_str}</span>'
        )
        self._hint.setTextFormat(Qt.TextFormat.RichText)
        self._hint.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: {weight}; "
            f"background: transparent; border: none; padding-left: 8px;"
        )


# ============================================================
# СТРОКА С ТЕГОМ "используется в стратегиях"
# ============================================================
def strategy_tag(strategies):
    """
    Возвращает QLabel-тег для отображения, в каких стратегиях используется поле.
    strategies: list[str] — например ['classic_levels', 'trendrider']
    """
    lbl = QLabel(f"только: {', '.join(strategies)}")
    lbl.setStyleSheet(
        f"color: {Palette.WARNING}; font-size: 10px; "
        f"background: rgba(255,176,32,0.1); "
        f"border: 1px solid rgba(255,176,32,0.3); "
        f"border-radius: 4px; padding: 2px 6px;"
    )
    return lbl


# ============================================================
# АНИМАЦИЯ ПРОЯВЛЕНИЯ
# ============================================================
def fade_in(widget, duration=200):
    """Плавное появление виджета."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    effect.setOpacity(0.0)

    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start()
    widget._fade_anim = anim  # держим ссылку, чтобы не съел GC
    return anim


def flash_border(widget, color=None, duration_ms=800):
    """
    Подсвечивает рамку виджета — для акцента на важных событиях.
    """
    color = color or Palette.ACCENT
    original = widget.styleSheet()
    widget.setStyleSheet(original + f" border: 1px solid {color};")

    def restore():
        widget.setStyleSheet(original)

    QTimer.singleShot(duration_ms, restore)


# ============================================================
# ХЕЛПЕР: цвет для числа (+/-)
# ============================================================
def pnl_color(value):
    """Возвращает цвет для числа: зелёный/красный/серый."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return Palette.TEXT_MAIN
    if v > 0:
        return Palette.SUCCESS
    if v < 0:
        return Palette.DANGER
    return Palette.TEXT_DIM


# ============================================================
# ФОРМАТИРОВАНИЕ
# ============================================================
def fmt_money(v, sign=False, decimals=2):
    """$1,234.56 или +$1,234.56."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    prefix = "+" if sign and v > 0 else ""
    return f"{prefix}${v:,.{decimals}f}"


def fmt_pct(v, sign=True, decimals=2):
    """+1.23% / -1.23%."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    prefix = "+" if sign and v > 0 else ""
    return f"{prefix}{v:.{decimals}f}%"