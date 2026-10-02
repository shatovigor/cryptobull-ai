"""
Toast-уведомления в правом верхнем углу родительского окна.
Плавное появление/исчезновение, автозакрытие, клик для закрытия.
"""
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGraphicsOpacityEffect, QHBoxLayout
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation
from PyQt6.QtGui import QMouseEvent


class Toast(QWidget):
    _active = []

    def __init__(self, parent, message, toast_type="info", duration=3000):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.ToolTip
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._parent_widget = parent
        self._duration = duration

        colors = {
            "info":    ("#1E1E1E", "#448AFF", "ℹ"),
            "success": ("#1E1E1E", "#00E676", "✅"),
            "warning": ("#1E1E1E", "#FFB74D", "⚠"),
            "error":   ("#1E1E1E", "#FF5252", "❌"),
        }
        bg, accent, icon = colors.get(toast_type, colors["info"])

        container = QWidget(self)
        container.setObjectName("toast_container")
        container.setStyleSheet(f"""
            #toast_container {{
                background-color: {bg};
                border-left: 4px solid {accent};
                border-radius: 8px;
            }}
        """)

        inner = QHBoxLayout(container)
        inner.setContentsMargins(15, 12, 15, 12)
        inner.setSpacing(10)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(
            f"color: {accent}; font-size: 16px; "
            f"border: none; background: transparent;"
        )
        inner.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

        text_lbl = QLabel(message)
        text_lbl.setStyleSheet(
            "color: #E0E0E0; font-size: 13px; "
            "border: none; background: transparent;"
        )
        text_lbl.setWordWrap(True)
        text_lbl.setMaximumWidth(360)
        inner.addWidget(text_lbl)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(0.0)

        self.anim_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim_in.setDuration(250)
        self.anim_in.setStartValue(0.0)
        self.anim_in.setEndValue(1.0)

        self.anim_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim_out.setDuration(300)
        self.anim_out.setStartValue(1.0)
        self.anim_out.setEndValue(0.0)
        self.anim_out.finished.connect(self._on_closed)

        Toast._active.append(self)

        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

        self.anim_in.start()
        QTimer.singleShot(duration, self._start_fade_out)

    def _reposition(self):
        if not self._parent_widget:
            return
        try:
            parent_rect = self._parent_widget.geometry()
            y_start = 110
            x = parent_rect.width() - self.width() - 40
            if x < 20:
                x = 20

            y = y_start
            for t in Toast._active:
                t.move(x, y)
                y += t.height() + 10
        except Exception:
            pass

    def _start_fade_out(self):
        try:
            self.anim_out.start()
        except Exception:
            self.close()

    def _on_closed(self):
        if self in Toast._active:
            Toast._active.remove(self)
        for t in Toast._active:
            t._reposition()
        self.close()

    def mousePressEvent(self, event: QMouseEvent):
        self.anim_out.stop()
        self._start_fade_out()
        super().mousePressEvent(event)

    def closeEvent(self, event):
        if self in Toast._active:
            Toast._active.remove(self)
        super().closeEvent(event)


def show_toast(parent, message, toast_type="info", duration=3000):
    try:
        return Toast(parent, message, toast_type, duration)
    except Exception:
        return None