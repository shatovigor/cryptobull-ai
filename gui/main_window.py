"""
Главное окно приложения.

Содержит:
  - Верхнюю панель с кнопками управления (СТАРТ/СТОП/СИНХР/ОТКРЫТЬ/ОТЧЁТ/ЗАКРЫТЬ ВСЁ)
  - Карточки метрик: Баланс, Equity, Нереализ., Позиции, P&L за день
  - QTabWidget со вкладками
  - Статусбар

Логика:
  - Все тяжёлые операции (синхронизация, сканирование, бэктест) идут через
    workers.py — GUI не подвисает.
  - Синхронизация автоматически запускается каждые N секунд (из config).
"""
import os
import sys
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QStatusBar, QMessageBox, QApplication, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QIcon, QDesktopServices

from .palette import Palette, build_stylesheet
from .widgets import (
    make_button, vline, StatCard, Card,
    fmt_money, fmt_pct, pnl_color,
)
from .workers import SyncWorker, ManualOpenWorker
from .tabs import (
    BotTab, StrategyTab, BacktestTab,
    ScannerTab, ApiTab, ReportsTab,
)

import config

APP_NAME = "CryptoBullAI"
BYBIT_URL = "https://www.bybit.com/trade/usdt/"


class MainWindow(QMainWindow):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 920)

        if os.path.exists('icon.png'):
            self.setWindowIcon(QIcon('icon.png'))

        # Ссылки на воркеры (чтобы не съел GC)
        self._sync_worker = None
        self._manual_open_worker = None

        # Подключаем колбэки бота к нашему GUI
        self.bot.on_log = self._on_bot_log
        self.bot.on_signal = self._on_bot_signal
        self.bot.on_balance = self._on_bot_balance
        self.bot.on_positions = self._on_bot_positions
        self.bot.on_status = self._on_bot_status

        # Главный таймер цикла бота
        self._bot_timer = QTimer()
        self._bot_timer.timeout.connect(self._run_bot_cycle)

        # Таймер часов
        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._tick_clock)

        # Таймер синхронизации с биржей (фоновый)
        self._sync_timer = QTimer()
        self._sync_timer.timeout.connect(self.sync_positions)

        self._cycle_count = 0
        self._build_ui()

        self._clock_timer.start(1000)

        # Стартовая синхронизация
        QTimer.singleShot(800, self.sync_positions)

    # ============================================================
    # ПОСТРОЕНИЕ UI
    # ============================================================
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 8)
        layout.setSpacing(12)

        # ==== ВЕРХНЯЯ ПАНЕЛЬ УПРАВЛЕНИЯ ====
        layout.addWidget(self._build_top_bar())

        # ==== КАРТОЧКИ МЕТРИК ====
        layout.addWidget(self._build_stats_row())

        # ==== ВКЛАДКИ ====
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.tab_bot = BotTab(self.bot, self)
        self.tab_strategy = StrategyTab(self.bot, self)
        self.tab_backtest = BacktestTab(self.bot, self)
        self.tab_scanner = ScannerTab(self.bot, self)
        self.tab_api = ApiTab(self.bot, self)
        self.tab_reports = ReportsTab(self.bot, self)

        self.tabs.addTab(self.tab_bot, "🤖  Автобот")
        self.tabs.addTab(self.tab_strategy, "🎯  Стратегия")
        self.tabs.addTab(self.tab_backtest, "📊  Бэктест")
        self.tabs.addTab(self.tab_scanner, "🔍  Сканер монет")
        self.tabs.addTab(self.tab_reports, "📈  Отчёты")
        self.tabs.addTab(self.tab_api, "🔑  API")

        layout.addWidget(self.tabs, 1)

        # ==== СТАТУСБАР ====
        self._build_statusbar()

        # Применяем тему — ОДИН РАЗ, при старте
        self.setStyleSheet(build_stylesheet('dark'))

    # ------------------------------------------------------------
    # Верхняя панель
    # ------------------------------------------------------------
    def _build_top_bar(self):
        bar = Card(padding=12)
        lay = QHBoxLayout()
        lay.setSpacing(8)

        self.btn_start = make_button("▶  СТАРТ", kind='success',
                                     tooltip="Запустить автобот")
        self.btn_start.clicked.connect(self.on_start)
        self.btn_start.setMinimumWidth(110)

        self.btn_stop = make_button("■  СТОП", kind='danger',
                                    tooltip="Остановить автобот")
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_stop.setMinimumWidth(110)
        self.btn_stop.setEnabled(False)

        self.btn_sync = make_button("🔄  СИНХР", kind='ghost',
                                    tooltip="Синхронизировать позиции с Bybit (F5)")
        self.btn_sync.clicked.connect(self.sync_positions)

        self.btn_open = make_button("➕  ОТКРЫТЬ", kind='accent',
                                    tooltip="Вручную открыть позицию")
        self.btn_open.clicked.connect(self.on_manual_open)

        self.btn_report = make_button("📊  ОТЧЁТ", kind='ghost',
                                      tooltip="Показать дневной отчёт")
        self.btn_report.clicked.connect(self.on_show_report)

        self.btn_close_all = make_button("✕  ЗАКРЫТЬ ВСЁ", kind='danger',
                                         tooltip="Закрыть все открытые позиции")
        self.btn_close_all.clicked.connect(self.on_close_all)

        self.btn_bybit = make_button("🌐  BYBIT", kind='ghost',
                                     tooltip="Открыть Bybit в браузере")
        self.btn_bybit.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(BYBIT_URL))
        )

        # Индикатор статуса бота
        self.lbl_status = QLabel("⏸  Остановлен")
        self.lbl_status.setStyleSheet(
            f"font-size: 14px; font-weight: 700; "
            f"color: {Palette.TEXT_DIM}; "
            f"background: transparent; padding: 6px 14px; "
            f"border: 1px solid {Palette.BORDER}; border-radius: 8px;"
        )

        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_stop)
        lay.addWidget(vline())
        lay.addWidget(self.btn_sync)
        lay.addWidget(self.btn_open)
        lay.addWidget(self.btn_report)
        lay.addWidget(vline())
        lay.addWidget(self.btn_close_all)
        lay.addWidget(self.btn_bybit)
        lay.addStretch()
        lay.addWidget(self.lbl_status)

        bar.layout().addLayout(lay)
        return bar

    # ------------------------------------------------------------
    # Карточки метрик
    # ------------------------------------------------------------
    def _build_stats_row(self):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.card_balance = StatCard("Баланс", "—", "USDT", color=Palette.SUCCESS)
        self.card_equity = StatCard("Equity", "—", "всего", color=Palette.ACCENT)
        self.card_unreal = StatCard("Нереализ.", "—", "по позициям")
        self.card_positions = StatCard("Позиции", "0 / 0", "открыто")
        self.card_trades = StatCard("Сделок сегодня", "0 / 0", "лимит")
        self.card_daily = StatCard("P&L за день", "+0.00%", "0 сделок",
                                   color=Palette.SUCCESS)

        for c in (self.card_balance, self.card_equity, self.card_unreal,
                  self.card_positions, self.card_trades, self.card_daily):
            lay.addWidget(c, 1)

        return row

    # ------------------------------------------------------------
    # Статусбар
    # ------------------------------------------------------------
    def _build_statusbar(self):
        bar = QStatusBar()
        self.setStatusBar(bar)
        bar.setSizeGripEnabled(False)

        self.status_msg = QLabel("Готово")
        self.status_msg.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; padding: 0 12px;"
        )
        bar.addWidget(self.status_msg)

        self.status_mode = QLabel("Режим: ?")
        self.status_mode.setStyleSheet(
            f"color: {Palette.ACCENT}; padding: 0 12px;"
        )
        bar.addPermanentWidget(self.status_mode)

        self.status_time = QLabel(datetime.now().strftime("%H:%M:%S"))
        self.status_time.setStyleSheet(
            f"color: {Palette.TEXT_MUTED}; padding: 0 12px; "
            f"font-family: 'JetBrains Mono', monospace;"
        )
        bar.addPermanentWidget(self.status_time)

    # ============================================================
    # СТАРТ / СТОП БОТА
    # ============================================================
    def on_start(self):
        strategy = getattr(self.bot.strategy, 'display_name', '?')
        msg = (
            f"Запустить автобот?\n\n"
            f"Стратегия:      {strategy}\n"
            f"Монет:          {len(config.AUTO_SYMBOLS)}\n"
            f"Размер:         {config.AUTO_POSITION_PCT}% "
            f"(адаптивный: {config.USE_ADAPTIVE_SIZE})\n"
            f"Плечо:          до {config.MAX_AUTO_LEVERAGE}x\n"
            f"Макс. позиций:  {config.MAX_POSITIONS_TOTAL}\n"
            f"Сделок в день:  {config.AUTO_MAX_TRADES_PER_DAY}\n"
            f"Дневной стоп:   {config.AUTO_DAILY_STOP_PCT}%\n"
        )
        reply = QMessageBox.question(
            self, "Запуск автобота", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.bot.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self._set_status_badge("🟢  Работает", Palette.SUCCESS)
        self.status_msg.setText("Автобот запущен")

        self._run_bot_cycle()
        self._bot_timer.start(config.AUTO_CHECK_INTERVAL_SEC * 1000)

        # Автосинхронизация каждые 30 сек
        self._sync_timer.start(30000)

        self.tab_bot.log("🤖 Автобот запущен", Palette.SUCCESS)

    def on_stop(self):
        self._bot_timer.stop()
        self._sync_timer.stop()
        self.bot.stop()

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

        self._set_status_badge("⏸  Остановлен", Palette.TEXT_DIM)
        self.status_msg.setText("Автобот остановлен")

        self.tab_bot.log("⏹ Автобот остановлен", Palette.DANGER)

        # Обновляем данные после остановки
        self.tab_reports.refresh()
        self.sync_positions()

    def _set_status_badge(self, text, color):
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(
            f"font-size: 14px; font-weight: 700; "
            f"color: {color}; "
            f"background: transparent; padding: 6px 14px; "
            f"border: 1px solid {color}; border-radius: 8px;"
        )

    # ============================================================
    # ЦИКЛ БОТА
    # ============================================================
    def _run_bot_cycle(self):
        if not self.bot.is_running:
            return
        try:
            self.bot.check_cycle()
            self._cycle_count += 1

            # Раз в 5 циклов — обновляем историю/статистику в отчётах
            if self._cycle_count % 5 == 0:
                self.tab_reports.refresh()
        except Exception as e:
            self.tab_bot.log(f"❌ Цикл: {str(e)[:120]}", Palette.DANGER)

    # ============================================================
    # СИНХРОНИЗАЦИЯ С БИРЖЕЙ (в фоне)
    # ============================================================
    def sync_positions(self):
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return  # уже идёт

        self.btn_sync.setEnabled(False)

        self._sync_worker = SyncWorker(self.bot)
        self._sync_worker.finished_ok.connect(self._on_sync_ok)
        self._sync_worker.finished_err.connect(self._on_sync_err)
        self._sync_worker.finished.connect(self._on_sync_done)
        self._sync_worker.start()

    def _on_sync_ok(self, data):
        # Баланс
        bal = data.get('balance')
        if bal:
            total = bal.get('total', 0)
            free = bal.get('free', 0)
            self.card_balance.set_value(
                fmt_money(total), color=Palette.SUCCESS,
                hint=f"свободно {fmt_money(free)}"
            )
            self._on_bot_balance(bal)

        # Equity
        eq = data.get('equity')
        if eq:
            eq_val = eq.get('equity', 0)
            self.card_equity.set_value(
                fmt_money(eq_val), color=Palette.ACCENT,
                hint=f"кошелёк {fmt_money(eq.get('wallet_balance', 0))}"
            )
            unreal = eq.get('unrealized_pnl', 0)
            self.card_unreal.set_value(
                fmt_money(unreal, sign=True),
                color=pnl_color(unreal),
                hint="по открытым позициям"
            )

        # Позиции
        positions = data.get('positions', [])
        self.tab_bot.update_positions(positions)
        self._update_positions_card(len(positions))

        # Режим
        try:
            mode = self.bot.trader.position_mode
            self.status_mode.setText(f"Режим: {mode.upper()}")
        except Exception:
            pass

        # Ошибки, но не фатальные
        if data.get('error'):
            self.status_msg.setText(f"⚠ {data['error']}")

    def _on_sync_err(self, err):
        self.status_msg.setText(f"⚠ Синхронизация: {err[:80]}")

    def _on_sync_done(self):
        self.btn_sync.setEnabled(True)
        self._sync_worker = None

    def _update_positions_card(self, count):
        max_pos = getattr(config, 'MAX_POSITIONS_TOTAL', 4)
        color = Palette.WARNING if count >= max_pos else Palette.TEXT_MAIN
        self.card_positions.set_value(
            f"{count} / {max_pos}", color=color, hint="открыто"
        )

    # ============================================================
    # РУЧНОЕ ОТКРЫТИЕ ПОЗИЦИИ
    # ============================================================
    def on_manual_open(self):
        from PyQt6.QtWidgets import QInputDialog

        symbols = list(config.AUTO_SYMBOLS)
        if not symbols:
            QMessageBox.warning(self, "Нет монет",
                                "Список AUTO_SYMBOLS пуст.\n"
                                "Настройте в config.py или через сканер.")
            return

        symbol, ok = QInputDialog.getItem(
            self, "Открыть позицию", "Монета:", symbols, 0, False
        )
        if not ok:
            return

        side, ok = QInputDialog.getItem(
            self, "Открыть позицию", "Сторона:", ["LONG", "SHORT"], 0, False
        )
        if not ok:
            return

        # Размер
        default_size = config.AUTO_MIN_POSITION_USD
        size, ok = QInputDialog.getDouble(
            self, "Размер позиции",
            f"Размер в USDT (мин {config.AUTO_MIN_POSITION_USD}, "
            f"макс {config.AUTO_MAX_POSITION_USD}):",
            default_size,
            config.AUTO_MIN_POSITION_USD,
            config.AUTO_MAX_POSITION_USD,
            2,
        )
        if not ok:
            return

        # Подтверждение
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Открыть {side} {symbol} на ${size:.2f}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.tab_bot.log(f"▶ Ручное открытие: {side} {symbol} (${size:.2f})",
                         Palette.ACCENT)
        self.btn_open.setEnabled(False)

        self._manual_open_worker = ManualOpenWorker(
            self.bot, symbol, side, size_usd=size
        )
        self._manual_open_worker.finished_ok.connect(self._on_manual_open_ok)
        self._manual_open_worker.finished_err.connect(self._on_manual_open_err)
        self._manual_open_worker.finished.connect(self._on_manual_open_done)
        self._manual_open_worker.start()

    def _on_manual_open_ok(self, msg, pos):
        self.tab_bot.log(f"✅ {msg}", Palette.SUCCESS)
        self.status_msg.setText(f"Открыта: {msg[:80]}")
        QTimer.singleShot(500, self.sync_positions)

    def _on_manual_open_err(self, err):
        self.tab_bot.log(f"❌ {err}", Palette.DANGER)
        QMessageBox.warning(self, "Ошибка открытия", err)

    def _on_manual_open_done(self):
        self.btn_open.setEnabled(True)
        self._manual_open_worker = None

    # ============================================================
    # ЗАКРЫТИЕ ВСЕХ ПОЗИЦИЙ
    # ============================================================
    def on_close_all(self):
        positions = self.bot.trader.state.get('open_positions', {})
        if not positions:
            QMessageBox.information(self, "Закрыть всё",
                                    "Нет открытых позиций.")
            return

        count = len(positions)
        symbols = "\n".join(f"  • {s}" for s in list(positions.keys())[:10])
        if count > 10:
            symbols += f"\n  ... и ещё {count - 10}"

        reply = QMessageBox.question(
            self, "Закрыть всё",
            f"Закрыть {count} позиций?\n\n{symbols}\n\n"
            f"Это действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            results = self.bot.trader.close_all()
            for r in results:
                self.tab_bot.log(f"  {r}", Palette.WARNING)
            self.tab_bot.log(f"✅ Закрыто позиций: {len(results)}",
                             Palette.SUCCESS)
            QTimer.singleShot(500, self.sync_positions)
            self.tab_reports.refresh()
        except Exception as e:
            self.tab_bot.log(f"❌ {str(e)[:120]}", Palette.DANGER)
            QMessageBox.critical(self, "Ошибка", str(e))

    # ============================================================
    # ОТЧЁТ
    # ============================================================
    def on_show_report(self):
        try:
            from report_manager import ReportManager
            rm = ReportManager()
            report = rm.get_daily_report()
            text = rm.format_report_text(report)
        except Exception as e:
            text = f"Ошибка получения отчёта: {e}"

        QMessageBox.information(self, "Дневной отчёт", text)

    # ============================================================
    # КОЛБЭКИ ОТ БОТА
    # ============================================================
    def _on_bot_log(self, msg, color=None):
        self.tab_bot.log(msg, color)

    def _on_bot_signal(self, symbol, side, level):
        self._set_status_badge(f"⚡ {side} {symbol}", Palette.ACCENT)
        QTimer.singleShot(2500, lambda: self._set_status_badge(
            "🟢  Работает" if self.bot.is_running else "⏸  Остановлен",
            Palette.SUCCESS if self.bot.is_running else Palette.TEXT_DIM
        ))

    def _on_bot_balance(self, bal):
        pass  # уже обновляем через SyncWorker

    def _on_bot_positions(self, positions):
        self.tab_bot.update_positions(positions)
        self._update_positions_card(len(positions))

    def _on_bot_status(self, status):
        trades = status.get('trades_today', 0)
        max_trades = getattr(config, 'AUTO_MAX_TRADES_PER_DAY', 15)
        pnl = status.get('pnl_today', 0)

        self.card_trades.set_value(
            f"{trades} / {max_trades}",
            color=Palette.WARNING if trades >= max_trades else Palette.TEXT_MAIN,
            hint="за сегодня",
        )
        self.card_daily.set_value(
            fmt_pct(pnl, sign=True),
            color=pnl_color(pnl),
            hint=f"{trades} сделок",
        )

    # ============================================================
    # ЧАСЫ
    # ============================================================
    def _tick_clock(self):
        self.status_time.setText(datetime.now().strftime("%H:%M:%S"))

    # ============================================================
    # СОБЫТИЯ
    # ============================================================
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F5:
            self.sync_positions()
        elif (event.key() == Qt.Key.Key_S
              and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.sync_positions()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.bot.is_running:
            reply = QMessageBox.question(
                self, "Выход",
                "Автобот работает. Остановить и выйти?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.on_stop()

        # Дождёмся завершения воркеров
        for w in (self._sync_worker, self._manual_open_worker):
            if w is not None and w.isRunning():
                w.quit()
                w.wait(2000)

        event.accept()