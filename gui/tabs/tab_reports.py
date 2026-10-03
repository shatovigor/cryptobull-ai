"""
Вкладка «Отчёты».

Под-табы:
  - История сделок
  - Статистика
  - Календарь P&L
  - Тепловая карта монет
"""
import csv
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QGridLayout,
    QMessageBox, QFileDialog, QAbstractItemView, QTextEdit,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from ..palette import Palette
from ..widgets import make_button, Card, pnl_color, fmt_money, fmt_pct
import config


class ReportsTab(QWidget):
    def __init__(self, bot, main_window):
        super().__init__()
        self.bot = bot
        self.mw = main_window

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Верхняя панель: кнопки
        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_refresh = make_button("🔄  Обновить", kind='accent')
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

        self.btn_export = make_button("📥  Экспорт CSV", kind='ghost')
        self.btn_export.clicked.connect(self._on_export)
        top.addWidget(self.btn_export)

        top.addStretch()
        layout.addLayout(top)

        # Под-табы
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setDocumentMode(True)

        self.sub_tabs.addTab(self._build_history_tab(), "📋  История")
        self.sub_tabs.addTab(self._build_stats_tab(), "📊  Статистика")
        self.sub_tabs.addTab(self._build_calendar_tab(), "📅  Календарь")
        self.sub_tabs.addTab(self._build_heatmap_tab(), "🌡  Тепловая карта")

        layout.addWidget(self.sub_tabs)

    # ============================================================
    # ИСТОРИЯ
    # ============================================================
    def _build_history_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)

        self.table_history = QTableWidget()
        self.table_history.setColumnCount(8)
        self.table_history.setHorizontalHeaderLabels([
            "Дата", "Монета", "Сторона", "Вход", "Выход",
            "Размер $", "P&L %", "P&L $",
        ])
        self.table_history.verticalHeader().setVisible(False)
        self.table_history.setAlternatingRowColors(True)
        self.table_history.setShowGrid(False)
        self.table_history.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        h = self.table_history.horizontalHeader()
        for i in range(8):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table_history)

        return w

    # ============================================================
    # СТАТИСТИКА
    # ============================================================
    def _build_stats_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)

        self.txt_stats = QTextEdit()
        self.txt_stats.setReadOnly(True)
        self.txt_stats.setStyleSheet(
            f"QTextEdit {{ background: {Palette.BG_PANEL}; "
            f"color: {Palette.TEXT_MAIN}; "
            f"font-family: 'JetBrains Mono', monospace; "
            f"font-size: 13px; "
            f"border: 1px solid {Palette.BORDER}; "
            f"border-radius: 10px; padding: 16px; }}"
        )
        lay.addWidget(self.txt_stats)

        return w

    # ============================================================
    # КАЛЕНДАРЬ
    # ============================================================
    def _build_calendar_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)

        self.calendar_grid = QGridLayout()
        self.calendar_grid.setSpacing(8)

        cal_w = QWidget()
        cal_w.setLayout(self.calendar_grid)
        lay.addWidget(cal_w)
        lay.addStretch()

        return w

    # ============================================================
    # HEATMAP
    # ============================================================
    def _build_heatmap_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)

        self.table_heatmap = QTableWidget()
        self.table_heatmap.setColumnCount(5)
        self.table_heatmap.setHorizontalHeaderLabels([
            "Монета", "Сделок", "Побед", "P&L $", "P&L %",
        ])
        self.table_heatmap.verticalHeader().setVisible(False)
        self.table_heatmap.setAlternatingRowColors(True)
        self.table_heatmap.setShowGrid(False)
        self.table_heatmap.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        h = self.table_heatmap.horizontalHeader()
        for i in range(5):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table_heatmap)

        return w

    # ============================================================
    # ОБНОВЛЕНИЕ
    # ============================================================
    def refresh(self):
        self._refresh_history()
        self._refresh_stats()
        self._refresh_calendar()
        self._refresh_heatmap()

    def _refresh_history(self):
        try:
            history = self.bot.get_history(limit=500)
        except Exception:
            history = []

        self.table_history.setRowCount(len(history))
        for i, t in enumerate(history):
            pnl_pct = t.get('pnl_pct', 0)
            pnl_usd = t.get('pnl_usd', 0)

            if pnl_usd > 0:
                bg = QColor(30, 60, 35)
            elif pnl_usd < 0:
                bg = QColor(60, 30, 35)
            else:
                bg = QColor(35, 38, 45)

            ts = str(t.get('exit_ts', ''))[:19].replace('T', ' ')

            side = t.get('side', '?')
            side_color = Palette.SUCCESS if side == 'LONG' else Palette.DANGER

            values = [
                (ts, Palette.TEXT_DIM, False),
                (t.get('symbol', ''), Palette.TEXT_MAIN, False),
                (side, side_color, True),
                (f"{t.get('entry', 0):.6f}", Palette.TEXT_MAIN, False),
                (f"{t.get('exit', 0):.6f}", Palette.TEXT_MAIN, False),
                (fmt_money(t.get('usd_size', 0)), Palette.TEXT_MAIN, False),
                (fmt_pct(pnl_pct, sign=True), pnl_color(pnl_pct), True),
                (fmt_money(pnl_usd, sign=True), pnl_color(pnl_usd), False),
            ]

            for j, (text, color, bold) in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setBackground(bg)
                item.setForeground(QColor(color))
                if bold:
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                self.table_history.setItem(i, j, item)

    def _refresh_stats(self):
        try:
            s7 = self.bot.get_stats(days=7)
            s30 = self.bot.get_stats(days=30)
            sall = self.bot.get_stats(days=3650)
        except Exception:
            self.txt_stats.setPlainText("Ошибка получения статистики")
            return

        def fmt(s, label):
            if s['total'] == 0:
                return f"── {label} ──\n  Нет сделок\n\n"
            return (
                f"── {label} ──\n"
                f"  Сделок:      {s['total']}\n"
                f"  Winrate:     {s['winrate']:.1f}% "
                f"({s['wins']}/{s['total']})\n"
                f"  P&L:         {s['pnl_pct']:+.2f}%  "
                f"(${s['pnl_usd']:+.2f})\n"
                f"  Средний:     {s['avg']:+.2f}%\n"
                f"  Лучшая:      {s['best']:+.2f}%\n"
                f"  Худшая:      {s['worst']:+.2f}%\n\n"
            )

        text = "════════════ ВСЁ ВРЕМЯ ════════════\n"
        text += fmt(sall, "Всего")
        text += "════════════ 30 ДНЕЙ ════════════\n"
        text += fmt(s30, "Месяц")
        text += "════════════ 7 ДНЕЙ ════════════\n"
        text += fmt(s7, "Неделя")

        # Equity
        try:
            from equity_manager import EquityManager
            em = EquityManager()
            eqs = em.get_stats()
            if eqs.get('start', 0) > 0:
                text += "════════════ EQUITY ════════════\n"
                text += f"  Начало:      ${eqs['start']:.2f}\n"
                text += f"  Сейчас:      ${eqs['current']:.2f}\n"
                text += f"  Рост:        {eqs['total_growth_pct']:+.2f}%\n"
                text += f"  Max DD:      ${eqs['max_dd']:.2f}\n"
        except Exception:
            pass

        self.txt_stats.setPlainText(text)

    def _refresh_calendar(self):
        # Очистить
        while self.calendar_grid.count():
            item = self.calendar_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            from report_manager import ReportManager
            rm = ReportManager()
            cal = rm.get_calendar(getattr(config, 'CALENDAR_DAYS', 30))
        except Exception:
            cal = {}

        if not cal:
            lbl = QLabel("📅  Нет данных за последние 30 дней")
            lbl.setStyleSheet(
                f"color: {Palette.TEXT_DIM}; font-size: 14px; padding: 20px; "
                f"background: transparent;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.calendar_grid.addWidget(lbl, 0, 0, 1, 7)
            return

        headers = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        for i, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"font-weight: 700; padding: 8px; "
                f"background: {Palette.BG_PANEL}; "
                f"color: {Palette.TEXT_DIM}; border-radius: 6px;"
            )
            self.calendar_grid.addWidget(lbl, 0, i)

        sorted_days = sorted(cal.items())
        row = 1
        col = 0

        for day, data in sorted_days:
            pnl = data.get('pnl_usd', 0)
            trades = data.get('trades', 0)

            text = f"{day[-5:]}\n${pnl:+.2f}\n({trades})"
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumHeight(70)

            if pnl > 0:
                lbl.setStyleSheet(
                    f"background: {Palette.SUCCESS_DARK}; color: white; "
                    f"padding: 10px; border-radius: 8px; font-weight: 700;"
                )
            elif pnl < 0:
                lbl.setStyleSheet(
                    f"background: {Palette.DANGER_DARK}; color: white; "
                    f"padding: 10px; border-radius: 8px; font-weight: 700;"
                )
            else:
                lbl.setStyleSheet(
                    f"background: {Palette.BG_PANEL}; "
                    f"color: {Palette.TEXT_DIM}; "
                    f"padding: 10px; border-radius: 8px;"
                )

            self.calendar_grid.addWidget(lbl, row, col)
            col += 1
            if col > 6:
                col = 0
                row += 1

    def _refresh_heatmap(self):
        try:
            from report_manager import ReportManager
            rm = ReportManager()
            hm = rm.get_heatmap()
        except Exception:
            hm = {}

        items = list(hm.items())
        self.table_heatmap.setRowCount(len(items))

        for i, (sym, data) in enumerate(items):
            pnl_usd = data.get('pnl_usd', 0)
            pnl_pct = data.get('pnl_pct', 0)
            trades = data.get('trades', 0)
            wins = data.get('wins', 0)

            if pnl_usd > 0:
                bg = QColor(30, 60, 35)
            elif pnl_usd < 0:
                bg = QColor(60, 30, 35)
            else:
                bg = QColor(35, 38, 45)

            values = [
                (sym, Palette.TEXT_MAIN, False),
                (str(trades), Palette.TEXT_MAIN, False),
                (str(wins), Palette.SUCCESS, False),
                (fmt_money(pnl_usd, sign=True), pnl_color(pnl_usd), True),
                (fmt_pct(pnl_pct, sign=True), pnl_color(pnl_pct), False),
            ]

            for j, (text, color, bold) in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setBackground(bg)
                item.setForeground(QColor(color))
                if bold:
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                self.table_heatmap.setItem(i, j, item)

    # ============================================================
    # ЭКСПОРТ
    # ============================================================
    def _on_export(self):
        try:
            history = self.bot.get_history(limit=10000)
        except Exception:
            history = []

        if not history:
            QMessageBox.information(self, "Экспорт",
                                    "Нет истории для экспорта.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, "Экспорт истории",
            f"history_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "CSV (*.csv)"
        )
        if not filename:
            return

        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f, delimiter=';')
                w.writerow([
                    'Дата', 'Монета', 'Сторона', 'Вход', 'Выход',
                    'Размер $', 'P&L %', 'P&L $'
                ])
                for t in history:
                    w.writerow([
                        str(t.get('exit_ts', ''))[:19],
                        t.get('symbol', ''),
                        t.get('side', ''),
                        t.get('entry', 0),
                        t.get('exit', 0),
                        t.get('usd_size', 0),
                        round(t.get('pnl_pct', 0), 2),
                        round(t.get('pnl_usd', 0), 2),
                    ])
            self.mw.tab_bot.log(f"💾 Экспортировано: {filename}",
                                Palette.SUCCESS)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))