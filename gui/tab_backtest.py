"""
Вкладка «Бэктест» — ОБЪЕДИНЁННАЯ.

Включает:
  - Выбор периода, символов и СТРАТЕГИИ
  - Режимы: одиночный / A/B функции / A/B параметров входа
  - Кнопки Запустить / Отмена
  - Прогресс-бар
  - Таблицу результатов по монетам
  - Таблицу сделок с фильтром
  - Сводку итогов с разнесённым P&L (от маржи / от депозита)

ИСПРАВЛЕНИЯ:
  - Добавлен выбор стратегии (combo_bt_strategy)
  - strategy_name передаётся во все воркеры
  - Колонки таблицы результатов: первая ResizeToContents, остальные Stretch
  - Минимальная высота таблиц
  - Сводка показывает стратегию и два вида P&L
  - Для adaptive_ml показывается предупреждение
"""
import csv
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QCheckBox, QSpinBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QRadioButton, QButtonGroup, QMessageBox, QFileDialog,
    QAbstractItemView, QSplitter, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

from ..palette import Palette
from ..widgets import make_button, Card, pnl_color, fmt_money, fmt_pct
from ..workers import BacktestWorker, CompareWorker
import config


class BacktestTab(QWidget):
    def __init__(self, bot, main_window):
        super().__init__()
        self.bot = bot
        self.mw = main_window

        self._worker = None
        self._trades_data = []
        self._last_result = None

        self._build_ui()

    # ============================================================
    # UI
    # ============================================================
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # ==== ВЕРХНЯЯ ПАНЕЛЬ: НАСТРОЙКИ ЗАПУСКА ====
        layout.addWidget(self._build_run_panel())

        # ==== ПРОГРЕСС ====
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("")
        layout.addWidget(self.progress)

        # ==== СТАТУС ====
        self.lbl_status = QLabel("Готов к запуску")
        self.lbl_status.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; padding: 4px 2px; "
            f"background: transparent;"
        )
        layout.addWidget(self.lbl_status)

        # ==== SPLITTER: РЕЗУЛЬТАТЫ + СДЕЛКИ ====
        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- Результаты по монетам ---
        top = Card(padding=12)
        top_lay = QVBoxLayout()
        top_lay.setSpacing(8)

        title1 = QLabel("Результаты по монетам")
        title1.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.5px; "
            f"background: transparent;"
        )
        top_lay.addWidget(title1)

        self.table_results = QTableWidget()
        self.table_results.setColumnCount(7)
        self.table_results.setHorizontalHeaderLabels([
            "Монета", "Сделок", "Winrate", "P&L (марж.)",
            "P&L (деп.)", "PF", "DD %"
        ])
        self.table_results.verticalHeader().setVisible(False)
        self.table_results.setAlternatingRowColors(True)
        self.table_results.setShowGrid(False)
        self.table_results.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table_results.setMinimumHeight(240)
        self.table_results.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        h = self.table_results.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(1, 7):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.table_results.verticalHeader().setDefaultSectionSize(28)

        top_lay.addWidget(self.table_results)

        self.lbl_summary = QLabel("Нажмите «Запустить»")
        self.lbl_summary.setStyleSheet(
            f"color: {Palette.TEXT_MAIN}; "
            f"font-family: 'JetBrains Mono', monospace; "
            f"font-size: 12px; background: {Palette.BG_MAIN}; "
            f"padding: 12px; border-radius: 8px; "
            f"border: 1px solid {Palette.BORDER};"
        )
        self.lbl_summary.setWordWrap(True)
        top_lay.addWidget(self.lbl_summary)

        top.layout().addLayout(top_lay)
        splitter.addWidget(top)

        # --- Список сделок ---
        bottom = Card(padding=12)
        bot_lay = QVBoxLayout()
        bot_lay.setSpacing(8)

        trade_header = QHBoxLayout()
        title2 = QLabel("Сделки бэктеста")
        title2.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.5px; "
            f"background: transparent;"
        )
        trade_header.addWidget(title2)
        trade_header.addStretch()

        trade_header.addWidget(QLabel("Монета:"))
        self.combo_symbol = QComboBox()
        self.combo_symbol.addItem("Все", None)
        self.combo_symbol.currentIndexChanged.connect(self._refresh_trades)
        trade_header.addWidget(self.combo_symbol)

        trade_header.addWidget(QLabel("Результат:"))
        self.combo_result = QComboBox()
        self.combo_result.addItem("Все", None)
        self.combo_result.addItem("Прибыльные", "TAKE")
        self.combo_result.addItem("Убыточные", "STOP")
        self.combo_result.currentIndexChanged.connect(self._refresh_trades)
        trade_header.addWidget(self.combo_result)

        self.btn_export = make_button("📥  CSV", kind='ghost')
        self.btn_export.clicked.connect(self._on_export)
        trade_header.addWidget(self.btn_export)

        self.lbl_count = QLabel("Сделок: 0")
        self.lbl_count.setStyleSheet(
            f"color: {Palette.TEXT_MUTED}; font-size: 11px; "
            f"background: transparent; padding: 0 8px;"
        )
        trade_header.addWidget(self.lbl_count)

        bot_lay.addLayout(trade_header)

        self.table_trades = QTableWidget()
        self.table_trades.setColumnCount(9)
        self.table_trades.setHorizontalHeaderLabels([
            "#", "Дата", "Монета", "Сторона", "Вход", "Выход",
            "P&L %", "P&L $", "Причина"
        ])
        self.table_trades.verticalHeader().setVisible(False)
        self.table_trades.setAlternatingRowColors(True)
        self.table_trades.setShowGrid(False)
        self.table_trades.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table_trades.setMinimumHeight(220)

        h2 = self.table_trades.horizontalHeader()
        for i in range(8):
            h2.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        h2.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)

        bot_lay.addWidget(self.table_trades)

        bottom.layout().addLayout(bot_lay)
        splitter.addWidget(bottom)

        splitter.setSizes([500, 350])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------
    def _build_run_panel(self):
        card = Card(padding=12)
        lay = QVBoxLayout()
        lay.setSpacing(12)

        # ---- Строка 1: режим ----
        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)

        lbl_mode = QLabel("Режим:")
        lbl_mode.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-weight: 600; "
            f"background: transparent;"
        )
        mode_row.addWidget(lbl_mode)

        self.radio_single = QRadioButton("Одиночный прогон")
        self.radio_compare = QRadioButton("A/B функции")
        self.radio_entry = QRadioButton("A/B параметров входа")
        self.radio_single.setChecked(True)

        self.radio_single.toggled.connect(self._on_mode_change)

        mode_row.addWidget(self.radio_single)
        mode_row.addWidget(self.radio_compare)
        mode_row.addWidget(self.radio_entry)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # ---- Строка 2: настройки ----
        settings_row = QHBoxLayout()
        settings_row.setSpacing(12)

        settings_row.addWidget(QLabel("Период:"))
        self.spin_days = QSpinBox()
        self.spin_days.setRange(3, 365)
        self.spin_days.setValue(getattr(config, 'BACKTEST_DEFAULT_DAYS', 14))
        self.spin_days.setSuffix(" дн")
        self.spin_days.setFixedWidth(100)
        settings_row.addWidget(self.spin_days)

        settings_row.addWidget(QLabel("Символы:"))
        self.combo_symbols = QComboBox()
        self.combo_symbols.addItem(
            f"Активные ({len(config.AUTO_SYMBOLS)})", "active"
        )
        self.combo_symbols.addItem("Все из config.py", "config")
        self.combo_symbols.setFixedWidth(170)
        settings_row.addWidget(self.combo_symbols)

        # ---- ВЫБОР СТРАТЕГИИ ----
        settings_row.addWidget(QLabel("Стратегия:"))
        self.combo_bt_strategy = QComboBox()
        self.combo_bt_strategy.addItem("📊 Уровни + паттерны", "classic_levels")
        self.combo_bt_strategy.addItem("🧠 Адаптивная ML", "adaptive_ml")
        self.combo_bt_strategy.addItem("📈 TrendRider", "trendrider")

        current_strat = getattr(config, 'ACTIVE_STRATEGY', 'classic_levels')
        idx = self.combo_bt_strategy.findData(current_strat)
        if idx >= 0:
            self.combo_bt_strategy.setCurrentIndex(idx)

        self.combo_bt_strategy.setFixedWidth(200)
        self.combo_bt_strategy.setStyleSheet(
            "QComboBox { font-weight: 600; }"
        )
        settings_row.addWidget(self.combo_bt_strategy)

        settings_row.addStretch()

        self.btn_run = make_button("▶  Запустить", kind='accent')
        self.btn_run.clicked.connect(self._on_run)
        settings_row.addWidget(self.btn_run)

        self.btn_cancel = make_button("⏹  Отмена", kind='danger')
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_cancel.setEnabled(False)
        settings_row.addWidget(self.btn_cancel)

        lay.addLayout(settings_row)

        # ---- Строка 3: инфо про A/B ----
        self.ab_info = QLabel(
            "A/B режимы запускают серию бэктестов с разными override-параметрами "
            "и показывают таблицу сравнения конфигураций. "
            "A/B функции сравнивает: MTF, Trailing, Адаптив размер, Пирамидинг, Хедж. "
            "A/B входа сравнивает параметры MIN_TOUCHES, NEAR_LEVEL, CLUSTER и типы сигналов."
        )
        self.ab_info.setWordWrap(True)
        self.ab_info.setStyleSheet(
            f"color: {Palette.TEXT_MUTED}; font-size: 11px; "
            f"font-style: italic; background: transparent; "
            f"padding: 0 4px;"
        )
        self.ab_info.setVisible(False)
        lay.addWidget(self.ab_info)

        card.layout().addLayout(lay)
        return card

    # ============================================================
    # СОБЫТИЯ
    # ============================================================
    def _on_mode_change(self):
        is_ab = self.radio_compare.isChecked() or self.radio_entry.isChecked()
        self.ab_info.setVisible(is_ab)

    def _on_run(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.warning(self, "Занято", "Бэктест уже запущен.")
            return

        symbols = self._get_symbols()
        if not symbols:
            QMessageBox.warning(self, "Нет монет", "Список AUTO_SYMBOLS пуст.")
            return

        days = self.spin_days.value()
        strategy_name = self.combo_bt_strategy.currentData()

        # adaptive_ml не поддерживает бэктест
        if strategy_name == 'adaptive_ml':
            QMessageBox.warning(
                self, "Недоступно",
                "🧠 Адаптивная ML не работает в бэктесте — модель "
                "обучается онлайн на закрытых сделках.\n\n"
                "Используйте classic_levels или trendrider."
            )
            return

        # Очистить прошлые данные
        self._trades_data = []
        self._last_result = None
        self.table_results.setRowCount(0)
        self.table_trades.setRowCount(0)
        self.lbl_summary.setText("Расчёт...")
        self.lbl_status.setText(
            f"⏳ Прогон: {len(symbols)} монет × {days} дней × {strategy_name}"
        )

        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setValue(0)
        self.progress.setMaximum(len(symbols))
        self.progress.setFormat("0%")

        if self.radio_single.isChecked():
            self._run_single(symbols, days, strategy_name)
        elif self.radio_compare.isChecked():
            self._run_ab_functions(symbols, days, strategy_name)
        else:
            self._run_ab_entry(symbols, days, strategy_name)

    def _on_cancel(self):
        if self._worker is not None and hasattr(self._worker, 'cancel'):
            self._worker.cancel()
            self.lbl_status.setText("⏹ Отмена...")
            self.btn_cancel.setEnabled(False)

    # ------------------------------------------------------------
    def _get_symbols(self):
        if self.combo_symbols.currentData() == "active":
            return list(config.AUTO_SYMBOLS)
        return list(getattr(config, 'AUTO_SYMBOLS', []))

    # ------------------------------------------------------------
    def _run_single(self, symbols, days, strategy_name):
        self._worker = BacktestWorker(
            symbols, days,
            override_config={'STRATEGY_NAME': strategy_name},
        )
        self._worker.log_message.connect(self._on_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_single_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _run_ab_functions(self, symbols, days, strategy_name):
        configs = self._build_ab_function_configs()
        self._worker = CompareWorker(
            symbols, configs, days,
            strategy_name=strategy_name,
        )
        self._worker.log_message.connect(self._on_log)
        self._worker.finished_ok.connect(self._on_compare_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _run_ab_entry(self, symbols, days, strategy_name):
        try:
            from backtest_compare import build_entry_ab_configs
            configs = build_entry_ab_configs()
        except (ImportError, AttributeError):
            QMessageBox.warning(
                self, "Недоступно",
                "build_entry_ab_configs не найден в backtest_compare.py.\n\n"
                "Использую базовый набор A/B функций."
            )
            configs = self._build_ab_function_configs()

        self._worker = CompareWorker(
            symbols, configs, days,
            strategy_name=strategy_name,
        )
        self._worker.log_message.connect(self._on_log)
        self._worker.finished_ok.connect(self._on_compare_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _build_ab_function_configs(self):
        base_off = {
            'USE_MULTI_TIMEFRAME': False,
            'USE_TRAILING_STOP': False,
            'USE_ADAPTIVE_SIZE': False,
            'USE_PYRAMIDING': False,
            'USE_HEDGING': False,
        }
        return [
            {'name': 'База (все выкл.)', 'config': base_off},
            {'name': '+ MTF', 'config': {**base_off, 'USE_MULTI_TIMEFRAME': True}},
            {'name': '+ Trailing', 'config': {**base_off, 'USE_TRAILING_STOP': True}},
            {'name': '+ Адаптив размер', 'config': {**base_off, 'USE_ADAPTIVE_SIZE': True}},
            {'name': '+ Пирамидинг', 'config': {**base_off, 'USE_PYRAMIDING': True}},
            {'name': '+ Хедж', 'config': {**base_off, 'USE_HEDGING': True}},
            {'name': 'Всё включено', 'config': {
                'USE_MULTI_TIMEFRAME': True,
                'USE_TRAILING_STOP': True,
                'USE_ADAPTIVE_SIZE': True,
                'USE_PYRAMIDING': True,
                'USE_HEDGING': True,
            }},
        ]

    # ============================================================
    # ОБРАБОТКА РЕЗУЛЬТАТОВ
    # ============================================================
    def _on_log(self, msg, color=None):
        self.lbl_status.setText(msg)

    def _on_progress(self, current, total, symbol):
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        pct = int(current / total * 100) if total else 0
        self.progress.setFormat(f"{current}/{total} ({pct}%) — {symbol}")

    def _on_single_ok(self, result):
        self._last_result = result
        rows = result.get('results', []) or []
        summary = result.get('summary')
        days = result.get('period_days', 0)
        strategy = result.get('strategy_name', '?')

        self._trades_data = result.get('trades_list', []) or []

        # Таблица результатов
        self.table_results.setRowCount(len(rows))
        for i, r in enumerate(rows):
            sym = r.get('symbol', '?')

            if r.get('error'):
                self._set_row(self.table_results, i, [
                    (sym, Palette.DANGER, False),
                    ("ERR", Palette.DANGER, True),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                ])
                continue

            if r.get('total', 0) == 0:
                self._set_row(self.table_results, i, [
                    (sym, Palette.TEXT_MAIN, False),
                    ("0", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                ])
                continue

            wr = r.get('winrate', 0)
            wr_color = (Palette.SUCCESS if wr >= 50
                        else Palette.WARNING if wr >= 33
                        else Palette.DANGER)

            pnl = r.get('pnl', 0)
            pnl_usd = r.get('pnl_usd', 0)
            start_bal = r.get('start_balance', 540.0) or 540.0
            pnl_deposit = pnl_usd / start_bal * 100 if start_bal else 0

            self._set_row(self.table_results, i, [
                (sym, Palette.TEXT_MAIN, False),
                (str(r.get('total', 0)), Palette.TEXT_MAIN, False),
                (fmt_pct(wr, sign=False, decimals=1), wr_color, False),
                (fmt_pct(pnl, sign=True), pnl_color(pnl), True),
                (fmt_pct(pnl_deposit, sign=True), pnl_color(pnl_deposit), False),
                (f"{r.get('pf', 0):.2f}", Palette.TEXT_MAIN, False),
                (fmt_pct(r.get('dd', 0), sign=False), Palette.TEXT_DIM, False),
            ])

        # Сводка
        if summary:
            pnl_usd = summary.get('pnl_usd', 0)
            start_bal = summary.get('start_balance', 540.0) or 540.0
            pnl_deposit_pct = pnl_usd / start_bal * 100 if start_bal else 0

            text = (
                f"═══ ИТОГО ═══\n"
                f"Стратегия:       {strategy}\n"
                f"Период:          {days} дней\n"
                f"Монет:           {result.get('symbols_count', 0)}\n"
                f"Сделок:          {summary.get('total', 0)}\n"
                f"Winrate:         {summary.get('winrate', 0):.1f}% "
                f"({summary.get('wins', 0)}/{summary.get('total', 0)})\n"
                f"\n── P&L от маржи (с плечом) ──\n"
                f"P&L:             {summary.get('pnl', 0):+.2f}%\n"
                f"Средний:         {summary.get('pnl_avg_pct', 0):+.2f}% на сделку\n"
                f"\n── P&L от депозита ──\n"
                f"${pnl_usd:+.2f} "
                f"(${start_bal:.2f} → ${summary.get('end_balance', 0):.2f})\n"
                f"P&L % от депозита: {pnl_deposit_pct:+.2f}%\n"
                f"\n── Метрики ──\n"
                f"Profit Factor:   {summary.get('pf', 0):.2f}\n"
                f"Max Drawdown:    {summary.get('dd', 0):.2f}% "
                f"(${summary.get('dd_usd', 0):.2f})\n"
            )
            self.lbl_summary.setText(text)
        else:
            self.lbl_summary.setText("Нет сделок в выбранном периоде.")

        self._refresh_symbol_filter()
        self._refresh_trades()

        errors = [r for r in rows if r.get('error')]
        if errors:
            self.lbl_status.setText(
                f"✅ Готово: {len(self._trades_data)} сделок, "
                f"ошибок: {len(errors)}"
            )
            self.mw.tab_bot.log(
                f"⚠ Ошибки бэктеста: "
                f"{', '.join(r.get('symbol', '?') for r in errors)}",
                Palette.WARNING
            )
        else:
            self.lbl_status.setText(
                f"✅ Готово: {len(self._trades_data)} сделок, стратегия {strategy}"
            )

    def _on_compare_ok(self, results):
        self.table_results.setRowCount(len(results))

        baseline_pnl = None
        for i, r in enumerate(results):
            name = r.get('name', '?')

            if r.get('error') or not r.get('summary'):
                self._set_row(self.table_results, i, [
                    (name, Palette.TEXT_MAIN, True),
                    ("ERR", Palette.DANGER, True),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                    ("—", Palette.TEXT_MUTED, False),
                ])
                continue

            pnl = r.get('pnl', 0)
            if i == 0:
                baseline_pnl = pnl

            wr = r.get('winrate', 0)
            wr_color = (Palette.SUCCESS if wr >= 50
                        else Palette.WARNING if wr >= 33
                        else Palette.DANGER)

            self._set_row(self.table_results, i, [
                (name, Palette.TEXT_MAIN, True),
                (str(r.get('trades_count', 0)), Palette.TEXT_MAIN, False),
                (fmt_pct(wr, sign=False, decimals=1), wr_color, False),
                (fmt_pct(pnl, sign=True), pnl_color(pnl), True),
                ("—", Palette.TEXT_MUTED, False),
                (f"{r.get('pf', 0):.2f}", Palette.TEXT_MAIN, False),
                (fmt_pct(r.get('dd', 0), sign=False), Palette.TEXT_DIM, False),
            ])

        if baseline_pnl is not None and len(results) > 1:
            lines = ["═══ СРАВНЕНИЕ ═══\n"]
            lines.append(f"База: P&L {baseline_pnl:+.2f}%\n")
            lines.append("Влияние на P&L:")
            for r in results[1:]:
                if r.get('error') or not r.get('summary'):
                    continue
                diff = r.get('pnl', 0) - baseline_pnl
                icon = "✅" if diff > 1 else "⚠" if diff > -1 else "❌"
                lines.append(
                    f"  {icon} {r.get('name')}: {diff:+.2f}% "
                    f"({r.get('trades_count', 0)} сд., "
                    f"{r.get('winrate', 0):.1f}% wr)"
                )
            self.lbl_summary.setText("\n".join(lines))

        self.lbl_status.setText(
            f"✅ Сравнение завершено: {len(results)} конфигов"
        )
        self._refresh_trades()

    def _set_row(self, table, row_idx, values):
        for j, (text, color, bold) in enumerate(values):
            item = QTableWidgetItem(str(text))
            item.setForeground(QColor(color))
            if bold:
                f = QFont()
                f.setBold(True)
                item.setFont(f)
            table.setItem(row_idx, j, item)

    def _on_err(self, err):
        self.lbl_status.setText(f"❌ Ошибка: {err[:120]}")
        QMessageBox.critical(self, "Ошибка бэктеста", err)

    def _on_done(self):
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setFormat("")
        self._worker = None

    # ============================================================
    # СДЕЛКИ
    # ============================================================
    def _refresh_symbol_filter(self):
        self.combo_symbol.blockSignals(True)
        self.combo_symbol.clear()
        self.combo_symbol.addItem("Все", None)

        symbols = sorted({t.get('symbol', '') for t in self._trades_data})
        for sym in symbols:
            if sym:
                self.combo_symbol.addItem(sym, sym)
        self.combo_symbol.blockSignals(False)

    def _refresh_trades(self):
        filter_sym = self.combo_symbol.currentData()
        filter_res = self.combo_result.currentData()

        filtered = list(self._trades_data)
        if filter_sym:
            filtered = [t for t in filtered if t.get('symbol') == filter_sym]
        if filter_res:
            filtered = [t for t in filtered if t.get('result') == filter_res]

        self.table_trades.setRowCount(len(filtered))
        for i, t in enumerate(filtered):
            pnl_pct = t.get('pnl', 0)
            pnl_usd = t.get('pnl_usd', 0)

            if pnl_pct > 0:
                bg = QColor(30, 60, 35)
            elif pnl_pct < 0:
                bg = QColor(60, 30, 35)
            else:
                bg = QColor(35, 38, 45)

            ts = ''
            try:
                ts = str(t.get('entry_ts', ''))[:19].replace('T', ' ')
            except Exception:
                pass

            side = t.get('type', '?')
            side_color = Palette.SUCCESS if side == 'LONG' else Palette.DANGER

            values = [
                (str(i + 1), Palette.TEXT_MUTED, False),
                (ts, Palette.TEXT_DIM, False),
                (t.get('symbol', ''), Palette.TEXT_MAIN, False),
                (side, side_color, True),
                (f"{t.get('entry', 0):.6f}", Palette.TEXT_MAIN, False),
                (f"{t.get('exit', 0):.6f}", Palette.TEXT_MAIN, False),
                (fmt_pct(pnl_pct, sign=True), pnl_color(pnl_pct), True),
                (fmt_money(pnl_usd, sign=True), pnl_color(pnl_usd), False),
                (t.get('reason', '?'), Palette.TEXT_DIM, False),
            ]

            for j, (text, color, bold) in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setBackground(bg)
                item.setForeground(QColor(color))
                if bold:
                    f = QFont()
                    f.setBold(True)
                    item.setFont(f)
                self.table_trades.setItem(i, j, item)

        self.lbl_count.setText(
            f"Сделок: {len(filtered)} из {len(self._trades_data)}"
        )

    def _on_export(self):
        if not self._trades_data:
            QMessageBox.information(self, "Экспорт", "Нет данных для экспорта.")
            return

        filename, _ = QFileDialog.getSaveFileName(
            self, "Экспорт сделок",
            f"bt_trades_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "CSV (*.csv)"
        )
        if not filename:
            return

        try:
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f, delimiter=';')
                w.writerow([
                    '#', 'Дата', 'Монета', 'Сторона', 'Вход', 'Выход',
                    'P&L %', 'P&L $', 'Причина', 'Часы',
                    'Плечо', 'Размер $', 'SL %', 'TP %', 'ATR %', 'Signal'
                ])
                for i, t in enumerate(self._trades_data):
                    w.writerow([
                        i + 1,
                        str(t.get('entry_ts', ''))[:19],
                        t.get('symbol', ''),
                        t.get('type', ''),
                        t.get('entry', 0),
                        t.get('exit', 0),
                        round(t.get('pnl', 0), 2),
                        round(t.get('pnl_usd', 0), 2),
                        t.get('reason', ''),
                        round(t.get('duration_h', 0), 2),
                        t.get('leverage', 1),
                        round(t.get('size_usd', 0), 2),
                        round(t.get('stop_pct', 0), 2),
                        round(t.get('take_pct', 0), 2),
                        round(t.get('atr_pct', 0), 2),
                        t.get('signal_type', ''),
                    ])
            self.mw.tab_bot.log(f"💾 Экспортировано: {filename}", Palette.SUCCESS)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))