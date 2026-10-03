"""
Вкладка «Автобот».

Содержит:
  - Список активных монет
  - Таблицу открытых позиций (с подсветкой P&L, двойной клик = закрыть)
  - Лог событий с фильтром по уровню и поиском
  - Компактные метрики активной стратегии

Никаких блокирующих вызовов — все данные приходят из main_window через
публичные методы: update_positions(), log().
"""
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QTextEdit, QLineEdit, QComboBox,
    QMessageBox, QAbstractItemView, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

from ..palette import Palette
from ..widgets import make_button, Card, pnl_color, fmt_money, fmt_pct
import config


class BotTab(QWidget):
    def __init__(self, bot, main_window):
        super().__init__()
        self.bot = bot
        self.mw = main_window

        # Кэш строк лога — для фильтрации
        self._log_lines = []   # [(msg, color, level)]
        self._log_filter_level = 'ALL'
        self._log_filter_text = ''

        self._build_ui()
        self._refresh_coins()

    # ============================================================
    # UI
    # ============================================================
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # ==== СТРОКА 1: активные монеты ====
        self.coins_card = Card(padding=12)
        coins_lay = QVBoxLayout()
        coins_lay.setSpacing(6)

        coins_header = QHBoxLayout()
        lbl_coins = QLabel("Активные монеты")
        lbl_coins.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.5px; "
            f"background: transparent;"
        )
        coins_header.addWidget(lbl_coins)
        coins_header.addStretch()

        self.btn_refresh_coins = make_button("🔄  Обновить", kind='ghost')
        self.btn_refresh_coins.clicked.connect(self._refresh_coins)
        coins_header.addWidget(self.btn_refresh_coins)

        coins_lay.addLayout(coins_header)

        self.coins_label = QLabel("—")
        self.coins_label.setWordWrap(True)
        self.coins_label.setStyleSheet(
            f"color: {Palette.ACCENT}; font-family: 'JetBrains Mono', monospace; "
            f"font-size: 12px; background: transparent; padding: 4px 0;"
        )
        coins_lay.addWidget(self.coins_label)

        self.coins_card.layout().addLayout(coins_lay)
        layout.addWidget(self.coins_card)

        # ==== СТРОКА 2: таблица позиций ====
        pos_card = Card(padding=12)
        pos_lay = QVBoxLayout()
        pos_lay.setSpacing(8)

        pos_header = QHBoxLayout()
        lbl_pos = QLabel("Открытые позиции")
        lbl_pos.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.5px; "
            f"background: transparent;"
        )
        pos_header.addWidget(lbl_pos)
        pos_header.addStretch()

        hint_pos = QLabel("двойной клик — закрыть позицию")
        hint_pos.setStyleSheet(
            f"color: {Palette.TEXT_MUTED}; font-size: 11px; "
            f"background: transparent; font-style: italic;"
        )
        pos_header.addWidget(hint_pos)
        pos_lay.addLayout(pos_header)

        self.table_positions = QTableWidget()
        self.table_positions.setColumnCount(10)
        self.table_positions.setHorizontalHeaderLabels([
            "Монета", "Сторона", "Плечо", "Вход", "Текущая",
            "Размер $", "Стоп", "Тейк", "P&L %", "P&L $",
        ])
        self.table_positions.verticalHeader().setVisible(False)
        self.table_positions.setAlternatingRowColors(True)
        self.table_positions.setShowGrid(False)
        self.table_positions.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table_positions.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table_positions.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table_positions.setMinimumHeight(180)
        self.table_positions.doubleClicked.connect(self._on_position_double_click)

        h = self.table_positions.horizontalHeader()
        for i in range(9):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(9, QHeaderView.ResizeMode.Stretch)

        pos_lay.addWidget(self.table_positions)
        pos_card.layout().addLayout(pos_lay)
        layout.addWidget(pos_card, 1)

        # ==== СТРОКА 3: лог ====
        log_card = Card(padding=12)
        log_lay = QVBoxLayout()
        log_lay.setSpacing(8)

        log_header = QHBoxLayout()
        lbl_log = QLabel("Лог событий")
        lbl_log.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.5px; "
            f"background: transparent;"
        )
        log_header.addWidget(lbl_log)
        log_header.addStretch()

        # Фильтр по уровню
        self.combo_log_level = QComboBox()
        self.combo_log_level.addItem("Все", "ALL")
        self.combo_log_level.addItem("ℹ Инфо", "INFO")
        self.combo_log_level.addItem("✅ Успех", "SUCCESS")
        self.combo_log_level.addItem("⚠ Предупр.", "WARNING")
        self.combo_log_level.addItem("❌ Ошибки", "ERROR")
        self.combo_log_level.setFixedWidth(130)
        self.combo_log_level.currentIndexChanged.connect(self._apply_log_filter)
        log_header.addWidget(self.combo_log_level)

        # Поиск
        self.input_log_search = QLineEdit()
        self.input_log_search.setPlaceholderText("Поиск...")
        self.input_log_search.setFixedWidth(180)
        self.input_log_search.textChanged.connect(self._apply_log_filter)
        log_header.addWidget(self.input_log_search)

        # Очистка
        self.btn_clear_log = make_button("🗑  Очистить", kind='ghost')
        self.btn_clear_log.clicked.connect(self._clear_log)
        log_header.addWidget(self.btn_clear_log)

        log_lay.addLayout(log_header)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setProperty('class', 'log')
        self.log_view.setMinimumHeight(160)
        log_lay.addWidget(self.log_view)

        log_card.layout().addLayout(log_lay)
        layout.addWidget(log_card, 1)

    # ============================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ (вызываются из main_window)
    # ============================================================
    def log(self, msg, color=None):
        """Добавляет строку в лог с автоопределением уровня по эмодзи/тексту."""
        level = self._detect_level(msg)
        self._log_lines.append((msg, color, level))

        # Ограничим историю 2000 строк
        if len(self._log_lines) > 2000:
            self._log_lines = self._log_lines[-2000:]

        if self._line_passes_filter(msg, level):
            self._append_html(msg, color)

    def update_positions(self, positions):
        """Перерисовывает таблицу позиций."""
        self.table_positions.setRowCount(len(positions))

        for i, p in enumerate(positions):
            pnl_pct = p.get('pnl_pct', 0)
            lev = p.get('leverage', 1)
            usd_size = p.get('usd_size', 0)
            pnl_usd = usd_size * pnl_pct / 100

            # Подсветка строки по P&L
            if pnl_pct > 0.5:
                row_bg = QColor(30, 60, 35)
            elif pnl_pct < -0.5:
                row_bg = QColor(60, 30, 35)
            else:
                row_bg = QColor(35, 38, 45)

            side = p.get('side', '?')
            side_color = Palette.SUCCESS if side == 'LONG' else Palette.DANGER

            values = [
                (p.get('symbol', '?'), Palette.TEXT_MAIN, False),
                (side, side_color, True),
                (f"{lev:.1f}x", Palette.TEXT_DIM, False),
                (f"{p.get('entry', 0):.6f}", Palette.TEXT_MAIN, False),
                (f"{p.get('current', 0):.6f}", Palette.TEXT_MAIN, False),
                (fmt_money(usd_size), Palette.TEXT_MAIN, False),
                (f"{p.get('stop', 0):.6f}", Palette.DANGER, False),
                (f"{p.get('take', 0):.6f}", Palette.SUCCESS, False),
                (fmt_pct(pnl_pct, sign=True), pnl_color(pnl_pct), True),
                (fmt_money(pnl_usd, sign=True), pnl_color(pnl_usd), False),
            ]

            for j, (text, color, bold) in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setBackground(row_bg)
                item.setForeground(QColor(color))
                if bold:
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                self.table_positions.setItem(i, j, item)

    # ============================================================
    # ПРИВАТНОЕ
    # ============================================================
    def _refresh_coins(self):
        symbols = list(getattr(config, 'AUTO_SYMBOLS', []))
        if not symbols:
            self.coins_label.setText("— список пуст —")
            self.coins_label.setStyleSheet(
                f"color: {Palette.TEXT_MUTED}; font-style: italic; "
                f"background: transparent; padding: 4px 0;"
            )
            return

        self.coins_label.setText("  ".join(symbols))
        self.coins_label.setStyleSheet(
            f"color: {Palette.ACCENT}; "
            f"font-family: 'JetBrains Mono', monospace; "
            f"font-size: 12px; background: transparent; padding: 4px 0;"
        )

    def _detect_level(self, msg):
        """Определяет уровень логирования по тексту."""
        m = msg.lower()
        if '✅' in msg or '🏁' in msg or 'opened' in m or 'закрыта' in m:
            if '❌' not in msg:
                return 'SUCCESS'
        if '❌' in msg or 'ошибка' in m or 'error' in m or 'failed' in m:
            return 'ERROR'
        if '⚠' in msg or 'предупрежд' in m or 'warn' in m:
            return 'WARNING'
        return 'INFO'

    def _line_passes_filter(self, msg, level):
        if self._log_filter_level != 'ALL' and level != self._log_filter_level:
            return False
        if self._log_filter_text and self._log_filter_text.lower() not in msg.lower():
            return False
        return True

    def _apply_log_filter(self):
        self._log_filter_level = self.combo_log_level.currentData() or 'ALL'
        self._log_filter_text = self.input_log_search.text().strip()

        self.log_view.clear()
        for msg, color, level in self._log_lines:
            if self._line_passes_filter(msg, level):
                self._append_html(msg, color)

        # Прокрутка вниз
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append_html(self, msg, color):
        if color is None:
            color = Palette.TEXT_MAIN
        timestamp = datetime.now().strftime("%H:%M:%S")
        html = (
            f'<span style="color: {Palette.TEXT_MUTED};">[{timestamp}]</span> '
            f'<span style="color: {color};">{msg}</span>'
        )
        self.log_view.append(html)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self):
        self._log_lines.clear()
        self.log_view.clear()

    def _on_position_double_click(self, index):
        """Двойной клик по строке → предложить закрыть позицию."""
        row = index.row()
        item = self.table_positions.item(row, 0)
        if not item:
            return
        symbol = item.text()

        reply = QMessageBox.question(
            self, "Закрыть позицию",
            f"Закрыть {symbol}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            ok, msg = self.bot.trader.close_position(symbol, reason="manual")
            if ok:
                self.log(f"✅ {symbol}: {msg}", Palette.SUCCESS)
                QTimer.singleShot(400, self.mw.sync_positions)
            else:
                self.log(f"❌ {symbol}: {msg}", Palette.DANGER)
                QMessageBox.warning(self, "Ошибка", msg)
        except Exception as e:
            self.log(f"❌ {symbol}: {str(e)[:120]}", Palette.DANGER)
            QMessageBox.critical(self, "Ошибка", str(e))