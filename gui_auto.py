"""
CryptoBullAI — современный GUI для автобота.
Тёмная тема, Toast-уведомления, двойные подсказки (сейчас/стандарт),
гибкие настройки бэктеста, адаптивный стоп по ATR.
"""
import sys
import os
import re
import csv
import json
from datetime import datetime, timezone, timedelta

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QTextEdit, QGroupBox, QHeaderView, QMessageBox,
    QTabWidget, QFileDialog, QComboBox, QLineEdit, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFormLayout, QFrame, QSplitter,
    QGridLayout, QProgressBar, QStatusBar, QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QColor, QIcon, QDesktopServices

from auto_trader import AutoTrader
from strategies.registry import STRATEGIES, list_strategies
import config
from bybit_client import (
    test_api_keys, check_connection, make_exchange,
    get_position_mode, get_equity, get_ticker
)

try:
    from equity_manager import EquityManager
    EQUITY_AVAILABLE = True
except ImportError:
    EQUITY_AVAILABLE = False

try:
    from report_manager import ReportManager
    REPORT_AVAILABLE = True
except ImportError:
    REPORT_AVAILABLE = False

try:
    from chart_widget import PriceChart, EquityChart
    CHART_AVAILABLE = True
except ImportError:
    CHART_AVAILABLE = False

try:
    from backtest_runner import run_backtest
    BACKTEST_AVAILABLE = True
except ImportError:
    BACKTEST_AVAILABLE = False

try:
    from backtest_compare import compare_configurations, compare_functions
    COMPARE_AVAILABLE = True
except ImportError:
    COMPARE_AVAILABLE = False

try:
    from advisor import get_advice, format_advice
    ADVISOR_AVAILABLE = True
except ImportError:
    ADVISOR_AVAILABLE = False

try:
    from analyze_entries import main as analyze_main
    ANALYZE_AVAILABLE = True
except ImportError:
    ANALYZE_AVAILABLE = False

try:
    from toast import Toast, show_toast
    TOAST_AVAILABLE = True
except ImportError:
    TOAST_AVAILABLE = False

APP_NAME = "CryptoBullAI"
BYBIT_URL = "https://www.bybit.com/trade/usdt/"

try:
    from step7_coin_scanner import get_top_symbols
    SCANNER_AVAILABLE = True
except ImportError:
    SCANNER_AVAILABLE = False


# ============================================================
# ПАЛИТРА
# ============================================================
class Palette:
    BG_MAIN    = "#0E0E0E"
    BG_PANEL   = "#1A1A1A"
    BG_INPUT   = "#242424"
    BG_HOVER   = "#2E2E2E"
    BORDER     = "#333333"
    TEXT_MAIN  = "#E8E8E8"
    TEXT_DIM   = "#8A8A8A"

    GREEN      = "#00E676"
    GREEN_DARK = "#00C853"
    RED        = "#FF5252"
    RED_DARK   = "#D50000"
    BLUE       = "#448AFF"
    BLUE_DARK  = "#2962FF"
    PURPLE     = "#7C4DFF"
    PURPLE_DARK= "#6200EA"
    ORANGE     = "#FFB74D"
    ORANGE_DARK= "#E65100"
    TEAL       = "#00ACC1"
    TEAL_DARK  = "#00838F"
    NEUTRAL    = "#455A64"
    NEUTRAL_DK = "#37474F"


# ============================================================
# WORKERS
# ============================================================
class ScannerWorker(QThread):
    log_message = pyqtSignal(str, str)
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str)

    def __init__(self, top_n=10):
        super().__init__()
        self.top_n = top_n

    def run(self):
        try:
            self.log_message.emit("🔄 Сканирую Bybit...", "#448AFF")
            symbols = get_top_symbols(self.top_n)
            if not symbols:
                self.finished_err.emit("Ничего не найдено")
                return
            self.finished_ok.emit(symbols)
        except Exception as e:
            self.finished_err.emit(str(e)[:120])


class BacktestWorker(QThread):
    log_message = pyqtSignal(str, str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, symbols, days, override_config=None):
        super().__init__()
        self.symbols = symbols
        self.days = days
        self.override_config = override_config or {}
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _cancel_check(self):
        return self._cancel

    def run(self):
        try:
            self.log_message.emit(
                f"📊 Бэктест: {len(self.symbols)} монет, {self.days} дней...",
                "#448AFF"
            )
            if self.override_config:
                self.log_message.emit(
                    f"  Override: {self.override_config}",
                    "#8A8A8A"
                )

            def progress(msg):
                self.log_message.emit(f"  {msg}", "#8A8A8A")

            def status(info):
                self.progress.emit(info['current'], info['total'], info['symbol'])

            result = run_backtest(
                self.symbols, self.days,
                progress_callback=progress,
                cancel_check=self._cancel_check,
                status_callback=status,
                override_config=self.override_config,
            )
            self.finished_ok.emit(result)
        except Exception as e:
            self.finished_err.emit(str(e)[:150])


class CompareConfigsWorker(QThread):
    log_message = pyqtSignal(str, str)
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str)

    def __init__(self, symbols, configs, days):
        super().__init__()
        self.symbols = symbols
        self.configs = configs
        self.days = days

    def run(self):
        try:
            self.log_message.emit(
                f"🔬 A/B сравнение: {len(self.configs)} конфигураций, "
                f"{len(self.symbols)} монет, {self.days} дней",
                "#7C4DFF"
            )

            def progress(msg):
                self.log_message.emit(f"  {msg}", "#8A8A8A")

            results = compare_configurations(
                symbols=self.symbols,
                configs=self.configs,
                backtest_days=self.days,
                progress_callback=progress,
            )
            self.finished_ok.emit(results)
        except Exception as e:
            self.finished_err.emit(str(e)[:150])


# ============================================================
# ГЛАВНОЕ ОКНО
# ============================================================
class AutoTraderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)

        if os.path.exists('icon.png'):
            self.setWindowIcon(QIcon('icon.png'))

        self.resize(1600, 940)

        try:
            self.bot = AutoTrader()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось запустить:\n{e}")
            sys.exit(1)

        self.bot.on_log = self.add_log
        self.bot.on_signal = self.on_signal
        self.bot.on_balance = self.on_balance
        self.bot.on_positions = self.on_positions
        self.bot.on_status = self.on_status
        self.bot.on_report = self.on_report

        self.timer = QTimer()
        self.timer.timeout.connect(self.run_cycle)

        self.scanner_worker = None
        self.backtest_worker = None
        self.compare_worker = None
        self._cycle_count = 0
        self.theme = 'dark'

        self.equity = EquityManager() if EQUITY_AVAILABLE else None
        self.reporter = ReportManager() if REPORT_AVAILABLE else None

        self.bt_trades_data = []
        self.compare_results = []

        self._defaults = {}

        self._init_ui()
        self._apply_theme('dark')

        QTimer.singleShot(1000, self._show_mode)
        QTimer.singleShot(2000, self.on_sync_positions)
        QTimer.singleShot(3000, self.refresh_all_charts)
        QTimer.singleShot(5000, self.refresh_heatmap)

        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)

    # ============================================================
    # СТИЛИ
    # ============================================================
    def _btn_style(self, bg, hover, text_color=None):
        if text_color is None:
            try:
                h = bg.lstrip("#")
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                text_color = "white" if lum < 140 else "#1A1A1A"
            except Exception:
                text_color = "white"

        return f"""
            QPushButton {{
                background-color: {bg};
                color: {text_color};
                font-size: 13px;
                font-weight: 600;
                padding: 10px 18px;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.05);
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: {hover};
                border: 1px solid rgba(255,255,255,0.2);
            }}
            QPushButton:pressed {{
                background-color: {bg};
                padding-top: 11px;
                padding-bottom: 9px;
            }}
            QPushButton:disabled {{
                background-color: #2A2A2A;
                color: #666666;
                border: 1px solid #333333;
            }}
        """

    def _apply_theme(self, theme):
        self.theme = theme
        p = Palette

        if theme == 'dark':
            self.setStyleSheet(f"""
                QMainWindow, QWidget {{
                    background-color: {p.BG_MAIN};
                    color: {p.TEXT_MAIN};
                    font-family: 'Segoe UI', 'Inter', 'Arial', sans-serif;
                    font-size: 13px;
                }}

                QGroupBox {{
                    background-color: {p.BG_PANEL};
                    border: 1px solid {p.BORDER};
                    border-radius: 10px;
                    margin-top: 15px;
                    padding: 18px 12px 12px 12px;
                    font-weight: bold;
                    color: {p.BLUE};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 15px;
                    padding: 0 8px;
                    background-color: {p.BG_PANEL};
                }}

                QTableWidget {{
                    background-color: {p.BG_PANEL};
                    color: {p.TEXT_MAIN};
                    gridline-color: {p.BORDER};
                    border: 1px solid {p.BORDER};
                    border-radius: 8px;
                    selection-background-color: {p.BLUE_DARK};
                    selection-color: white;
                    alternate-background-color: #1F1F1F;
                }}
                QTableWidget::item {{
                    padding: 6px;
                    border: none;
                }}
                QHeaderView::section {{
                    background-color: {p.BG_MAIN};
                    color: {p.TEXT_DIM};
                    padding: 10px 8px;
                    border: none;
                    border-bottom: 2px solid {p.BORDER};
                    font-weight: 700;
                    font-size: 12px;
                }}

                QPushButton {{
                    background-color: {p.BG_PANEL};
                    color: {p.TEXT_MAIN};
                    border: 1px solid {p.BORDER};
                    border-radius: 6px;
                    padding: 8px 14px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {p.BG_HOVER};
                    border-color: {p.BLUE};
                }}
                QPushButton:pressed {{
                    background-color: #000000;
                }}
                QPushButton:disabled {{
                    background-color: #1A1A1A;
                    color: #555;
                }}

                QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
                    background-color: {p.BG_INPUT};
                    color: {p.TEXT_MAIN};
                    border: 1px solid {p.BORDER};
                    border-radius: 6px;
                    padding: 7px 10px;
                    selection-background-color: {p.BLUE};
                }}
                QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
                    border: 1px solid {p.BLUE};
                }}
                QComboBox::drop-down {{
                    border: none;
                    padding-right: 8px;
                }}
                QComboBox QAbstractItemView {{
                    background-color: {p.BG_PANEL};
                    color: {p.TEXT_MAIN};
                    border: 1px solid {p.BORDER};
                    selection-background-color: {p.BLUE_DARK};
                }}

                QCheckBox {{
                    color: {p.TEXT_MAIN};
                    spacing: 8px;
                    padding: 4px;
                }}
                QCheckBox::indicator {{
                    width: 18px; height: 18px;
                    border-radius: 4px;
                    border: 2px solid {p.BORDER};
                    background: {p.BG_INPUT};
                }}
                QCheckBox::indicator:checked {{
                    background: {p.GREEN_DARK};
                    border: 2px solid {p.GREEN_DARK};
                }}
                QCheckBox::indicator:hover {{
                    border: 2px solid {p.BLUE};
                }}

                QTabWidget::pane {{
                    border: 1px solid {p.BORDER};
                    background: {p.BG_PANEL};
                    border-radius: 10px;
                    top: -1px;
                }}
                QTabBar::tab {{
                    background: {p.BG_MAIN};
                    color: {p.TEXT_DIM};
                    padding: 10px 22px;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                    margin-right: 3px;
                    font-weight: 600;
                }}
                QTabBar::tab:selected {{
                    background: {p.BG_PANEL};
                    color: {p.BLUE};
                    border-bottom: 2px solid {p.BLUE};
                }}
                QTabBar::tab:hover {{
                    background: {p.BG_HOVER};
                    color: {p.TEXT_MAIN};
                }}

                QScrollBar:vertical {{
                    border: none;
                    background: {p.BG_MAIN};
                    width: 10px;
                    margin: 0;
                }}
                QScrollBar::handle:vertical {{
                    background: #444;
                    min-height: 24px;
                    border-radius: 5px;
                }}
                QScrollBar::handle:vertical:hover {{ background: {p.BLUE}; }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

                QScrollBar:horizontal {{
                    background: {p.BG_MAIN};
                    height: 10px;
                }}
                QScrollBar::handle:horizontal {{
                    background: #444;
                    min-width: 24px;
                    border-radius: 5px;
                }}
                QScrollBar::handle:horizontal:hover {{ background: {p.BLUE}; }}

                QStatusBar {{
                    background-color: {p.BG_PANEL};
                    color: {p.TEXT_DIM};
                    border-top: 1px solid {p.BORDER};
                    font-size: 12px;
                }}
                QStatusBar::item {{ border: none; }}

                QScrollArea {{
                    border: none;
                    background: transparent;
                }}
            """)
            self.btn_theme.setText("🌙")
        else:
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background-color: #F5F5F7;
                    color: #202020;
                    font-family: 'Segoe UI', 'Inter', sans-serif;
                    font-size: 13px;
                }
                QGroupBox {
                    background-color: white;
                    border: 1px solid #DDDDDD;
                    border-radius: 10px;
                    margin-top: 15px;
                    padding: 18px 12px 12px 12px;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 15px; padding: 0 8px;
                    background-color: white;
                }
                QTableWidget {
                    background-color: white;
                    border: 1px solid #DDD;
                    border-radius: 8px;
                    alternate-background-color: #FAFAFA;
                }
                QHeaderView::section {
                    background-color: #EEEEEE;
                    padding: 10px;
                    border: none;
                    font-weight: bold;
                }
                QPushButton {
                    background-color: white;
                    border: 1px solid #CCC;
                    border-radius: 6px;
                    padding: 8px 14px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #EFEFEF; }
                QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                    background-color: white;
                    border: 1px solid #CCC;
                    border-radius: 6px;
                    padding: 7px 10px;
                }
                QTabWidget::pane { border: 1px solid #DDD; background: white; border-radius: 10px; }
                QTabBar::tab {
                    background: #EEE; color: #444;
                    padding: 10px 20px;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                    margin-right: 3px;
                }
                QTabBar::tab:selected { background: white; color: #2962FF; border-bottom: 2px solid #2962FF; }
            """)
            self.btn_theme.setText("☀")

    # ============================================================
    # УТИЛИТЫ
    # ============================================================
    def _vsep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {Palette.BORDER}; background: {Palette.BORDER};")
        sep.setFixedWidth(1)
        sep.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        return sep

    def _tick_clock(self):
        try:
            self.status_time.setText(datetime.now().strftime("%H:%M:%S"))
        except Exception:
            pass

    def _show_mode(self):
        try:
            mode = self.bot.trader.position_mode
            self.lbl_mode.setText(f"Режим: {mode.upper()}")
            color = Palette.ORANGE if mode == 'hedge' else Palette.GREEN
            self.lbl_mode.setStyleSheet(
                f"font-size: 13px; color: {color}; font-weight: 700; "
                f"border: none; background: transparent;"
            )
            self.status_mode.setText(f"Режим: {mode.upper()}")
        except Exception:
            pass

    def notify(self, message, kind="info", duration=3000):
        if TOAST_AVAILABLE:
            try:
                Toast(self, message, kind, duration)
                return
            except Exception:
                pass
        if kind == "error":
            QMessageBox.critical(self, "Ошибка", message)
        elif kind == "warning":
            QMessageBox.warning(self, "Внимание", message)
        else:
            QMessageBox.information(self, "Инфо", message)

    # ============================================================
    # ЗАГРУЗКА ЭТАЛОНА
    # ============================================================
    def _load_defaults(self):
        if self._defaults:
            return self._defaults

        if os.path.exists("defaults.json"):
            try:
                with open("defaults.json", "r", encoding="utf-8") as f:
                    self._defaults = json.load(f)
            except Exception:
                self._defaults = {}
        return self._defaults

    def _hint_pair(self, current_value, default_value, suffix=""):
        wrapper = QWidget()
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        def fmt(v):
            if isinstance(v, bool):
                return "ON" if v else "OFF"
            if isinstance(v, float):
                return f"{v:g}"
            return str(v)

        cur_str = f"{fmt(current_value)}{suffix}"
        def_str = f"{fmt(default_value)}{suffix}"

        lbl_cur = QLabel(f"сейчас: {cur_str}")
        if cur_str == def_str:
            lbl_cur.setStyleSheet(
                "color: #8A8A8A; font-size: 11px; font-style: italic; "
                "padding-left: 8px; border: none; background: transparent;"
            )
        else:
            lbl_cur.setStyleSheet(
                "color: #FFB74D; font-size: 11px; font-style: italic; "
                "padding-left: 8px; border: none; background: transparent; "
                "font-weight: bold;"
            )
        lay.addWidget(lbl_cur)

        lbl_def = QLabel(f"стандарт: {def_str}")
        lbl_def.setStyleSheet(
            "color: #666; font-size: 11px; font-style: italic; "
            "padding-left: 12px; border: none; background: transparent;"
        )
        lay.addWidget(lbl_def)

        lay.addStretch()
        return wrapper

    def _row_with_hint(self, form, label, widget, current_value, default_value, suffix=""):
        widget.setMinimumWidth(130)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        row_layout.addWidget(widget)
        row_layout.addWidget(self._hint_pair(current_value, default_value, suffix))
        row_layout.addStretch()
        form.addRow(label, row)
        return widget

    # ============================================================
    # UI
    # ============================================================
    def _init_ui(self):
        defaults = self._load_defaults()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 8)

        # ============ ВЕРХНЯЯ ПАНЕЛЬ ============
        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_start = QPushButton("▶  СТАРТ")
        self.btn_start.setStyleSheet(self._btn_style(Palette.GREEN_DARK, Palette.GREEN))
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setMinimumWidth(110)
        self.btn_start.clicked.connect(self.on_start)

        self.btn_stop = QPushButton("■  СТОП")
        self.btn_stop.setStyleSheet(self._btn_style(Palette.RED_DARK, Palette.RED))
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setMinimumWidth(110)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_stop.setEnabled(False)

        self.btn_sync = QPushButton("🔄  СИНХР")
        self.btn_sync.setStyleSheet(self._btn_style(Palette.BLUE_DARK, Palette.BLUE))
        self.btn_sync.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sync.clicked.connect(self.on_sync_positions)

        self.btn_open_trade = QPushButton("➕  ОТКРЫТЬ")
        self.btn_open_trade.setStyleSheet(self._btn_style(Palette.PURPLE_DARK, Palette.PURPLE))
        self.btn_open_trade.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_trade.clicked.connect(self.on_manual_open)

        self.btn_report = QPushButton("📊  ОТЧЁТ")
        self.btn_report.setStyleSheet(self._btn_style(Palette.TEAL_DARK, Palette.TEAL))
        self.btn_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_report.clicked.connect(self.on_show_report)

        self.btn_close_all = QPushButton("✕  ЗАКРЫТЬ ВСЁ")
        self.btn_close_all.setStyleSheet(self._btn_style("#8B0000", Palette.RED))
        self.btn_close_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close_all.clicked.connect(self.on_close_all)

        self.btn_bybit = QPushButton("🌐  BYBIT")
        self.btn_bybit.setStyleSheet(self._btn_style(Palette.ORANGE_DARK, Palette.ORANGE))
        self.btn_bybit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bybit.clicked.connect(self.on_open_bybit)

        self.btn_theme = QPushButton("🌙")
        self.btn_theme.setStyleSheet(self._btn_style(Palette.NEUTRAL_DK, Palette.NEUTRAL))
        self.btn_theme.setFixedWidth(50)
        self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme.clicked.connect(self.on_toggle_theme)

        self.lbl_status = QLabel("⏸ Остановлен")
        self.lbl_status.setStyleSheet(
            f"font-size: 15px; font-weight: 700; padding: 8px 16px; "
            f"color: {Palette.TEXT_DIM}; background: {Palette.BG_PANEL}; "
            f"border-radius: 8px; border: 1px solid {Palette.BORDER};"
        )

        top.addWidget(self.btn_start)
        top.addWidget(self.btn_stop)

        top.addWidget(self._vsep())

        top.addWidget(QLabel("Стратегия:"))
        self.combo_strategy = QComboBox()
        for key, name in list_strategies():
            self.combo_strategy.addItem(name, key)
        # установить текущую
        cur = getattr(config, 'ACTIVE_STRATEGY', 'classic_levels')
        idx = self.combo_strategy.findData(cur)
        if idx >= 0:
            self.combo_strategy.setCurrentIndex(idx)
        self.combo_strategy.setMinimumWidth(200)
        self.combo_strategy.currentIndexChanged.connect(self.on_strategy_changed)
        top.addWidget(self.combo_strategy)

        top.addWidget(self._vsep())

        top.addWidget(self.btn_sync)
        top.addWidget(self.btn_open_trade)
        top.addWidget(self.btn_report)
        top.addWidget(self.btn_close_all)
        top.addWidget(self.btn_bybit)
        top.addWidget(self.btn_theme)
        top.addStretch()
        top.addWidget(self.lbl_status)

        layout.addLayout(top)

        # ============ ИНФО-ПАНЕЛЬ ============
        info_frame = QFrame()
        info_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Palette.BG_PANEL};
                border-radius: 12px;
                border: 1px solid {Palette.BORDER};
            }}
        """)
        info = QHBoxLayout(info_frame)
        info.setContentsMargins(20, 14, 20, 14)
        info.setSpacing(16)

        self.lbl_balance = QLabel("💰  —")
        self.lbl_balance.setStyleSheet(
            f"font-size: 18px; color: {Palette.GREEN}; font-weight: 700; "
            f"border: none; background: transparent;"
        )
        info.addWidget(self.lbl_balance)

        info.addWidget(self._vsep())

        self.lbl_equity = QLabel("Equity: —")
        self.lbl_equity.setStyleSheet(
            f"font-size: 14px; color: {Palette.BLUE}; border: none; background: transparent;"
        )
        info.addWidget(self.lbl_equity)

        info.addWidget(self._vsep())

        self.lbl_unrealized = QLabel("Нереализ: —")
        self.lbl_unrealized.setStyleSheet(
            f"font-size: 14px; color: {Palette.TEXT_DIM}; border: none; background: transparent;"
        )
        info.addWidget(self.lbl_unrealized)

        info.addWidget(self._vsep())

        self.lbl_positions_info = QLabel("Позиций: 0/4")
        self.lbl_positions_info.setStyleSheet(
            f"font-size: 14px; color: {Palette.ORANGE}; border: none; background: transparent;"
        )
        info.addWidget(self.lbl_positions_info)

        info.addWidget(self._vsep())

        self.lbl_trades_info = QLabel("Сделок: 0/10")
        self.lbl_trades_info.setStyleSheet(
            f"font-size: 14px; color: {Palette.TEXT_DIM}; border: none; background: transparent;"
        )
        info.addWidget(self.lbl_trades_info)

        info.addStretch()

        self.lbl_daily_pnl = QLabel("+0.00%")
        self.lbl_daily_pnl.setStyleSheet(
            f"font-size: 26px; font-weight: 800; color: {Palette.GREEN}; "
            f"border: none; background: transparent;"
        )
        info.addWidget(self.lbl_daily_pnl)

        layout.addWidget(info_frame)

        # ============ META-ПАНЕЛЬ ============
        meta_frame = QFrame()
        meta_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Palette.BG_PANEL};
                border-radius: 10px;
                border: 1px solid {Palette.BORDER};
            }}
        """)
        meta = QHBoxLayout(meta_frame)
        meta.setContentsMargins(16, 8, 16, 8)
        meta.setSpacing(14)

        self.lbl_last_trade = QLabel("📭  Последняя: нет")
        self.lbl_last_trade.setStyleSheet(
            f"font-size: 13px; color: {Palette.TEXT_DIM}; border: none; background: transparent;"
        )
        meta.addWidget(self.lbl_last_trade)

        meta.addStretch()

        self.lbl_streak = QLabel("Серия: —")
        self.lbl_streak.setStyleSheet(
            f"font-size: 13px; color: {Palette.TEXT_DIM}; border: none; background: transparent;"
        )
        meta.addWidget(self.lbl_streak)

        meta.addWidget(self._vsep())

        self.lbl_mode = QLabel("Режим: ?")
        self.lbl_mode.setStyleSheet(
            f"font-size: 13px; color: {Palette.TEXT_DIM}; border: none; background: transparent;"
        )
        meta.addWidget(self.lbl_mode)

        layout.addWidget(meta_frame)

        # ============ ВКЛАДКИ ============
        self.tabs = QTabWidget()

        # ---- Автобот ----
        tab_main = QWidget()
        main_layout = QVBoxLayout(tab_main)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        self.coins_group = QGroupBox(f"Монеты ({len(config.AUTO_SYMBOLS)})")
        coins_layout = QVBoxLayout(self.coins_group)
        self.coins_label = QLabel("  ".join(config.AUTO_SYMBOLS))
        self.coins_label.setStyleSheet(
            f"font-size: 13px; color: {Palette.GREEN}; padding: 10px; "
            f"background: {Palette.BG_MAIN}; border-radius: 6px;"
        )
        self.coins_label.setWordWrap(True)
        coins_layout.addWidget(self.coins_label)
        main_layout.addWidget(self.coins_group)

        pos_group = QGroupBox("Открытые позиции")
        pos_layout = QVBoxLayout(pos_group)
        self.table_positions = QTableWidget()
        self.table_positions.setColumnCount(11)
        self.table_positions.setHorizontalHeaderLabels([
            "Монета", "Сторона", "Плечо", "Вход", "Текущая", "Размер $",
            "Стоп", "Тейк", "P&L %", "P&L $", "Доп"
        ])
        h = self.table_positions.horizontalHeader()
        for i in range(10):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
        self.table_positions.verticalHeader().setDefaultSectionSize(32)
        self.table_positions.setAlternatingRowColors(True)
        self.table_positions.setShowGrid(False)
        pos_layout.addWidget(self.table_positions)
        main_layout.addWidget(pos_group)

        log_group = QGroupBox("Лог")
        log_layout = QVBoxLayout(log_group)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Palette.BG_MAIN};
                color: {Palette.TEXT_MAIN};
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                border: 1px solid {Palette.BORDER};
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        log_layout.addWidget(self.log)
        main_layout.addWidget(log_group)

        self.tabs.addTab(tab_main, "🤖  Автобот")

        # ---- Графики ----
        tab_charts = QWidget()
        charts_layout = QVBoxLayout(tab_charts)
        charts_layout.setContentsMargins(12, 12, 12, 12)

        chart_top = QHBoxLayout()
        chart_top.setSpacing(10)

        lbl_chart = QLabel("График цены:")
        lbl_chart.setStyleSheet(f"font-weight: 700; color: {Palette.TEXT_DIM};")
        chart_top.addWidget(lbl_chart)

        self.combo_chart_symbol = QComboBox()
        self.combo_chart_symbol.addItems(config.AUTO_SYMBOLS)
        self.combo_chart_symbol.setMinimumWidth(220)
        self.combo_chart_symbol.currentTextChanged.connect(self.update_price_chart)
        chart_top.addWidget(self.combo_chart_symbol)

        self.btn_refresh_chart = QPushButton("🔄  ОБНОВИТЬ")
        self.btn_refresh_chart.setStyleSheet(self._btn_style(Palette.TEAL_DARK, Palette.TEAL))
        self.btn_refresh_chart.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_chart.clicked.connect(self.update_price_chart)
        chart_top.addWidget(self.btn_refresh_chart)

        chart_top.addStretch()
        charts_layout.addLayout(chart_top)

        if CHART_AVAILABLE:
            splitter = QSplitter(Qt.Orientation.Vertical)
            self.price_chart = PriceChart()
            self.equity_chart = EquityChart()
            splitter.addWidget(self.price_chart)
            splitter.addWidget(self.equity_chart)
            splitter.setSizes([520, 380])
            charts_layout.addWidget(splitter)
        else:
            lbl_warn = QLabel("⚠  pyqtgraph не установлен\n\npip install pyqtgraph")
            lbl_warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_warn.setStyleSheet(f"color: {Palette.ORANGE}; font-size: 14px; padding: 40px;")
            charts_layout.addWidget(lbl_warn)

        self.tabs.addTab(tab_charts, "📈  Графики")

        # ---- Тепловая карта ----
        tab_heatmap = QWidget()
        hm_layout = QVBoxLayout(tab_heatmap)
        hm_layout.setContentsMargins(12, 12, 12, 12)

        hm_top = QHBoxLayout()
        self.btn_refresh_hm = QPushButton("🔄  ОБНОВИТЬ")
        self.btn_refresh_hm.setStyleSheet(self._btn_style(Palette.TEAL_DARK, Palette.TEAL))
        self.btn_refresh_hm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_hm.clicked.connect(self.refresh_heatmap)
        hm_top.addWidget(self.btn_refresh_hm)
        hm_top.addStretch()
        hm_layout.addLayout(hm_top)

        self.table_heatmap = QTableWidget()
        self.table_heatmap.setColumnCount(5)
        self.table_heatmap.setHorizontalHeaderLabels([
            "Монета", "Сделок", "Побед", "P&L $", "P&L %"
        ])
        hh = self.table_heatmap.horizontalHeader()
        for i in range(5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.table_heatmap.verticalHeader().setDefaultSectionSize(32)
        self.table_heatmap.setAlternatingRowColors(True)
        self.table_heatmap.setShowGrid(False)
        hm_layout.addWidget(self.table_heatmap)

        self.tabs.addTab(tab_heatmap, "🌡  Тепловая карта")

        # ---- Календарь ----
        tab_calendar = QWidget()
        cal_layout = QVBoxLayout(tab_calendar)
        cal_layout.setContentsMargins(12, 12, 12, 12)

        cal_top = QHBoxLayout()
        self.btn_refresh_cal = QPushButton("🔄  ОБНОВИТЬ")
        self.btn_refresh_cal.setStyleSheet(self._btn_style(Palette.TEAL_DARK, Palette.TEAL))
        self.btn_refresh_cal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_cal.clicked.connect(self.refresh_calendar)
        cal_top.addWidget(self.btn_refresh_cal)
        cal_top.addStretch()
        cal_layout.addLayout(cal_top)

        self.calendar_grid = QGridLayout()
        self.calendar_grid.setSpacing(8)
        cal_widget = QWidget()
        cal_widget.setLayout(self.calendar_grid)
        cal_layout.addWidget(cal_widget)
        cal_layout.addStretch()

        self.tabs.addTab(tab_calendar, "📅  Календарь")

        # ---- История ----
        tab_history = QWidget()
        history_layout = QVBoxLayout(tab_history)
        history_layout.setContentsMargins(12, 12, 12, 12)

        hist_top = QHBoxLayout()
        hist_top.setSpacing(8)

        self.btn_export_csv = QPushButton("📥  ЭКСПОРТ CSV")
        self.btn_export_csv.setStyleSheet(self._btn_style(Palette.BLUE_DARK, Palette.BLUE))
        self.btn_export_csv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_csv.clicked.connect(self.on_export_csv)
        hist_top.addWidget(self.btn_export_csv)

        self.btn_clear_history = QPushButton("🗑  ОЧИСТИТЬ")
        self.btn_clear_history.setStyleSheet(self._btn_style("#8B0000", Palette.RED))
        self.btn_clear_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_history.clicked.connect(self.on_clear_history)
        hist_top.addWidget(self.btn_clear_history)

        self.btn_refresh_history = QPushButton("🔄  ОБНОВИТЬ")
        self.btn_refresh_history.setStyleSheet(self._btn_style(Palette.TEAL_DARK, Palette.TEAL))
        self.btn_refresh_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_history.clicked.connect(self.refresh_history)
        hist_top.addWidget(self.btn_refresh_history)

        hist_top.addStretch()
        history_layout.addLayout(hist_top)

        self.table_history = QTableWidget()
        self.table_history.setColumnCount(8)
        self.table_history.setHorizontalHeaderLabels([
            "Дата", "Монета", "Сторона", "Вход", "Выход", "Размер $", "P&L %", "P&L $"
        ])
        hhh = self.table_history.horizontalHeader()
        for i in range(8):
            hhh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.table_history.verticalHeader().setDefaultSectionSize(32)
        self.table_history.setAlternatingRowColors(True)
        self.table_history.setShowGrid(False)
        history_layout.addWidget(self.table_history)

        self.tabs.addTab(tab_history, "📊  История")

        # ---- Статистика ----
        tab_stats = QWidget()
        stats_layout = QVBoxLayout(tab_stats)
        stats_layout.setContentsMargins(12, 12, 12, 12)

        self.stats_label = QLabel("Загрузка...")
        self.stats_label.setStyleSheet(f"""
            QLabel {{
                background-color: {Palette.BG_PANEL};
                color: {Palette.TEXT_MAIN};
                font-family: 'Consolas', monospace;
                font-size: 13px;
                padding: 20px;
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
            }}
        """)
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.stats_label.setWordWrap(True)
        stats_layout.addWidget(self.stats_label)

        self.tabs.addTab(tab_stats, "📈  Статистика")

        # ============ ОСТАЛЬНЫЕ ВКЛАДКИ ============
        self._build_tab_settings(defaults)
        self._build_tab_api()
        self._build_tab_backtest()
        self._build_tab_bt_settings(defaults)
        self._build_tab_bt_trades()
        self._build_tab_compare()
        self._build_tab_scanner(defaults)
        self._build_tab_advisor()
        self._build_tab_strategy()

        layout.addWidget(self.tabs)

        # ============ СТАТУСБАР ============
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.setSizeGripEnabled(False)

        self.status_balance = QLabel("💰  $0.00")
        self.status_balance.setStyleSheet(f"color: {Palette.GREEN}; padding: 0 12px; font-weight: 600;")
        self.statusbar.addWidget(self.status_balance)

        self.status_positions = QLabel("📊  Позиций: 0/4")
        self.status_positions.setStyleSheet(f"color: {Palette.ORANGE}; padding: 0 12px;")
        self.statusbar.addWidget(self.status_positions)

        self.status_trades = QLabel("📈  Сделок: 0/10")
        self.status_trades.setStyleSheet(f"color: {Palette.TEXT_DIM}; padding: 0 12px;")
        self.statusbar.addWidget(self.status_trades)

        self.status_mode = QLabel("Режим: ?")
        self.status_mode.setStyleSheet(f"color: {Palette.BLUE}; padding: 0 12px;")
        self.statusbar.addPermanentWidget(self.status_mode)

        self.status_time = QLabel(datetime.now().strftime("%H:%M:%S"))
        self.status_time.setStyleSheet(f"color: {Palette.TEXT_DIM}; padding: 0 12px;")
        self.statusbar.addPermanentWidget(self.status_time)

        # Стартовые сообщения
        self.add_log(f"🤖 {APP_NAME} готов к работе", Palette.GREEN)
        self.add_log(f"MTF: {config.USE_MULTI_TIMEFRAME} | Адаптив: {config.USE_ADAPTIVE_SIZE}", Palette.TEXT_DIM)
        self.add_log(f"Trailing: {config.USE_TRAILING_STOP} | Адапт.стоп: {config.USE_ADAPTIVE_STOP}", Palette.TEXT_DIM)
        self.add_log(f"Пирамидинг: {config.USE_PYRAMIDING} | Хедж: {config.USE_HEDGING}", Palette.TEXT_DIM)

        self.refresh_history()
        self.refresh_stats()
        QTimer.singleShot(1500, self.refresh_calendar)
        QTimer.singleShot(1500, self.refresh_heatmap)

    def _build_tab_scanner(self, defaults):
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(14)
        lay.setContentsMargins(12, 12, 12, 12)

        # ---- Параметры фильтра ----
        g1 = QGroupBox("🔎 Параметры фильтра")
        f1 = QFormLayout(g1)
        f1.setSpacing(10)
        f1.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.sc_max_price = QDoubleSpinBox()
        self.sc_max_price.setRange(0.001, 1000)
        self.sc_max_price.setDecimals(3)
        self.sc_max_price.setSuffix(" $")
        self.sc_max_price.setValue(getattr(config, 'SCANNER_MAX_PRICE', 5.0))
        self._row_with_hint(f1, "Макс. цена:", self.sc_max_price,
                            getattr(config, 'SCANNER_MAX_PRICE', 5.0),
                            defaults.get("SCANNER_MAX_PRICE", 5.0), " $")

        self.sc_min_volume = QDoubleSpinBox()
        self.sc_min_volume.setRange(100_000, 10_000_000_000)
        self.sc_min_volume.setDecimals(0)
        self.sc_min_volume.setSuffix(" $")
        self.sc_min_volume.setValue(getattr(config, 'SCANNER_MIN_VOLUME_USD', 15_000_000))
        self.sc_min_volume.setSingleStep(1_000_000)
        self._row_with_hint(f1, "Мин. объём 24ч:", self.sc_min_volume,
                            getattr(config, 'SCANNER_MIN_VOLUME_USD', 15_000_000),
                            defaults.get("SCANNER_MIN_VOLUME_USD", 15_000_000), " $")

        self.sc_min_atr = QDoubleSpinBox()
        self.sc_min_atr.setRange(0.5, 50)
        self.sc_min_atr.setDecimals(1)
        self.sc_min_atr.setSuffix(" %")
        self.sc_min_atr.setValue(getattr(config, 'SCANNER_MIN_ATR_PCT', 6.0))
        self._row_with_hint(f1, "ATR% мин:", self.sc_min_atr,
                            getattr(config, 'SCANNER_MIN_ATR_PCT', 6.0),
                            defaults.get("SCANNER_MIN_ATR_PCT", 6.0), " %")

        self.sc_max_atr = QDoubleSpinBox()
        self.sc_max_atr.setRange(0.5, 50)
        self.sc_max_atr.setDecimals(1)
        self.sc_max_atr.setSuffix(" %")
        self.sc_max_atr.setValue(getattr(config, 'SCANNER_MAX_ATR_PCT', 11.0))
        self._row_with_hint(f1, "ATR% макс:", self.sc_max_atr,
                            getattr(config, 'SCANNER_MAX_ATR_PCT', 11.0),
                            defaults.get("SCANNER_MAX_ATR_PCT", 11.0), " %")

        self.sc_min_change = QDoubleSpinBox()
        self.sc_min_change.setRange(0.1, 50)
        self.sc_min_change.setDecimals(1)
        self.sc_min_change.setSuffix(" %")
        self.sc_min_change.setValue(getattr(config, 'SCANNER_MIN_CHANGE_PCT', 2.0))
        self._row_with_hint(f1, "Изменение 24ч мин:", self.sc_min_change,
                            getattr(config, 'SCANNER_MIN_CHANGE_PCT', 2.0),
                            defaults.get("SCANNER_MIN_CHANGE_PCT", 2.0), " %")

        self.sc_max_change = QDoubleSpinBox()
        self.sc_max_change.setRange(0.1, 100)
        self.sc_max_change.setDecimals(1)
        self.sc_max_change.setSuffix(" %")
        self.sc_max_change.setValue(getattr(config, 'SCANNER_MAX_CHANGE_PCT', 15.0))
        self._row_with_hint(f1, "Изменение 24ч макс:", self.sc_max_change,
                            getattr(config, 'SCANNER_MAX_CHANGE_PCT', 15.0),
                            defaults.get("SCANNER_MAX_CHANGE_PCT", 15.0), " %")

        self.sc_min_daily = QSpinBox()
        self.sc_min_daily.setRange(10, 365)
        self.sc_min_daily.setSuffix(" дней")
        self.sc_min_daily.setValue(getattr(config, 'SCANNER_MIN_DAILY_CANDLES', 90))
        self._row_with_hint(f1, "Мин. история:", self.sc_min_daily,
                            getattr(config, 'SCANNER_MIN_DAILY_CANDLES', 90),
                            defaults.get("SCANNER_MIN_DAILY_CANDLES", 90), " дней")

        self.sc_max_3day = QDoubleSpinBox()
        self.sc_max_3day.setRange(1, 100)
        self.sc_max_3day.setDecimals(1)
        self.sc_max_3day.setSuffix(" %")
        self.sc_max_3day.setValue(getattr(config, 'SCANNER_MAX_3DAY_MOVE_PCT', 20.0))
        self._row_with_hint(f1, "Макс. движ. 3д:", self.sc_max_3day,
                            getattr(config, 'SCANNER_MAX_3DAY_MOVE_PCT', 20.0),
                            defaults.get("SCANNER_MAX_3DAY_MOVE_PCT", 20.0), " %")

        self.sc_top_n = QSpinBox()
        self.sc_top_n.setRange(3, 50)
        self.sc_top_n.setSuffix(" монет")
        self.sc_top_n.setValue(getattr(config, 'SCANNER_TOP_N', 10))
        self._row_with_hint(f1, "Топ N:", self.sc_top_n,
                            getattr(config, 'SCANNER_TOP_N', 10),
                            defaults.get("SCANNER_TOP_N", 10), " монет")

        lay.addWidget(g1)

        # ---- Чёрный список ----
        g2 = QGroupBox("🚫 Чёрный список монет")
        f2 = QVBoxLayout(g2)

        info = QLabel("Монеты (по одной на строку), которые НИКОГДА не будут добавлены сканером.")
        info.setStyleSheet(f"color: {Palette.TEXT_DIM}; font-size: 12px; padding: 4px;")
        f2.addWidget(info)

        self.sc_blacklist = QTextEdit()
        bl = getattr(config, 'SCANNER_BLACKLIST', [])
        self.sc_blacklist.setPlainText("\n".join(bl))
        self.sc_blacklist.setMaximumHeight(180)
        self.sc_blacklist.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Palette.BG_MAIN};
                color: {Palette.TEXT_MAIN};
                font-family: 'Consolas', monospace;
                font-size: 13px;
                border: 1px solid {Palette.BORDER};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        f2.addWidget(self.sc_blacklist)
        lay.addWidget(g2)

        # ---- Автоскан ----
        g3 = QGroupBox("⏰ Автоскан монет")
        f3 = QFormLayout(g3)
        f3.setSpacing(10)
        f3.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.sc_auto_enabled = QCheckBox("Включить автоскан")
        self.sc_auto_enabled.setChecked(getattr(config, 'SCANNER_AUTO_ENABLED', False))
        f3.addRow("", self.sc_auto_enabled)

        self.sc_auto_hours = QSpinBox()
        self.sc_auto_hours.setRange(1, 168)
        self.sc_auto_hours.setSuffix(" ч")
        self.sc_auto_hours.setValue(getattr(config, 'SCANNER_AUTO_HOURS', 24))
        self._row_with_hint(f3, "Интервал:", self.sc_auto_hours,
                            getattr(config, 'SCANNER_AUTO_HOURS', 24),
                            defaults.get("SCANNER_AUTO_HOURS", 24), " ч")

        info2 = QLabel("Раз в N часов бот автоматически запустит сканер и обновит список монет в config.py.")
        info2.setStyleSheet(f"color: {Palette.TEXT_DIM}; font-size: 11px; font-style: italic; padding: 4px;")
        info2.setWordWrap(True)
        f3.addRow("", info2)

        lay.addWidget(g3)

        # ---- Кнопки ----
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_sc_save = QPushButton("💾  СОХРАНИТЬ В CONFIG")
        self.btn_sc_save.setStyleSheet(self._btn_style(Palette.GREEN_DARK, Palette.GREEN))
        self.btn_sc_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sc_save.clicked.connect(self.on_save_scanner_settings)
        btns.addWidget(self.btn_sc_save)

        self.btn_sc_reset = QPushButton("↺  СБРОСИТЬ К СТАНДАРТУ")
        self.btn_sc_reset.setStyleSheet(self._btn_style(Palette.NEUTRAL_DK, Palette.NEUTRAL))
        self.btn_sc_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sc_reset.clicked.connect(self.on_reset_scanner_settings)
        btns.addWidget(self.btn_sc_reset)

        self.btn_sc_run_now = QPushButton("🔍  ЗАПУСТИТЬ СКАН СЕЙЧАС")
        self.btn_sc_run_now.setStyleSheet(self._btn_style(Palette.PURPLE_DARK, Palette.PURPLE))
        self.btn_sc_run_now.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sc_run_now.clicked.connect(self.on_scan_now_from_tab)
        btns.addWidget(self.btn_sc_run_now)

        btns.addStretch()
        lay.addLayout(btns)
        lay.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.tabs.addTab(tab, "🔍  Фильтры монет")

    # ============================================================
    # СОХРАНЕНИЕ / СБРОС ФИЛЬТРОВ СКАНЕРА
    # ============================================================
    def on_save_scanner_settings(self):
        try:
            blacklist_raw = self.sc_blacklist.toPlainText().strip()
            blacklist = [b.strip() for b in blacklist_raw.split('\n') if b.strip()]

            for b in blacklist:
                if not re.match(r'^[A-Z0-9]+/USDT:USDT$', b):
                    self.notify(f"Неверный формат в чёрном списке: {b}", "error")
                    return

            values = {
                'SCANNER_MAX_PRICE': self.sc_max_price.value(),
                'SCANNER_MIN_VOLUME_USD': self.sc_min_volume.value(),
                'SCANNER_MIN_ATR_PCT': self.sc_min_atr.value(),
                'SCANNER_MAX_ATR_PCT': self.sc_max_atr.value(),
                'SCANNER_MIN_CHANGE_PCT': self.sc_min_change.value(),
                'SCANNER_MAX_CHANGE_PCT': self.sc_max_change.value(),
                'SCANNER_MIN_DAILY_CANDLES': self.sc_min_daily.value(),
                'SCANNER_MAX_3DAY_MOVE_PCT': self.sc_max_3day.value(),
                'SCANNER_TOP_N': self.sc_top_n.value(),
                'SCANNER_AUTO_ENABLED': self.sc_auto_enabled.isChecked(),
                'SCANNER_AUTO_HOURS': self.sc_auto_hours.value(),
            }

            # Сохраняем в config.py через regex
            self._update_config_file(values, config.AUTO_SYMBOLS)

            # Чёрный список — отдельно (список)
            self._update_blacklist_in_config(blacklist)

            # Применяем к runtime config
            for k, v in values.items():
                setattr(config, k, v)
            config.SCANNER_BLACKLIST = blacklist

            self.notify("Фильтры сканера сохранены", "success")
            self.add_log("💾 Фильтры сканера → config.py", Palette.GREEN)
        except Exception as e:
            self.notify(str(e), "error")

    def _update_blacklist_in_config(self, blacklist):
        """Обновляет SCANNER_BLACKLIST = [...] в config.py."""
        with open('config.py', 'r', encoding='utf-8') as f:
            content = f.read()

        block = "SCANNER_BLACKLIST = [\n"
        for b in blacklist:
            block += f"    '{b}',\n"
        block += "]"

        new_content = re.sub(
            r'^SCANNER_BLACKLIST\s*=\s*\[[^\]]*\]',
            block, content,
            flags=re.MULTILINE | re.DOTALL
        )

        if new_content == content:
            # Параметр не найден — добавляем в конец
            new_content = content + "\n\n" + block + "\n"

        with open('config.py', 'w', encoding='utf-8') as f:
            f.write(new_content)

    def on_reset_scanner_settings(self):
        defaults = self._load_defaults()
        if not defaults:
            self.notify("defaults.json не найден", "warning")
            return

        reply = QMessageBox.question(
            self, "Сброс",
            "Сбросить фильтры сканера к стандартным?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.sc_max_price.setValue(defaults.get("SCANNER_MAX_PRICE", 5.0))
        self.sc_min_volume.setValue(defaults.get("SCANNER_MIN_VOLUME_USD", 15_000_000))
        self.sc_min_atr.setValue(defaults.get("SCANNER_MIN_ATR_PCT", 6.0))
        self.sc_max_atr.setValue(defaults.get("SCANNER_MAX_ATR_PCT", 11.0))
        self.sc_min_change.setValue(defaults.get("SCANNER_MIN_CHANGE_PCT", 2.0))
        self.sc_max_change.setValue(defaults.get("SCANNER_MAX_CHANGE_PCT", 15.0))
        self.sc_min_daily.setValue(defaults.get("SCANNER_MIN_DAILY_CANDLES", 90))
        self.sc_max_3day.setValue(defaults.get("SCANNER_MAX_3DAY_MOVE_PCT", 20.0))
        self.sc_top_n.setValue(defaults.get("SCANNER_TOP_N", 10))
        self.sc_auto_enabled.setChecked(defaults.get("SCANNER_AUTO_ENABLED", False))
        self.sc_auto_hours.setValue(defaults.get("SCANNER_AUTO_HOURS", 24))

        bl = defaults.get("SCANNER_BLACKLIST", [])
        self.sc_blacklist.setPlainText("\n".join(bl))

        self.notify("Фильтры сброшены к стандартным", "info")

    def on_scan_now_from_tab(self):
        """Запуск скана прямо из вкладки фильтров."""
        if self.scanner_worker is not None:
            self.notify("Скан уже идёт", "warning")
            return
        self.on_refresh_coins()

    def _build_tab_settings(self, defaults):
        tab_settings = QWidget()
        settings_outer = QVBoxLayout(tab_settings)
        settings_outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        settings_layout = QVBoxLayout(scroll_content)
        settings_layout.setSpacing(14)
        settings_layout.setContentsMargins(12, 12, 12, 12)

        # ========== ТОРГОВЛЯ ==========
        g1 = QGroupBox("💰 Торговля")
        f1 = QFormLayout(g1)
        f1.setSpacing(10)
        f1.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_pct = QDoubleSpinBox()
        self.s_pct.setRange(0.5, 50); self.s_pct.setDecimals(1); self.s_pct.setSuffix(" %")
        self.s_pct.setValue(config.AUTO_POSITION_PCT)
        self._row_with_hint(f1, "% от баланса:", self.s_pct,
                            config.AUTO_POSITION_PCT,
                            defaults.get("AUTO_POSITION_PCT", 5.0), " %")

        self.s_trades = QSpinBox()
        self.s_trades.setRange(1, 100)
        self.s_trades.setValue(config.AUTO_MAX_TRADES_PER_DAY)
        self._row_with_hint(f1, "Сделок/день:", self.s_trades,
                            config.AUTO_MAX_TRADES_PER_DAY,
                            defaults.get("AUTO_MAX_TRADES_PER_DAY", 15))

        self.s_stop = QDoubleSpinBox()
        self.s_stop.setRange(0.5, 50); self.s_stop.setDecimals(1); self.s_stop.setSuffix(" %")
        self.s_stop.setValue(config.AUTO_DAILY_STOP_PCT)
        self._row_with_hint(f1, "Дневной стоп:", self.s_stop,
                            config.AUTO_DAILY_STOP_PCT,
                            defaults.get("AUTO_DAILY_STOP_PCT", 3.0), " %")

        self.s_positions = QSpinBox()
        self.s_positions.setRange(1, 30)
        self.s_positions.setValue(config.MAX_POSITIONS_TOTAL)
        self._row_with_hint(f1, "Макс. позиций:", self.s_positions,
                            config.MAX_POSITIONS_TOTAL,
                            defaults.get("MAX_POSITIONS_TOTAL", 4))

        self.s_interval = QSpinBox()
        self.s_interval.setRange(15, 3600); self.s_interval.setSuffix(" сек")
        self.s_interval.setValue(config.AUTO_CHECK_INTERVAL_SEC)
        self._row_with_hint(f1, "Интервал проверки:", self.s_interval,
                            config.AUTO_CHECK_INTERVAL_SEC,
                            defaults.get("AUTO_CHECK_INTERVAL_SEC", 60), " сек")

        self.s_min_size = QDoubleSpinBox()
        self.s_min_size.setRange(1, 1000); self.s_min_size.setSuffix(" $")
        self.s_min_size.setValue(config.AUTO_MIN_POSITION_USD)
        self._row_with_hint(f1, "Мин. размер:", self.s_min_size,
                            config.AUTO_MIN_POSITION_USD,
                            defaults.get("AUTO_MIN_POSITION_USD", 10), " $")

        self.s_max_size = QDoubleSpinBox()
        self.s_max_size.setRange(1, 10000); self.s_max_size.setSuffix(" $")
        self.s_max_size.setValue(config.AUTO_MAX_POSITION_USD)
        self._row_with_hint(f1, "Макс. размер:", self.s_max_size,
                            config.AUTO_MAX_POSITION_USD,
                            defaults.get("AUTO_MAX_POSITION_USD", 500), " $")

        self.s_min_balance = QDoubleSpinBox()
        self.s_min_balance.setRange(0, 10000); self.s_min_balance.setSuffix(" $")
        self.s_min_balance.setValue(config.AUTO_MIN_FREE_BALANCE)
        self._row_with_hint(f1, "Мин. баланс:", self.s_min_balance,
                            config.AUTO_MIN_FREE_BALANCE,
                            defaults.get("AUTO_MIN_FREE_BALANCE", 50), " $")

        settings_layout.addWidget(g1)

        # ========== ПЛЕЧО ==========
        g2 = QGroupBox("⚖ Плечо")
        f2 = QFormLayout(g2)
        f2.setSpacing(10)
        f2.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_max_lev = QDoubleSpinBox()
        self.s_max_lev.setRange(1, 20); self.s_max_lev.setDecimals(1); self.s_max_lev.setSuffix(" x")
        self.s_max_lev.setValue(config.MAX_AUTO_LEVERAGE)
        self._row_with_hint(f2, "Макс. плечо:", self.s_max_lev,
                            config.MAX_AUTO_LEVERAGE,
                            defaults.get("MAX_AUTO_LEVERAGE", 2.0), " x")

        self.s_def_lev = QDoubleSpinBox()
        self.s_def_lev.setRange(1, 20); self.s_def_lev.setDecimals(1); self.s_def_lev.setSuffix(" x")
        self.s_def_lev.setValue(config.DEFAULT_LEVERAGE)
        self._row_with_hint(f2, "Плечо по умолчанию:", self.s_def_lev,
                            config.DEFAULT_LEVERAGE,
                            defaults.get("DEFAULT_LEVERAGE", 2.0), " x")

        self.s_auto_lev = QCheckBox("Использовать авто-плечо")
        self.s_auto_lev.setChecked(config.USE_AUTO_LEVERAGE)
        f2.addRow("", self.s_auto_lev)

        settings_layout.addWidget(g2)

        # ========== СТОП / ТЕЙК ==========
        g3 = QGroupBox("🎯 Стоп / Тейк")
        f3 = QFormLayout(g3)
        f3.setSpacing(10)
        f3.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_stop_calm = QDoubleSpinBox()
        self.s_stop_calm.setRange(0.5, 20); self.s_stop_calm.setDecimals(2); self.s_stop_calm.setSuffix(" %")
        self.s_stop_calm.setValue(config.STOP_PCT_CALM)
        self._row_with_hint(f3, "Стоп (calm):", self.s_stop_calm,
                            config.STOP_PCT_CALM,
                            defaults.get("STOP_PCT_CALM", 2.5), " %")

        self.s_take_calm = QDoubleSpinBox()
        self.s_take_calm.setRange(0.5, 30); self.s_take_calm.setDecimals(2); self.s_take_calm.setSuffix(" %")
        self.s_take_calm.setValue(config.TAKE_PCT_CALM)
        self._row_with_hint(f3, "Тейк (calm):", self.s_take_calm,
                            config.TAKE_PCT_CALM,
                            defaults.get("TAKE_PCT_CALM", 5.0), " %")

        self.s_cooldown = QSpinBox()
        self.s_cooldown.setRange(0, 1440); self.s_cooldown.setSuffix(" мин")
        self.s_cooldown.setValue(config.COOLDOWN_MINUTES)
        self._row_with_hint(f3, "Cooldown:", self.s_cooldown,
                            config.COOLDOWN_MINUTES,
                            defaults.get("COOLDOWN_MINUTES", 120), " мин")

        # ==== АДАПТИВНЫЙ СТОП ПО ATR ====
        self.s_use_adaptive_stop = QCheckBox("🎯 Адаптивный стоп по ATR")
        self.s_use_adaptive_stop.setChecked(getattr(config, 'USE_ADAPTIVE_STOP', True))
        f3.addRow("", self.s_use_adaptive_stop)

        self.s_stop_atr_mult = QDoubleSpinBox()
        self.s_stop_atr_mult.setRange(0.1, 3.0)
        self.s_stop_atr_mult.setDecimals(2)
        self.s_stop_atr_mult.setSingleStep(0.1)
        self.s_stop_atr_mult.setValue(getattr(config, 'ADAPTIVE_STOP_ATR_MULT', 0.6))
        self._row_with_hint(f3, "Стоп × ATR:", self.s_stop_atr_mult,
                            getattr(config, 'ADAPTIVE_STOP_ATR_MULT', 0.6),
                            defaults.get("ADAPTIVE_STOP_ATR_MULT", 0.6))

        self.s_take_atr_mult = QDoubleSpinBox()
        self.s_take_atr_mult.setRange(0.1, 5.0)
        self.s_take_atr_mult.setDecimals(2)
        self.s_take_atr_mult.setSingleStep(0.1)
        self.s_take_atr_mult.setValue(getattr(config, 'ADAPTIVE_TAKE_ATR_MULT', 1.2))
        self._row_with_hint(f3, "Тейк × ATR:", self.s_take_atr_mult,
                            getattr(config, 'ADAPTIVE_TAKE_ATR_MULT', 1.2),
                            defaults.get("ADAPTIVE_TAKE_ATR_MULT", 1.2))

        self.s_stop_atr_min = QDoubleSpinBox()
        self.s_stop_atr_min.setRange(0.5, 20); self.s_stop_atr_min.setDecimals(2); self.s_stop_atr_min.setSuffix(" %")
        self.s_stop_atr_min.setValue(getattr(config, 'ADAPTIVE_STOP_MIN_PCT', 1.5))
        self._row_with_hint(f3, "Стоп мин %:", self.s_stop_atr_min,
                            getattr(config, 'ADAPTIVE_STOP_MIN_PCT', 1.5),
                            defaults.get("ADAPTIVE_STOP_MIN_PCT", 1.5), " %")

        self.s_stop_atr_max = QDoubleSpinBox()
        self.s_stop_atr_max.setRange(0.5, 30); self.s_stop_atr_max.setDecimals(2); self.s_stop_atr_max.setSuffix(" %")
        self.s_stop_atr_max.setValue(getattr(config, 'ADAPTIVE_STOP_MAX_PCT', 8.0))
        self._row_with_hint(f3, "Стоп макс %:", self.s_stop_atr_max,
                            getattr(config, 'ADAPTIVE_STOP_MAX_PCT', 8.0),
                            defaults.get("ADAPTIVE_STOP_MAX_PCT", 8.0), " %")

        self.s_take_atr_min = QDoubleSpinBox()
        self.s_take_atr_min.setRange(0.5, 30); self.s_take_atr_min.setDecimals(2); self.s_take_atr_min.setSuffix(" %")
        self.s_take_atr_min.setValue(getattr(config, 'ADAPTIVE_TAKE_MIN_PCT', 3.0))
        self._row_with_hint(f3, "Тейк мин %:", self.s_take_atr_min,
                            getattr(config, 'ADAPTIVE_TAKE_MIN_PCT', 3.0),
                            defaults.get("ADAPTIVE_TAKE_MIN_PCT", 3.0), " %")

        self.s_take_atr_max = QDoubleSpinBox()
        self.s_take_atr_max.setRange(0.5, 50); self.s_take_atr_max.setDecimals(2); self.s_take_atr_max.setSuffix(" %")
        self.s_take_atr_max.setValue(getattr(config, 'ADAPTIVE_TAKE_MAX_PCT', 16.0))
        self._row_with_hint(f3, "Тейк макс %:", self.s_take_atr_max,
                            getattr(config, 'ADAPTIVE_TAKE_MAX_PCT', 16.0),
                            defaults.get("ADAPTIVE_TAKE_MAX_PCT", 16.0), " %")

        settings_layout.addWidget(g3)

        # ========== СИГНАЛЫ ==========
        g4 = QGroupBox("📡 Сигналы")
        f4 = QFormLayout(g4)
        f4.setSpacing(10)
        f4.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_near = QDoubleSpinBox()
        self.s_near.setRange(0.1, 5); self.s_near.setDecimals(2); self.s_near.setSuffix(" %")
        self.s_near.setValue(config.NEAR_LEVEL_PCT)
        self._row_with_hint(f4, "Близость к уровню:", self.s_near,
                            config.NEAR_LEVEL_PCT,
                            defaults.get("NEAR_LEVEL_PCT", 0.8), " %")

        self.s_pinbar = QDoubleSpinBox()
        self.s_pinbar.setRange(0.5, 5); self.s_pinbar.setDecimals(2)
        self.s_pinbar.setValue(config.PINBAR_SHADOW_RATIO)
        self._row_with_hint(f4, "Pinbar shadow ratio:", self.s_pinbar,
                            config.PINBAR_SHADOW_RATIO,
                            defaults.get("PINBAR_SHADOW_RATIO", 2.0))

        self.s_min_shadow = QDoubleSpinBox()
        self.s_min_shadow.setRange(0.01, 2); self.s_min_shadow.setDecimals(3); self.s_min_shadow.setSuffix(" %")
        self.s_min_shadow.setValue(config.MIN_SHADOW_PCT)
        self._row_with_hint(f4, "Мин. тень:", self.s_min_shadow,
                            config.MIN_SHADOW_PCT,
                            defaults.get("MIN_SHADOW_PCT", 0.15), " %")

        self.s_bounce = QCheckBox("Использовать bounce-сигнал")
        self.s_bounce.setChecked(config.USE_BOUNCE_SIGNAL)
        f4.addRow("", self.s_bounce)

        settings_layout.addWidget(g4)

        # ========== УРОВНИ ==========
        g5 = QGroupBox("📊 Уровни")
        f5 = QFormLayout(g5)
        f5.setSpacing(10)
        f5.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_cluster = QDoubleSpinBox()
        self.s_cluster.setRange(0.1, 5); self.s_cluster.setDecimals(2); self.s_cluster.setSuffix(" %")
        self.s_cluster.setValue(config.CLUSTER_PCT)
        self._row_with_hint(f5, "Кластер %:", self.s_cluster,
                            config.CLUSTER_PCT,
                            defaults.get("CLUSTER_PCT", 0.6), " %")

        self.s_min_touches = QSpinBox()
        self.s_min_touches.setRange(2, 20)
        self.s_min_touches.setValue(config.MIN_TOUCHES)
        self._row_with_hint(f5, "Мин. касаний:", self.s_min_touches,
                            config.MIN_TOUCHES,
                            defaults.get("MIN_TOUCHES", 4))

        self.s_max_age = QSpinBox()
        self.s_max_age.setRange(1, 365); self.s_max_age.setSuffix(" дн")
        self.s_max_age.setValue(config.MAX_LEVEL_AGE_DAYS)
        self._row_with_hint(f5, "Макс. возраст:", self.s_max_age,
                            config.MAX_LEVEL_AGE_DAYS,
                            defaults.get("MAX_LEVEL_AGE_DAYS", 21), " дн")

        self.s_lookback = QSpinBox()
        self.s_lookback.setRange(30, 365); self.s_lookback.setSuffix(" дн")
        self.s_lookback.setValue(config.LOOKBACK_DAYS)
        self._row_with_hint(f5, "Lookback:", self.s_lookback,
                            config.LOOKBACK_DAYS,
                            defaults.get("LOOKBACK_DAYS", 90), " дн")

        settings_layout.addWidget(g5)

        # ========== TRAILING ==========
        g6 = QGroupBox("📈 Trailing Stop")
        f6 = QFormLayout(g6)
        f6.setSpacing(10)
        f6.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_use_trailing = QCheckBox("Включён")
        self.s_use_trailing.setChecked(config.USE_TRAILING_STOP)
        f6.addRow("", self.s_use_trailing)

        self.s_trail_start = QDoubleSpinBox()
        self.s_trail_start.setRange(0.5, 20); self.s_trail_start.setDecimals(1); self.s_trail_start.setSuffix(" %")
        self.s_trail_start.setValue(config.TRAILING_START_PCT)
        self._row_with_hint(f6, "Start %:", self.s_trail_start,
                            config.TRAILING_START_PCT,
                            defaults.get("TRAILING_START_PCT", 4.0), " %")

        self.s_trail_step = QDoubleSpinBox()
        self.s_trail_step.setRange(0.1, 10); self.s_trail_step.setDecimals(1); self.s_trail_step.setSuffix(" %")
        self.s_trail_step.setValue(config.TRAILING_STEP_PCT)
        self._row_with_hint(f6, "Step %:", self.s_trail_step,
                            config.TRAILING_STEP_PCT,
                            defaults.get("TRAILING_STEP_PCT", 1.0), " %")

        self.s_trail_sec = QSpinBox()
        self.s_trail_sec.setRange(10, 600); self.s_trail_sec.setSuffix(" сек")
        self.s_trail_sec.setValue(config.TRAILING_UPDATE_SEC)
        self._row_with_hint(f6, "Обновление:", self.s_trail_sec,
                            config.TRAILING_UPDATE_SEC,
                            defaults.get("TRAILING_UPDATE_SEC", 60), " сек")

        settings_layout.addWidget(g6)

        # ========== MTF ==========
        g7 = QGroupBox("📊 Мульти-таймфрейм")
        f7 = QFormLayout(g7)
        f7.setSpacing(10)
        f7.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_use_mtf = QCheckBox("Включён")
        self.s_use_mtf.setChecked(config.USE_MULTI_TIMEFRAME)
        f7.addRow("", self.s_use_mtf)

        self.s_w_daily = QDoubleSpinBox()
        self.s_w_daily.setRange(0, 1); self.s_w_daily.setDecimals(2); self.s_w_daily.setSingleStep(0.05)
        self.s_w_daily.setValue(config.MTF_WEIGHT_DAILY)
        self._row_with_hint(f7, "Вес 1d:", self.s_w_daily,
                            config.MTF_WEIGHT_DAILY,
                            defaults.get("MTF_WEIGHT_DAILY", 0.4))

        self.s_w_4h = QDoubleSpinBox()
        self.s_w_4h.setRange(0, 1); self.s_w_4h.setDecimals(2); self.s_w_4h.setSingleStep(0.05)
        self.s_w_4h.setValue(config.MTF_WEIGHT_4H)
        self._row_with_hint(f7, "Вес 4h:", self.s_w_4h,
                            config.MTF_WEIGHT_4H,
                            defaults.get("MTF_WEIGHT_4H", 0.3))

        self.s_w_15m = QDoubleSpinBox()
        self.s_w_15m.setRange(0, 1); self.s_w_15m.setDecimals(2); self.s_w_15m.setSingleStep(0.05)
        self.s_w_15m.setValue(config.MTF_WEIGHT_15M)
        self._row_with_hint(f7, "Вес 15m:", self.s_w_15m,
                            config.MTF_WEIGHT_15M,
                            defaults.get("MTF_WEIGHT_15M", 0.3))

        settings_layout.addWidget(g7)

        # ========== АДАПТИВНЫЙ РАЗМЕР ==========
        g8 = QGroupBox("📏 Адаптивный размер")
        f8 = QFormLayout(g8)
        f8.setSpacing(10)
        f8.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_use_adaptive = QCheckBox("Включён")
        self.s_use_adaptive.setChecked(config.USE_ADAPTIVE_SIZE)
        f8.addRow("", self.s_use_adaptive)

        self.s_atr_low = QDoubleSpinBox()
        self.s_atr_low.setRange(1, 30); self.s_atr_low.setDecimals(1); self.s_atr_low.setSuffix(" %")
        self.s_atr_low.setValue(config.ADAPTIVE_ATR_LOW)
        self._row_with_hint(f8, "ATR Low %:", self.s_atr_low,
                            config.ADAPTIVE_ATR_LOW,
                            defaults.get("ADAPTIVE_ATR_LOW", 5.0), " %")

        self.s_atr_high = QDoubleSpinBox()
        self.s_atr_high.setRange(1, 50); self.s_atr_high.setDecimals(1); self.s_atr_high.setSuffix(" %")
        self.s_atr_high.setValue(config.ADAPTIVE_ATR_HIGH)
        self._row_with_hint(f8, "ATR High %:", self.s_atr_high,
                            config.ADAPTIVE_ATR_HIGH,
                            defaults.get("ADAPTIVE_ATR_HIGH", 12.0), " %")

        self.s_size_min_pct = QDoubleSpinBox()
        self.s_size_min_pct.setRange(0.5, 20); self.s_size_min_pct.setDecimals(1); self.s_size_min_pct.setSuffix(" %")
        self.s_size_min_pct.setValue(config.ADAPTIVE_SIZE_MIN_PCT)
        self._row_with_hint(f8, "Min %:", self.s_size_min_pct,
                            config.ADAPTIVE_SIZE_MIN_PCT,
                            defaults.get("ADAPTIVE_SIZE_MIN_PCT", 3.0), " %")

        self.s_size_max_pct = QDoubleSpinBox()
        self.s_size_max_pct.setRange(0.5, 30); self.s_size_max_pct.setDecimals(1); self.s_size_max_pct.setSuffix(" %")
        self.s_size_max_pct.setValue(config.ADAPTIVE_SIZE_MAX_PCT)
        self._row_with_hint(f8, "Max %:", self.s_size_max_pct,
                            config.ADAPTIVE_SIZE_MAX_PCT,
                            defaults.get("ADAPTIVE_SIZE_MAX_PCT", 8.0), " %")

        settings_layout.addWidget(g8)

        # ========== ПИРАМИДИНГ ==========
        g9 = QGroupBox("🎲 Пирамидинг")
        f9 = QFormLayout(g9)
        f9.setSpacing(10)
        f9.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_use_pyramid = QCheckBox("Включён (ОПАСНО)")
        self.s_use_pyramid.setChecked(config.USE_PYRAMIDING)
        f9.addRow("", self.s_use_pyramid)

        self.s_pyr_start = QDoubleSpinBox()
        self.s_pyr_start.setRange(0.5, 20); self.s_pyr_start.setDecimals(1); self.s_pyr_start.setSuffix(" %")
        self.s_pyr_start.setValue(config.PYRAMID_START_PCT)
        self._row_with_hint(f9, "Start %:", self.s_pyr_start,
                            config.PYRAMID_START_PCT,
                            defaults.get("PYRAMID_START_PCT", 2.0), " %")

        self.s_pyr_step = QDoubleSpinBox()
        self.s_pyr_step.setRange(0.5, 20); self.s_pyr_step.setDecimals(1); self.s_pyr_step.setSuffix(" %")
        self.s_pyr_step.setValue(config.PYRAMID_STEP_PCT)
        self._row_with_hint(f9, "Step %:", self.s_pyr_step,
                            config.PYRAMID_STEP_PCT,
                            defaults.get("PYRAMID_STEP_PCT", 2.0), " %")

        self.s_pyr_max = QSpinBox()
        self.s_pyr_max.setRange(1, 5)
        self.s_pyr_max.setValue(config.PYRAMID_MAX_ADD)
        self._row_with_hint(f9, "Max add:", self.s_pyr_max,
                            config.PYRAMID_MAX_ADD,
                            defaults.get("PYRAMID_MAX_ADD", 2))

        settings_layout.addWidget(g9)

        # ========== ХЕДЖ ==========
        g10 = QGroupBox("🛡 Хеджирование")
        f10 = QFormLayout(g10)
        f10.setSpacing(10)
        f10.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_use_hedge = QCheckBox("Включён (ОПАСНО)")
        self.s_use_hedge.setChecked(config.USE_HEDGING)
        f10.addRow("", self.s_use_hedge)

        self.s_hedge_trigger = QDoubleSpinBox()
        self.s_hedge_trigger.setRange(-20, 0); self.s_hedge_trigger.setDecimals(1); self.s_hedge_trigger.setSuffix(" %")
        self.s_hedge_trigger.setValue(config.HEDGE_TRIGGER_PCT)
        self._row_with_hint(f10, "Trigger %:", self.s_hedge_trigger,
                            config.HEDGE_TRIGGER_PCT,
                            defaults.get("HEDGE_TRIGGER_PCT", -2.5), " %")

        self.s_hedge_ratio = QDoubleSpinBox()
        self.s_hedge_ratio.setRange(0.1, 1.0); self.s_hedge_ratio.setDecimals(2); self.s_hedge_ratio.setSingleStep(0.1)
        self.s_hedge_ratio.setValue(config.HEDGE_SIZE_RATIO)
        self._row_with_hint(f10, "Size ratio:", self.s_hedge_ratio,
                            config.HEDGE_SIZE_RATIO,
                            defaults.get("HEDGE_SIZE_RATIO", 0.5))

        settings_layout.addWidget(g10)

        # ========== УПРАВЛЕНИЕ МОНЕТАМИ ==========
        g11 = QGroupBox("🪙 Управление монетами")
        f11 = QFormLayout(g11)
        f11.setSpacing(10)
        f11.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_auto_manage = QCheckBox("Автоуправление включено")
        self.s_auto_manage.setChecked(config.AUTO_MANAGE_COINS)
        f11.addRow("", self.s_auto_manage)

        self.s_coin_hours = QSpinBox()
        self.s_coin_hours.setRange(1, 72); self.s_coin_hours.setSuffix(" ч")
        self.s_coin_hours.setValue(config.COIN_ANALYSIS_HOURS)
        self._row_with_hint(f11, "Интервал анализа:", self.s_coin_hours,
                            config.COIN_ANALYSIS_HOURS,
                            defaults.get("COIN_ANALYSIS_HOURS", 6), " ч")

        self.s_coin_min_trades = QSpinBox()
        self.s_coin_min_trades.setRange(1, 100)
        self.s_coin_min_trades.setValue(config.COIN_MIN_TRADES)
        self._row_with_hint(f11, "Мин. сделок:", self.s_coin_min_trades,
                            config.COIN_MIN_TRADES,
                            defaults.get("COIN_MIN_TRADES", 5))

        self.s_coin_min_pnl = QDoubleSpinBox()
        self.s_coin_min_pnl.setRange(-50, 0); self.s_coin_min_pnl.setDecimals(1); self.s_coin_min_pnl.setSuffix(" %")
        self.s_coin_min_pnl.setValue(config.COIN_MIN_PNL_PCT)
        self._row_with_hint(f11, "Мин. P&L:", self.s_coin_min_pnl,
                            config.COIN_MIN_PNL_PCT,
                            defaults.get("COIN_MIN_PNL_PCT", -3.0), " %")

        self.s_coin_losses = QSpinBox()
        self.s_coin_losses.setRange(1, 10)
        self.s_coin_losses.setValue(config.COIN_CONSECUTIVE_LOSSES)
        self._row_with_hint(f11, "Убытков подряд:", self.s_coin_losses,
                            config.COIN_CONSECUTIVE_LOSSES,
                            defaults.get("COIN_CONSECUTIVE_LOSSES", 2))

        settings_layout.addWidget(g11)

        # ========== ИЗДЕРЖКИ ==========
        g12 = QGroupBox("💸 Издержки")
        f12 = QFormLayout(g12)
        f12.setSpacing(10)
        f12.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.s_commission = QDoubleSpinBox()
        self.s_commission.setRange(0, 1); self.s_commission.setDecimals(3); self.s_commission.setSuffix(" %")
        self.s_commission.setValue(config.COMMISSION_PCT)
        self._row_with_hint(f12, "Комиссия (1 сторона):", self.s_commission,
                            config.COMMISSION_PCT,
                            defaults.get("COMMISSION_PCT", 0.055), " %")

        self.s_slippage = QDoubleSpinBox()
        self.s_slippage.setRange(0, 1); self.s_slippage.setDecimals(3); self.s_slippage.setSuffix(" %")
        self.s_slippage.setValue(config.SLIPPAGE_PCT)
        self._row_with_hint(f12, "Слиппедж:", self.s_slippage,
                            config.SLIPPAGE_PCT,
                            defaults.get("SLIPPAGE_PCT", 0.02), " %")

        settings_layout.addWidget(g12)

        # ========== СПИСОК МОНЕТ ==========
        g13 = QGroupBox("📋 Список монет (по одной на строку)")
        f13 = QVBoxLayout(g13)
        self.text_coins = QTextEdit()
        self.text_coins.setPlainText("\n".join(config.AUTO_SYMBOLS))
        self.text_coins.setMaximumHeight(160)
        self.text_coins.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Palette.BG_MAIN};
                color: {Palette.TEXT_MAIN};
                font-family: 'Consolas', monospace;
                font-size: 13px;
                border: 1px solid {Palette.BORDER};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        f13.addWidget(self.text_coins)
        settings_layout.addWidget(g13)

        # ========== КНОПКИ ==========
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_save_settings = QPushButton("💾  СОХРАНИТЬ В CONFIG")
        self.btn_save_settings.setStyleSheet(self._btn_style(Palette.GREEN_DARK, Palette.GREEN))
        self.btn_save_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_settings.clicked.connect(self.on_save_settings)
        btns.addWidget(self.btn_save_settings)

        self.btn_reset_settings = QPushButton("↺  СБРОСИТЬ К СТАНДАРТУ")
        self.btn_reset_settings.setStyleSheet(self._btn_style(Palette.NEUTRAL_DK, Palette.NEUTRAL))
        self.btn_reset_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_settings.clicked.connect(self.on_reset_settings)
        btns.addWidget(self.btn_reset_settings)

        self.btn_save_defaults = QPushButton("📌  СДЕЛАТЬ ЭТАЛОНОМ")
        self.btn_save_defaults.setStyleSheet(self._btn_style(Palette.BLUE_DARK, Palette.BLUE))
        self.btn_save_defaults.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_defaults.clicked.connect(self.on_save_as_default)
        btns.addWidget(self.btn_save_defaults)

        self.btn_refresh_coins = QPushButton("🔄  АВТОПОДБОР МОНЕТ")
        self.btn_refresh_coins.setStyleSheet(self._btn_style(Palette.TEAL_DARK, Palette.TEAL))
        self.btn_refresh_coins.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_coins.clicked.connect(self.on_refresh_coins)
        btns.addWidget(self.btn_refresh_coins)

        btns.addStretch()
        settings_layout.addLayout(btns)
        settings_layout.addStretch()

        scroll.setWidget(scroll_content)
        settings_outer.addWidget(scroll)

        self.tabs.addTab(tab_settings, "⚙  Настройки")

    # ============================================================
    # ВКЛАДКА: API
    # ============================================================
    def _build_tab_api(self):
        tab_api = QWidget()
        api_layout = QVBoxLayout(tab_api)
        api_layout.setContentsMargins(12, 12, 12, 12)
        api_layout.setSpacing(12)

        info_label = QLabel("🔑  API-ключи Bybit\n\nbybit.com → Профиль → API")
        info_label.setStyleSheet(f"""
            QLabel {{
                background-color: {Palette.BG_PANEL};
                color: {Palette.TEXT_MAIN};
                font-size: 13px;
                padding: 16px;
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
            }}
        """)
        api_layout.addWidget(info_label)

        api_form = QFormLayout()
        api_form.setSpacing(12)
        api_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.input_api_key = QLineEdit()
        self.input_api_key.setPlaceholderText("API Key")
        api_form.addRow("API Key:", self.input_api_key)

        self.input_api_secret = QLineEdit()
        self.input_api_secret.setPlaceholderText("API Secret")
        self.input_api_secret.setEchoMode(QLineEdit.EchoMode.Password)
        api_form.addRow("API Secret:", self.input_api_secret)

        self.chk_testnet = QCheckBox("Testnet")
        api_form.addRow("", self.chk_testnet)
        api_layout.addLayout(api_form)

        api_btns = QHBoxLayout()
        api_btns.setSpacing(8)

        self.btn_test_api = QPushButton("🔍  ПРОВЕРИТЬ")
        self.btn_test_api.setStyleSheet(self._btn_style(Palette.BLUE_DARK, Palette.BLUE))
        self.btn_test_api.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_api.clicked.connect(self.on_test_api)
        api_btns.addWidget(self.btn_test_api)

        self.btn_save_api = QPushButton("💾  СОХРАНИТЬ")
        self.btn_save_api.setStyleSheet(self._btn_style(Palette.GREEN_DARK, Palette.GREEN))
        self.btn_save_api.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_api.clicked.connect(self.on_save_api)
        api_btns.addWidget(self.btn_save_api)

        api_btns.addStretch()
        api_layout.addLayout(api_btns)

        self.lbl_api_status = QLabel("Статус: неизвестно")
        self.lbl_api_status.setStyleSheet(f"""
            QLabel {{
                background-color: {Palette.BG_PANEL};
                color: {Palette.TEXT_MAIN};
                font-size: 13px;
                padding: 16px;
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
            }}
        """)
        self.lbl_api_status.setWordWrap(True)
        api_layout.addWidget(self.lbl_api_status)
        api_layout.addStretch()

        self.tabs.addTab(tab_api, "🔑  API")

    # ============================================================
    # ВКЛАДКА: БЭКТЕСТ (запуск + результаты)
    # ============================================================
    def _build_tab_backtest(self):
        tab_backtest = QWidget()
        backtest_layout = QVBoxLayout(tab_backtest)
        backtest_layout.setContentsMargins(12, 12, 12, 12)
        backtest_layout.setSpacing(10)

        bt_top = QHBoxLayout()
        bt_top.setSpacing(8)
        bt_top.addWidget(QLabel("Период (дн):"))

        self.combo_period = QComboBox()
        for d in [7, 14, 21, 28]:
            self.combo_period.addItem(f"{d} дней", d)
        self.combo_period.setCurrentIndex(1)
        bt_top.addWidget(self.combo_period)

        self.btn_run_backtest = QPushButton("▶  ЗАПУСТИТЬ")
        self.btn_run_backtest.setStyleSheet(self._btn_style(Palette.PURPLE_DARK, Palette.PURPLE))
        self.btn_run_backtest.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_backtest.clicked.connect(self.on_backtest)
        bt_top.addWidget(self.btn_run_backtest)

        self.lbl_backtest_status = QLabel("Не запускался")
        self.lbl_backtest_status.setStyleSheet(f"color: {Palette.TEXT_DIM}; padding: 5px;")
        bt_top.addWidget(self.lbl_backtest_status)
        bt_top.addStretch()

        self.btn_cancel_backtest = QPushButton("⏹  ОТМЕНА")
        self.btn_cancel_backtest.setStyleSheet(self._btn_style("#8B0000", Palette.RED))
        self.btn_cancel_backtest.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel_backtest.clicked.connect(self.on_cancel_backtest)
        self.btn_cancel_backtest.setEnabled(False)
        bt_top.addWidget(self.btn_cancel_backtest)

        backtest_layout.addLayout(bt_top)

        self.progress_backtest = QProgressBar()
        self.progress_backtest.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
                background-color: {Palette.BG_MAIN};
                color: {Palette.TEXT_MAIN};
                text-align: center;
                height: 26px;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {Palette.GREEN};
                border-radius: 7px;
            }}
        """)
        self.progress_backtest.setValue(0)
        backtest_layout.addWidget(self.progress_backtest)

        self.table_backtest = QTableWidget()
        self.table_backtest.setColumnCount(7)
        self.table_backtest.setHorizontalHeaderLabels([
            "Монета", "Сделок", "Winrate", "P&L", "Gross", "PF", "DD"
        ])
        bh = self.table_backtest.horizontalHeader()
        for i in range(7):
            bh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.table_backtest.verticalHeader().setDefaultSectionSize(32)
        self.table_backtest.setAlternatingRowColors(True)
        self.table_backtest.setShowGrid(False)
        backtest_layout.addWidget(self.table_backtest)

        self.lbl_backtest_summary = QLabel("Нажмите «ЗАПУСТИТЬ»")
        self.lbl_backtest_summary.setStyleSheet(f"""
            QLabel {{
                background-color: {Palette.BG_PANEL};
                color: {Palette.TEXT_MAIN};
                font-family: 'Consolas', monospace;
                font-size: 13px;
                padding: 16px;
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
            }}
        """)
        self.lbl_backtest_summary.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_backtest_summary.setWordWrap(True)
        backtest_layout.addWidget(self.lbl_backtest_summary)

        self.tabs.addTab(tab_backtest, "📊  Бэктест")

    # ============================================================
    # ВКЛАДКА: НАСТРОЙКИ БЭКТЕСТА
    # ============================================================
    def _build_tab_bt_settings(self, defaults):
        tab_bt = QWidget()
        bt_outer = QVBoxLayout(tab_bt)
        bt_outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(14)
        lay.setContentsMargins(12, 12, 12, 12)

        # ---- Период ----
        period_group = QGroupBox("📅 Период бэктеста")
        period_layout = QHBoxLayout(period_group)
        period_layout.setSpacing(12)

        self.bt_period_checks = {}
        for days in [7, 14, 21, 28]:
            chk = QCheckBox(f"{days} дней")
            chk.setChecked(days == 14)
            self.bt_period_checks[days] = chk
            period_layout.addWidget(chk)

        period_layout.addWidget(QLabel("Свой:"))

        self.bt_custom_chk = QCheckBox("исп.")
        self.bt_custom_chk.toggled.connect(
            lambda on: self.bt_custom_days.setEnabled(on)
        )
        period_layout.addWidget(self.bt_custom_chk)

        self.bt_custom_days = QSpinBox()
        self.bt_custom_days.setRange(1, 365)
        self.bt_custom_days.setValue(14)
        self.bt_custom_days.setSuffix(" дн")
        self.bt_custom_days.setEnabled(False)
        period_layout.addWidget(self.bt_custom_days)

        period_layout.addStretch()
        lay.addWidget(period_group)

        # ---- Функции ----
        funcs_group = QGroupBox("⚙ Функции для теста")
        funcs_layout = QVBoxLayout(funcs_group)
        funcs_layout.setSpacing(10)

        # Адаптивный стоп
        self.bt_chk_adaptive_stop = QCheckBox("🎯  Адаптивный стоп по ATR")
        funcs_layout.addWidget(self.bt_chk_adaptive_stop)

        astop_row = QHBoxLayout()
        astop_row.setSpacing(8)
        astop_row.addWidget(QLabel("  Стоп × ATR:"))
        self.bt_stop_atr_mult = QDoubleSpinBox()
        self.bt_stop_atr_mult.setRange(0.1, 3.0); self.bt_stop_atr_mult.setDecimals(2); self.bt_stop_atr_mult.setSingleStep(0.1)
        self.bt_stop_atr_mult.setValue(defaults.get("ADAPTIVE_STOP_ATR_MULT", 0.6))
        astop_row.addWidget(self.bt_stop_atr_mult)

        astop_row.addWidget(QLabel("Тейк × ATR:"))
        self.bt_take_atr_mult = QDoubleSpinBox()
        self.bt_take_atr_mult.setRange(0.1, 5.0); self.bt_take_atr_mult.setDecimals(2); self.bt_take_atr_mult.setSingleStep(0.1)
        self.bt_take_atr_mult.setValue(defaults.get("ADAPTIVE_TAKE_ATR_MULT", 1.2))
        astop_row.addWidget(self.bt_take_atr_mult)

        astop_row.addStretch()
        funcs_layout.addLayout(astop_row)

        # MTF
        self.bt_chk_mtf = QCheckBox("📊  Мульти-таймфрейм (MTF)")
        funcs_layout.addWidget(self.bt_chk_mtf)

        mtf_row = QHBoxLayout()
        mtf_row.setSpacing(8)
        mtf_row.addWidget(QLabel("  Веса 1d/4h/15m:"))
        self.bt_w_daily = QDoubleSpinBox()
        self.bt_w_daily.setRange(0, 1); self.bt_w_daily.setDecimals(2); self.bt_w_daily.setSingleStep(0.05)
        self.bt_w_daily.setValue(defaults.get("MTF_WEIGHT_DAILY", 0.4))
        mtf_row.addWidget(self.bt_w_daily)

        self.bt_w_4h = QDoubleSpinBox()
        self.bt_w_4h.setRange(0, 1); self.bt_w_4h.setDecimals(2); self.bt_w_4h.setSingleStep(0.05)
        self.bt_w_4h.setValue(defaults.get("MTF_WEIGHT_4H", 0.3))
        mtf_row.addWidget(self.bt_w_4h)

        self.bt_w_15m = QDoubleSpinBox()
        self.bt_w_15m.setRange(0, 1); self.bt_w_15m.setDecimals(2); self.bt_w_15m.setSingleStep(0.05)
        self.bt_w_15m.setValue(defaults.get("MTF_WEIGHT_15M", 0.3))
        mtf_row.addWidget(self.bt_w_15m)

        mtf_row.addStretch()
        funcs_layout.addLayout(mtf_row)

        # Trailing
        self.bt_chk_trailing = QCheckBox("📈  Trailing Stop")
        funcs_layout.addWidget(self.bt_chk_trailing)

        trail_row = QHBoxLayout()
        trail_row.setSpacing(8)
        trail_row.addWidget(QLabel("  Start %:"))
        self.bt_trail_start = QDoubleSpinBox()
        self.bt_trail_start.setRange(0.5, 20); self.bt_trail_start.setDecimals(1)
        self.bt_trail_start.setValue(defaults.get("TRAILING_START_PCT", 4.0))
        trail_row.addWidget(self.bt_trail_start)

        trail_row.addWidget(QLabel("Step %:"))
        self.bt_trail_step = QDoubleSpinBox()
        self.bt_trail_step.setRange(0.1, 10); self.bt_trail_step.setDecimals(1)
        self.bt_trail_step.setValue(defaults.get("TRAILING_STEP_PCT", 1.0))
        trail_row.addWidget(self.bt_trail_step)

        trail_row.addStretch()
        funcs_layout.addLayout(trail_row)

        # Adaptive size
        self.bt_chk_adaptive = QCheckBox("📏  Адаптивный размер позиции")
        funcs_layout.addWidget(self.bt_chk_adaptive)

        adapt_row = QHBoxLayout()
        adapt_row.setSpacing(8)
        adapt_row.addWidget(QLabel("  ATR Low:"))
        self.bt_atr_low = QDoubleSpinBox()
        self.bt_atr_low.setRange(1, 30); self.bt_atr_low.setDecimals(1)
        self.bt_atr_low.setValue(defaults.get("ADAPTIVE_ATR_LOW", 5.0))
        adapt_row.addWidget(self.bt_atr_low)

        adapt_row.addWidget(QLabel("ATR High:"))
        self.bt_atr_high = QDoubleSpinBox()
        self.bt_atr_high.setRange(1, 50); self.bt_atr_high.setDecimals(1)
        self.bt_atr_high.setValue(defaults.get("ADAPTIVE_ATR_HIGH", 12.0))
        adapt_row.addWidget(self.bt_atr_high)

        adapt_row.addWidget(QLabel("Min %:"))
        self.bt_size_min = QDoubleSpinBox()
        self.bt_size_min.setRange(0.5, 20); self.bt_size_min.setDecimals(1)
        self.bt_size_min.setValue(defaults.get("ADAPTIVE_SIZE_MIN_PCT", 3.0))
        adapt_row.addWidget(self.bt_size_min)

        adapt_row.addWidget(QLabel("Max %:"))
        self.bt_size_max = QDoubleSpinBox()
        self.bt_size_max.setRange(0.5, 30); self.bt_size_max.setDecimals(1)
        self.bt_size_max.setValue(defaults.get("ADAPTIVE_SIZE_MAX_PCT", 8.0))
        adapt_row.addWidget(self.bt_size_max)

        adapt_row.addStretch()
        funcs_layout.addLayout(adapt_row)

        # Pyramiding
        self.bt_chk_pyramid = QCheckBox("🎲  Пирамидинг")
        funcs_layout.addWidget(self.bt_chk_pyramid)

        pyr_row = QHBoxLayout()
        pyr_row.setSpacing(8)
        pyr_row.addWidget(QLabel("  Start %:"))
        self.bt_pyr_start = QDoubleSpinBox()
        self.bt_pyr_start.setRange(0.5, 20); self.bt_pyr_start.setDecimals(1)
        self.bt_pyr_start.setValue(defaults.get("PYRAMID_START_PCT", 2.0))
        pyr_row.addWidget(self.bt_pyr_start)

        pyr_row.addWidget(QLabel("Max Add:"))
        self.bt_pyr_max = QSpinBox()
        self.bt_pyr_max.setRange(1, 5)
        self.bt_pyr_max.setValue(defaults.get("PYRAMID_MAX_ADD", 2))
        pyr_row.addWidget(self.bt_pyr_max)

        pyr_row.addStretch()
        funcs_layout.addLayout(pyr_row)

        # Hedging
        self.bt_chk_hedge = QCheckBox("🛡  Хеджирование")
        funcs_layout.addWidget(self.bt_chk_hedge)

        hedge_row = QHBoxLayout()
        hedge_row.setSpacing(8)
        hedge_row.addWidget(QLabel("  Trigger %:"))
        self.bt_hedge_trigger = QDoubleSpinBox()
        self.bt_hedge_trigger.setRange(-20, 0); self.bt_hedge_trigger.setDecimals(1)
        self.bt_hedge_trigger.setValue(defaults.get("HEDGE_TRIGGER_PCT", -2.5))
        hedge_row.addWidget(self.bt_hedge_trigger)

        hedge_row.addWidget(QLabel("Size Ratio:"))
        self.bt_hedge_ratio = QDoubleSpinBox()
        self.bt_hedge_ratio.setRange(0.1, 1.0); self.bt_hedge_ratio.setDecimals(2); self.bt_hedge_ratio.setSingleStep(0.1)
        self.bt_hedge_ratio.setValue(defaults.get("HEDGE_SIZE_RATIO", 0.5))
        hedge_row.addWidget(self.bt_hedge_ratio)

        hedge_row.addStretch()
        funcs_layout.addLayout(hedge_row)

        lay.addWidget(funcs_group)

        # ---- Режим запуска ----
        mode_group = QGroupBox("🎛 Режим запуска")
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(6)

        self.bt_mode_single = QCheckBox("Одиночный прогон (текущие настройки из формы выше)")
        self.bt_mode_single.setChecked(True)
        mode_layout.addWidget(self.bt_mode_single)

        self.bt_mode_compare = QCheckBox("A/B-сравнение: база + каждая функция по отдельности + всё вместе")
        mode_layout.addWidget(self.bt_mode_compare)

        lay.addWidget(mode_group)

        # ---- Кнопки ----
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_bt_run = QPushButton("▶  ЗАПУСТИТЬ ТЕСТ")
        self.btn_bt_run.setStyleSheet(self._btn_style(Palette.PURPLE_DARK, Palette.PURPLE))
        self.btn_bt_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bt_run.clicked.connect(self.on_run_backtest_from_settings)
        btns.addWidget(self.btn_bt_run)

        self.btn_bt_save = QPushButton("💾  СОХРАНИТЬ В CONFIG")
        self.btn_bt_save.setStyleSheet(self._btn_style(Palette.GREEN_DARK, Palette.GREEN))
        self.btn_bt_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bt_save.clicked.connect(self.on_save_backtest_settings)
        btns.addWidget(self.btn_bt_save)

        btns.addStretch()
        lay.addLayout(btns)
        lay.addStretch()

        scroll.setWidget(content)
        bt_outer.addWidget(scroll)

        self.tabs.addTab(tab_bt, "⚙  Бэктест-настройки")

    # ============================================================
    # ВКЛАДКА: СДЕЛКИ БЭКТЕСТА
    # ============================================================
    def _build_tab_bt_trades(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)

        title = QLabel("Список всех сделок из последнего бэктеста")
        title.setStyleSheet(f"font-size: 13px; padding: 8px; color: {Palette.TEXT_DIM};")
        lay.addWidget(title)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)
        filter_layout.addWidget(QLabel("Монета:"))

        self.combo_bt_symbol = QComboBox()
        self.combo_bt_symbol.addItem("Все", None)
        self.combo_bt_symbol.currentIndexChanged.connect(self.refresh_bt_trades)
        filter_layout.addWidget(self.combo_bt_symbol)

        filter_layout.addWidget(QLabel("Результат:"))

        self.combo_bt_result = QComboBox()
        self.combo_bt_result.addItem("Все", None)
        self.combo_bt_result.addItem("Прибыльные", "TAKE")
        self.combo_bt_result.addItem("Убыточные", "STOP")
        self.combo_bt_result.currentIndexChanged.connect(self.refresh_bt_trades)
        filter_layout.addWidget(self.combo_bt_result)

        filter_layout.addStretch()

        self.lbl_bt_count = QLabel("Сделок: 0")
        self.lbl_bt_count.setStyleSheet(f"font-size: 13px; color: {Palette.TEXT_DIM}; padding: 5px;")
        filter_layout.addWidget(self.lbl_bt_count)

        lay.addLayout(filter_layout)

        self.table_bt_trades = QTableWidget()
        self.table_bt_trades.setColumnCount(10)
        self.table_bt_trades.setHorizontalHeaderLabels([
            "#", "Дата", "Монета", "Сторона", "Вход", "Выход",
            "P&L %", "P&L $", "Причина", "Часы"
        ])
        hbt = self.table_bt_trades.horizontalHeader()
        for i in range(10):
            hbt.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hbt.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_bt_trades.verticalHeader().setDefaultSectionSize(28)
        self.table_bt_trades.setAlternatingRowColors(True)
        self.table_bt_trades.setShowGrid(False)

        lay.addWidget(self.table_bt_trades)

        export_bt = QHBoxLayout()
        self.btn_export_bt = QPushButton("📥  ЭКСПОРТ СДЕЛОК")
        self.btn_export_bt.setStyleSheet(self._btn_style(Palette.BLUE_DARK, Palette.BLUE))
        self.btn_export_bt.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_bt.clicked.connect(self.on_export_bt_trades)
        export_bt.addWidget(self.btn_export_bt)
        export_bt.addStretch()
        lay.addLayout(export_bt)

        self.tabs.addTab(tab, "📋  Сделки бэктеста")

    # ============================================================
    # ВКЛАДКА: СРАВНЕНИЕ ФУНКЦИЙ
    # ============================================================
    def _build_tab_compare(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)

        title = QLabel("A/B сравнение функций: ATR, MTF, Trailing, Адаптив, Пирамидинг, Хедж")
        title.setStyleSheet(f"font-size: 13px; padding: 8px; color: {Palette.TEXT_DIM};")
        lay.addWidget(title)

        cmp_top = QHBoxLayout()
        cmp_top.setSpacing(8)

        self.btn_run_compare = QPushButton("🔬  ЗАПУСТИТЬ СРАВНЕНИЕ")
        self.btn_run_compare.setStyleSheet(self._btn_style(Palette.PURPLE_DARK, Palette.PURPLE))
        self.btn_run_compare.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_compare.clicked.connect(self.on_run_compare_from_bt)
        cmp_top.addWidget(self.btn_run_compare)
        self.btn_run_entry_ab = QPushButton("🎯  A/B ТЕСТ ВХОДА")
        self.btn_run_entry_ab.setStyleSheet(self._btn_style(Palette.ORANGE_DARK, Palette.ORANGE))
        self.btn_run_entry_ab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_entry_ab.clicked.connect(self.on_run_entry_ab)
        cmp_top.addWidget(self.btn_run_entry_ab)

        self.lbl_compare_status = QLabel("Не запускалось")
        self.lbl_compare_status.setStyleSheet(f"color: {Palette.TEXT_DIM}; padding: 5px;")
        cmp_top.addWidget(self.lbl_compare_status)

        cmp_top.addStretch()
        lay.addLayout(cmp_top)

        self.table_compare = QTableWidget()
        self.table_compare.setColumnCount(7)
        self.table_compare.setHorizontalHeaderLabels([
            "Конфигурация", "Сделок", "Winrate", "P&L %", "P&L $", "PF", "DD %"
        ])
        hcmp = self.table_compare.horizontalHeader()
        for i in range(7):
            hcmp.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.table_compare.verticalHeader().setDefaultSectionSize(32)
        self.table_compare.setAlternatingRowColors(True)
        self.table_compare.setShowGrid(False)
        lay.addWidget(self.table_compare)

        self.lbl_compare_conclusion = QLabel("Нажмите «ЗАПУСТИТЬ СРАВНЕНИЕ» для анализа")
        self.lbl_compare_conclusion.setStyleSheet(f"""
            QLabel {{
                background-color: {Palette.BG_PANEL};
                color: {Palette.TEXT_MAIN};
                font-family: 'Consolas', monospace;
                font-size: 13px;
                padding: 16px;
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
            }}
        """)
        self.lbl_compare_conclusion.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.lbl_compare_conclusion.setWordWrap(True)
        lay.addWidget(self.lbl_compare_conclusion)

        self.tabs.addTab(tab, "🔬  Сравнение функций")

            # ============================================================
    # ВКЛАДКА: СОВЕТНИК
    # ============================================================
    def _build_tab_advisor(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        title = QLabel(
            "🧠 Автосоветник — анализирует накопленные сделки "
            "и предлагает улучшения стратегии"
        )
        title.setStyleSheet(f"font-size: 13px; padding: 8px; color: {Palette.TEXT_DIM};")
        title.setWordWrap(True)
        lay.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_refresh_advice = QPushButton("🔄  ОБНОВИТЬ СОВЕТЫ")
        self.btn_refresh_advice.setStyleSheet(self._btn_style(Palette.PURPLE_DARK, Palette.PURPLE))
        self.btn_refresh_advice.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_advice.clicked.connect(self.refresh_advisor)
        top.addWidget(self.btn_refresh_advice)

        self.btn_run_analyze = QPushButton("📊  ДЕТАЛЬНЫЙ АНАЛИЗ")
        self.btn_run_analyze.setStyleSheet(self._btn_style(Palette.TEAL_DARK, Palette.TEAL))
        self.btn_run_analyze.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_analyze.clicked.connect(self.on_run_detailed_analysis)
        top.addWidget(self.btn_run_analyze)

        self.btn_clear_signals = QPushButton("🗑  ОЧИСТИТЬ ЛОГ СИГНАЛОВ")
        self.btn_clear_signals.setStyleSheet(self._btn_style("#8B0000", Palette.RED))
        self.btn_clear_signals.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_signals.clicked.connect(self.on_clear_signals_log)
        top.addWidget(self.btn_clear_signals)

        top.addStretch()
        lay.addLayout(top)

        # Инфо-панель
        self.lbl_advisor_stats = QLabel("Загрузка...")
        self.lbl_advisor_stats.setStyleSheet(f"""
            QLabel {{
                background-color: {Palette.BG_PANEL};
                color: {Palette.TEXT_MAIN};
                font-family: 'Consolas', monospace;
                font-size: 13px;
                padding: 12px;
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
            }}
        """)
        self.lbl_advisor_stats.setWordWrap(True)
        lay.addWidget(self.lbl_advisor_stats)

        # Основной текст советов
        self.txt_advisor = QTextEdit()
        self.txt_advisor.setReadOnly(True)
        self.txt_advisor.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Palette.BG_PANEL};
                color: {Palette.TEXT_MAIN};
                font-family: 'Consolas', monospace;
                font-size: 13px;
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        lay.addWidget(self.txt_advisor)

        self.tabs.addTab(tab, "🧠  Советник")

    # ============================================================
    # ВКЛАДКА: СТРАТЕГИЯ
    # ============================================================
    def _build_tab_strategy(self):
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(14)
        lay.setContentsMargins(12, 12, 12, 12)

        # Инфо о текущей стратегии
        self.lbl_strategy_info = QLabel("")
        self.lbl_strategy_info.setStyleSheet(f"""
            QLabel {{
                background-color: {Palette.BG_PANEL};
                color: {Palette.TEXT_MAIN};
                font-size: 13px;
                padding: 12px;
                border: 1px solid {Palette.BORDER};
                border-radius: 8px;
            }}
        """)
        self.lbl_strategy_info.setWordWrap(True)
        lay.addWidget(self.lbl_strategy_info)

        # Параметры
        self.strategy_group = QGroupBox("Параметры стратегии")
        self.strategy_form = QFormLayout(self.strategy_group)
        self.strategy_form.setSpacing(10)
        self.strategy_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.strategy_group)

        # Кнопки
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_strategy_save = QPushButton("💾  СОХРАНИТЬ ПАРАМЕТРЫ")
        self.btn_strategy_save.setStyleSheet(self._btn_style(Palette.GREEN_DARK, Palette.GREEN))
        self.btn_strategy_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_strategy_save.clicked.connect(self.on_save_strategy_params)
        btns.addWidget(self.btn_strategy_save)

        self.btn_strategy_reload = QPushButton("↺  ПЕРЕЗАГРУЗИТЬ")
        self.btn_strategy_reload.setStyleSheet(self._btn_style(Palette.NEUTRAL_DK, Palette.NEUTRAL))
        self.btn_strategy_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_strategy_reload.clicked.connect(self._rebuild_strategy_params)
        btns.addWidget(self.btn_strategy_reload)

        btns.addStretch()
        lay.addLayout(btns)
        lay.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.strategy_params_widgets = {}
        self.tabs.addTab(tab, "🎯  Стратегия")

        # Первичная отрисовка
        self._rebuild_strategy_params()

    def _rebuild_strategy_params(self):
        """Строит форму параметров под текущую стратегию."""
        # Очистить
        while self.strategy_form.rowCount():
            self.strategy_form.removeRow(0)
        self.strategy_params_widgets.clear()

        key = self.combo_strategy.currentData()
        cls = STRATEGIES.get(key)
        if not cls:
            return

        # Инфо
        self.lbl_strategy_info.setText(
            f"Активная стратегия: <b>{cls.display_name}</b> "
            f"(<code>{cls.name}</code>)"
        )

        specs = cls.params_schema()
        if not specs:
            self.strategy_form.addRow(
                QLabel("У этой стратегии нет параметров в этой вкладке.\n"
                       "Все настройки — во вкладке «⚙ Настройки».")
            )
            return

        for spec in specs:
            pkey, label, typ, default, lo, hi, step = spec
            current = getattr(config, pkey, default)

            if typ == "float":
                w = QDoubleSpinBox()
                w.setRange(float(lo), float(hi))
                w.setSingleStep(float(step))
                w.setDecimals(4)
                w.setValue(float(current))
            elif typ == "int":
                w = QSpinBox()
                w.setRange(int(lo), int(hi))
                w.setValue(int(current))
            elif typ == "bool":
                w = QCheckBox()
                w.setChecked(bool(current))
            else:
                w = QLineEdit(str(current))

            self.strategy_form.addRow(label, w)
            self.strategy_params_widgets[pkey] = w

    def on_strategy_changed(self, idx):
        key = self.combo_strategy.currentData()
        cls = STRATEGIES.get(key)
        if not cls:
            return

        reply = QMessageBox.question(
            self, "Смена стратегии",
            f"Переключиться на «{cls.display_name}»?\n\n"
            f"Бот будет остановлен, настройки применены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            # откат селектора
            cur = getattr(config, 'ACTIVE_STRATEGY', 'classic_levels')
            i = self.combo_strategy.findData(cur)
            if i >= 0:
                self.combo_strategy.blockSignals(True)
                self.combo_strategy.setCurrentIndex(i)
                self.combo_strategy.blockSignals(False)
            return

        if self.bot.is_running:
            self.on_stop()

        # применяем в config и в боте
        config.ACTIVE_STRATEGY = key
        try:
            self.bot.set_strategy(key)
        except Exception as e:
            self.notify(f"Ошибка смены стратегии: {e}", "error")
            return

        # сохраняем в файл config.py
        try:
            self._update_config_file({'ACTIVE_STRATEGY': key}, config.AUTO_SYMBOLS)
        except Exception:
            pass

        self._rebuild_strategy_params()
        self.add_log(f"🎯 Стратегия: {cls.display_name}", Palette.PURPLE)
        self.notify(f"Стратегия «{cls.display_name}» активна", "success")

    def on_save_strategy_params(self):
        """Сохраняет параметры стратегии в config.py."""
        if not self.strategy_params_widgets:
            self.notify("Нет параметров для сохранения", "info")
            return

        values = {}
        for key, w in self.strategy_params_widgets.items():
            if isinstance(w, QDoubleSpinBox):
                values[key] = w.value()
            elif isinstance(w, QSpinBox):
                values[key] = w.value()
            elif isinstance(w, QCheckBox):
                values[key] = w.isChecked()
            else:
                values[key] = w.text()

        try:
            self._update_config_file(values, config.AUTO_SYMBOLS)
            for k, v in values.items():
                setattr(config, k, v)
            self.notify("Параметры стратегии сохранены в config.py", "success")
            self.add_log("💾 Параметры стратегии → config.py", Palette.GREEN)
        except Exception as e:
            self.notify(f"Ошибка сохранения: {e}", "error")

    def refresh_advisor(self):
        if not ADVISOR_AVAILABLE:
            self.notify("advisor.py не найден", "warning")
            return

        try:
            # Стата лога сигналов
            try:
                from signal_logger import stats as sig_stats
                s = sig_stats()
                stats_text = (
                    f"📊 Лог сигналов: всего {s['total']}, "
                    f"открыто {s['opened']}, закрыто {s['closed']}, "
                    f"отфильтровано {s['not_opened']}"
                )
            except Exception:
                stats_text = "📊 Лог сигналов: недоступен"

            self.lbl_advisor_stats.setText(stats_text)

            # Советы
            advice = get_advice()
            text = format_advice(advice)
            self.txt_advisor.setPlainText(text)
        except Exception as e:
            self.txt_advisor.setPlainText(f"Ошибка: {e}")
            self.notify(str(e), "error")

    def on_run_detailed_analysis(self):
        """Запускает analyze_entries.py как отдельный процесс — вывод в консоль."""
        import subprocess
        import sys as _sys

        try:
            result = subprocess.run(
                [_sys.executable, "analyze_entries.py"],
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )
            output = result.stdout or ""
            if result.stderr:
                output += "\n\n[stderr]\n" + result.stderr

            self.txt_advisor.setPlainText(output)
            self.notify("Анализ завершён (см. панель ниже)", "success")
        except Exception as e:
            self.notify(f"Ошибка анализа: {e}", "error")

    def on_clear_signals_log(self):
        reply = QMessageBox.question(
            self, "Очистить",
            "Удалить весь лог сигналов (signals_log.json)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from signal_logger import clear_signals
            clear_signals()
            self.notify("Лог сигналов очищен", "success")
            self.refresh_advisor()
        except Exception as e:
            self.notify(str(e), "error")
    # ============================================================
    # ЛОГ
    # ============================================================
    def add_log(self, msg, color=None):
        timestamp = datetime.now().strftime("%H:%M:%S")

        if color is None:
            msg_lower = msg.lower()
            if any(k in msg_lower for k in ['✅', 'открыта', 'прибыль', 'p&l +']):
                color = Palette.GREEN
            elif any(k in msg_lower for k in ['❌', 'ошибка', 'убыток', 'стоп']):
                color = Palette.RED
            elif any(k in msg_lower for k in ['⚠', 'предупреждение', 'пропуск']):
                color = Palette.ORANGE
            elif any(k in msg_lower for k in ['🔔', 'сигнал', 'mtf']):
                color = Palette.BLUE
            elif any(k in msg_lower for k in ['🏁', 'закрыта']):
                color = Palette.PURPLE
            elif '📐' in msg_lower:
                color = Palette.TEAL
            else:
                color = Palette.TEXT_MAIN

        html = f'<span style="color: #666;">[{timestamp}]</span> '
        html += f'<span style="color: {color};">{msg}</span>'
        self.log.append(html)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

        if '🏁' in msg and ('закрыта' in msg.lower() or 'P&L' in msg):
            if getattr(config, 'SOUND_ON_SIGNAL', True):
                try:
                    QApplication.beep()
                    QTimer.singleShot(200, lambda: QApplication.beep())
                    QTimer.singleShot(400, lambda: QApplication.beep())
                except Exception:
                    pass

        if '✅ Открыта' in msg:
            if getattr(config, 'SOUND_ON_SIGNAL', True):
                try:
                    QApplication.beep()
                except Exception:
                    pass

    # ============================================================
    # ОТЧЁТЫ / HEATMAP / КАЛЕНДАРЬ
    # ============================================================
    def on_show_report(self):
        if not self.reporter:
            self.notify("report_manager.py не найден", "warning")
            return
        report = self.reporter.get_daily_report()
        text = self.reporter.format_report_text(report)
        QMessageBox.information(self, "Дневной отчёт", text)

    def on_report(self, text):
        self.add_log("📊 Отчёт отправлен", Palette.GREEN)
        self.notify("Дневной отчёт готов", "info")

    def refresh_heatmap(self):
        if not self.reporter:
            return
        try:
            hm = self.reporter.get_heatmap()
            items = list(hm.items())
            self.table_heatmap.setRowCount(len(items))
            for i, (sym, data) in enumerate(items):
                pnl_usd = data['pnl_usd']
                pnl_pct = data['pnl_pct']

                row_bg = QColor(30, 60, 30) if pnl_usd > 0 else QColor(60, 25, 25)

                row_items = [
                    QTableWidgetItem(sym),
                    QTableWidgetItem(str(data['trades'])),
                    QTableWidgetItem(str(data['wins'])),
                    QTableWidgetItem(f"${pnl_usd:+.2f}"),
                    QTableWidgetItem(f"{pnl_pct:+.2f}%"),
                ]

                for j, it in enumerate(row_items):
                    it.setBackground(row_bg)
                    self.table_heatmap.setItem(i, j, it)

                for j in (3, 4):
                    it = self.table_heatmap.item(i, j)
                    it.setForeground(QColor(Palette.GREEN if pnl_usd > 0 else Palette.RED))
                    f = QFont(); f.setBold(True); it.setFont(f)
        except Exception as e:
            self.add_log(f"⚠ Heatmap: {str(e)[:60]}", Palette.ORANGE)

    def refresh_calendar(self):
        if not self.reporter:
            return
        try:
            while self.calendar_grid.count():
                item = self.calendar_grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            cal = self.reporter.get_calendar(getattr(config, 'CALENDAR_DAYS', 30))

            if not cal:
                label = QLabel("📅  Нет данных за последние 30 дней")
                label.setStyleSheet(f"font-size: 14px; padding: 20px; color: {Palette.TEXT_DIM};")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.calendar_grid.addWidget(label, 0, 0, 1, 7)
                return

            headers = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
            for i, h in enumerate(headers):
                lbl = QLabel(h)
                lbl.setStyleSheet(
                    f"font-weight: 700; padding: 8px; "
                    f"background-color: {Palette.BG_PANEL}; "
                    f"color: {Palette.TEXT_DIM}; border-radius: 6px;"
                )
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.calendar_grid.addWidget(lbl, 0, i)

            sorted_days = sorted(cal.items())
            row = 1
            col = 0

            for day, data in sorted_days:
                pnl = data['pnl_usd']
                trades = data['trades']

                text = f"{day[-5:]}\n${pnl:+.2f}\n({trades})"
                lbl = QLabel(text)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setMinimumHeight(70)

                if pnl > 0:
                    lbl.setStyleSheet(
                        f"background-color: {Palette.GREEN_DARK}; color: white; "
                        f"padding: 10px; border-radius: 8px; font-weight: 700;"
                    )
                elif pnl < 0:
                    lbl.setStyleSheet(
                        f"background-color: {Palette.RED_DARK}; color: white; "
                        f"padding: 10px; border-radius: 8px; font-weight: 700;"
                    )
                else:
                    lbl.setStyleSheet(
                        f"background-color: {Palette.BG_PANEL}; color: {Palette.TEXT_DIM}; "
                        f"padding: 10px; border-radius: 8px;"
                    )

                self.calendar_grid.addWidget(lbl, row, col)

                col += 1
                if col > 6:
                    col = 0
                    row += 1
        except Exception as e:
            self.add_log(f"⚠ Календарь: {str(e)[:60]}", Palette.ORANGE)

    # ============================================================
    # СИНХРОНИЗАЦИЯ С БИРЖЕЙ
    # ============================================================
    def on_sync_positions(self):
        try:
            try:
                bal = check_connection(self.bot.trader.exchange)
                self.lbl_balance.setText(f"💰  ${bal['total']:.2f}")
                self.status_balance.setText(f"💰  ${bal['total']:.2f}")
                self.on_balance(bal)

                eq = get_equity(self.bot.trader.exchange)
                if eq:
                    self.lbl_equity.setText(f"Equity: ${eq['equity']:.2f}")
                    unreal = eq['unrealized_pnl']
                    color = Palette.GREEN if unreal >= 0 else Palette.RED
                    self.lbl_unrealized.setText(f"Нереализ: ${unreal:+.2f}")
                    self.lbl_unrealized.setStyleSheet(
                        f"font-size: 14px; color: {color}; border: none; background: transparent;"
                    )
                    if self.equity:
                        self.equity.add_point(bal['total'], unreal)
            except Exception:
                pass

            try:
                self.bot.check_closed_positions()
            except Exception:
                pass

            try:
                positions = self.bot.trader.get_positions_status()
                self.on_positions(positions)
            except Exception:
                pass

            self.refresh_history()
            self.refresh_stats()
            self.refresh_all_charts()
            self.refresh_heatmap()
            self.refresh_calendar()
        except Exception:
            pass

    # ============================================================
    # API
    # ============================================================
    def on_test_api(self):
        api_key = self.input_api_key.text().strip()
        api_secret = self.input_api_secret.text().strip()
        if not api_key or not api_secret:
            self.notify("Заполните поля API", "warning")
            return
        self.lbl_api_status.setText("🔍 Проверка...")
        QApplication.processEvents()
        ok, msg = test_api_keys(api_key, api_secret, self.chk_testnet.isChecked())
        self.lbl_api_status.setText(f"{'✅' if ok else '❌'}  {msg}")
        self.notify(msg, "success" if ok else "error")

    def on_save_api(self):
        api_key = self.input_api_key.text().strip()
        api_secret = self.input_api_secret.text().strip()
        if not api_key or not api_secret:
            self.notify("Заполните поля API", "warning")
            return
        try:
            with open('.env', 'w', encoding='utf-8') as f:
                f.write(f"BYBIT_API_KEY={api_key}\n")
                f.write(f"BYBIT_API_SECRET={api_secret}\n")
                f.write(f"BYBIT_TESTNET={'True' if self.chk_testnet.isChecked() else 'False'}\n")
            self.lbl_api_status.setText("✅  Сохранено. Перезапустите приложение.")
            self.notify("API-ключи сохранены. Перезапустите приложение.", "success", 5000)
            self.add_log("🔑 API обновлены", Palette.ORANGE)
        except Exception as e:
            self.notify(str(e), "error")

    # ============================================================
    # СОХРАНЕНИЕ НАСТРОЕК
    # ============================================================
    def on_save_settings(self):
        try:
            values = {
                'AUTO_POSITION_PCT': self.s_pct.value(),
                'AUTO_MAX_TRADES_PER_DAY': self.s_trades.value(),
                'AUTO_DAILY_STOP_PCT': self.s_stop.value(),
                'MAX_POSITIONS_TOTAL': self.s_positions.value(),
                'AUTO_CHECK_INTERVAL_SEC': self.s_interval.value(),
                'AUTO_MIN_POSITION_USD': self.s_min_size.value(),
                'AUTO_MAX_POSITION_USD': self.s_max_size.value(),
                'AUTO_MIN_FREE_BALANCE': self.s_min_balance.value(),
                'MAX_AUTO_LEVERAGE': self.s_max_lev.value(),
                'DEFAULT_LEVERAGE': self.s_def_lev.value(),
                'USE_AUTO_LEVERAGE': self.s_auto_lev.isChecked(),
                'STOP_PCT_CALM': self.s_stop_calm.value(),
                'TAKE_PCT_CALM': self.s_take_calm.value(),
                'COOLDOWN_MINUTES': self.s_cooldown.value(),
                # Адаптивный стоп
                'USE_ADAPTIVE_STOP': self.s_use_adaptive_stop.isChecked(),
                'ADAPTIVE_STOP_ATR_MULT': self.s_stop_atr_mult.value(),
                'ADAPTIVE_TAKE_ATR_MULT': self.s_take_atr_mult.value(),
                'ADAPTIVE_STOP_MIN_PCT': self.s_stop_atr_min.value(),
                'ADAPTIVE_STOP_MAX_PCT': self.s_stop_atr_max.value(),
                'ADAPTIVE_TAKE_MIN_PCT': self.s_take_atr_min.value(),
                'ADAPTIVE_TAKE_MAX_PCT': self.s_take_atr_max.value(),
                # Сигналы
                'NEAR_LEVEL_PCT': self.s_near.value(),
                'PINBAR_SHADOW_RATIO': self.s_pinbar.value(),
                'MIN_SHADOW_PCT': self.s_min_shadow.value(),
                'USE_BOUNCE_SIGNAL': self.s_bounce.isChecked(),
                # Уровни
                'CLUSTER_PCT': self.s_cluster.value(),
                'MIN_TOUCHES': self.s_min_touches.value(),
                'MAX_LEVEL_AGE_DAYS': self.s_max_age.value(),
                'LOOKBACK_DAYS': self.s_lookback.value(),
                # Trailing
                'USE_TRAILING_STOP': self.s_use_trailing.isChecked(),
                'TRAILING_START_PCT': self.s_trail_start.value(),
                'TRAILING_STEP_PCT': self.s_trail_step.value(),
                'TRAILING_UPDATE_SEC': self.s_trail_sec.value(),
                # MTF
                'USE_MULTI_TIMEFRAME': self.s_use_mtf.isChecked(),
                'MTF_WEIGHT_DAILY': self.s_w_daily.value(),
                'MTF_WEIGHT_4H': self.s_w_4h.value(),
                'MTF_WEIGHT_15M': self.s_w_15m.value(),
                # Adaptive size
                'USE_ADAPTIVE_SIZE': self.s_use_adaptive.isChecked(),
                'ADAPTIVE_ATR_LOW': self.s_atr_low.value(),
                'ADAPTIVE_ATR_HIGH': self.s_atr_high.value(),
                'ADAPTIVE_SIZE_MIN_PCT': self.s_size_min_pct.value(),
                'ADAPTIVE_SIZE_MAX_PCT': self.s_size_max_pct.value(),
                # Pyramid
                'USE_PYRAMIDING': self.s_use_pyramid.isChecked(),
                'PYRAMID_START_PCT': self.s_pyr_start.value(),
                'PYRAMID_STEP_PCT': self.s_pyr_step.value(),
                'PYRAMID_MAX_ADD': self.s_pyr_max.value(),
                # Hedge
                'USE_HEDGING': self.s_use_hedge.isChecked(),
                'HEDGE_TRIGGER_PCT': self.s_hedge_trigger.value(),
                'HEDGE_SIZE_RATIO': self.s_hedge_ratio.value(),
                # Coins
                'AUTO_MANAGE_COINS': self.s_auto_manage.isChecked(),
                'COIN_ANALYSIS_HOURS': self.s_coin_hours.value(),
                'COIN_MIN_TRADES': self.s_coin_min_trades.value(),
                'COIN_MIN_PNL_PCT': self.s_coin_min_pnl.value(),
                'COIN_CONSECUTIVE_LOSSES': self.s_coin_losses.value(),
                # Fees
                'COMMISSION_PCT': self.s_commission.value(),
                'SLIPPAGE_PCT': self.s_slippage.value(),
            }

            coins_raw = self.text_coins.toPlainText().strip()
            coins = [c.strip() for c in coins_raw.split('\n') if c.strip()]
            if not coins:
                self.notify("Список монет пуст", "warning")
                return
            for c in coins:
                if not re.match(r'^[A-Z0-9]+/USDT:USDT$', c):
                    self.notify(f"Неверный формат: {c}", "error")
                    return

            self._update_config_file(values, coins)
            for k, v in values.items():
                setattr(config, k, v)
            config.AUTO_SYMBOLS = coins

            self._refresh_hints_for_settings()
            self._sync_bt_settings_from_config()

            self.notify("Все настройки сохранены. Перезапустите автобот.", "success", 4000)
            self.add_log("💾 Настройки → config.py", Palette.GREEN)
        except Exception as e:
            self.notify(str(e), "error")

    def _refresh_hints_for_settings(self):
        """
        Обновляет кэш эталона. Подсказки «сейчас/стандарт» пересоздаются
        только при следующем открытии вкладки, чтобы не терять ссылки
        на виджеты (self.s_pct и т.д.).
        """
        try:
            self._defaults = {}
            self._load_defaults()
            self.add_log("↻ Кэш эталона обновлён", "#8A8A8A")
        except Exception as e:
            self.add_log(f"⚠ _refresh_hints: {str(e)[:80]}", "#FFB74D")

    def _sync_bt_settings_from_config(self):
        try:
            self.bt_chk_adaptive_stop.setChecked(getattr(config, 'USE_ADAPTIVE_STOP', True))
            self.bt_chk_mtf.setChecked(config.USE_MULTI_TIMEFRAME)
            self.bt_chk_trailing.setChecked(config.USE_TRAILING_STOP)
            self.bt_chk_adaptive.setChecked(config.USE_ADAPTIVE_SIZE)
            self.bt_chk_pyramid.setChecked(config.USE_PYRAMIDING)
            self.bt_chk_hedge.setChecked(config.USE_HEDGING)
        except Exception:
            pass

    def on_reset_settings(self):
        defaults = self._load_defaults()
        if not defaults:
            self.notify("defaults.json не найден", "warning")
            return

        reply = QMessageBox.question(
            self, "Сброс",
            "Сбросить все поля к стандартным настройкам?\n\n"
            "(config.py не изменится, пока вы не нажмёте «Сохранить»)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.s_pct.setValue(defaults.get("AUTO_POSITION_PCT", 5.0))
        self.s_trades.setValue(defaults.get("AUTO_MAX_TRADES_PER_DAY", 15))
        self.s_stop.setValue(defaults.get("AUTO_DAILY_STOP_PCT", 3.0))
        self.s_positions.setValue(defaults.get("MAX_POSITIONS_TOTAL", 4))
        self.s_interval.setValue(defaults.get("AUTO_CHECK_INTERVAL_SEC", 60))
        self.s_min_size.setValue(defaults.get("AUTO_MIN_POSITION_USD", 10))
        self.s_max_size.setValue(defaults.get("AUTO_MAX_POSITION_USD", 500))
        self.s_min_balance.setValue(defaults.get("AUTO_MIN_FREE_BALANCE", 50))
        self.s_max_lev.setValue(defaults.get("MAX_AUTO_LEVERAGE", 2.0))
        self.s_def_lev.setValue(defaults.get("DEFAULT_LEVERAGE", 2.0))
        self.s_auto_lev.setChecked(defaults.get("USE_AUTO_LEVERAGE", True))
        self.s_stop_calm.setValue(defaults.get("STOP_PCT_CALM", 2.5))
        self.s_take_calm.setValue(defaults.get("TAKE_PCT_CALM", 5.0))
        self.s_cooldown.setValue(defaults.get("COOLDOWN_MINUTES", 120))
        self.s_use_adaptive_stop.setChecked(defaults.get("USE_ADAPTIVE_STOP", True))
        self.s_stop_atr_mult.setValue(defaults.get("ADAPTIVE_STOP_ATR_MULT", 0.6))
        self.s_take_atr_mult.setValue(defaults.get("ADAPTIVE_TAKE_ATR_MULT", 1.2))
        self.s_stop_atr_min.setValue(defaults.get("ADAPTIVE_STOP_MIN_PCT", 1.5))
        self.s_stop_atr_max.setValue(defaults.get("ADAPTIVE_STOP_MAX_PCT", 8.0))
        self.s_take_atr_min.setValue(defaults.get("ADAPTIVE_TAKE_MIN_PCT", 3.0))
        self.s_take_atr_max.setValue(defaults.get("ADAPTIVE_TAKE_MAX_PCT", 16.0))
        self.s_near.setValue(defaults.get("NEAR_LEVEL_PCT", 0.8))
        self.s_pinbar.setValue(defaults.get("PINBAR_SHADOW_RATIO", 2.0))
        self.s_min_shadow.setValue(defaults.get("MIN_SHADOW_PCT", 0.15))
        self.s_bounce.setChecked(defaults.get("USE_BOUNCE_SIGNAL", True))
        self.s_cluster.setValue(defaults.get("CLUSTER_PCT", 0.6))
        self.s_min_touches.setValue(defaults.get("MIN_TOUCHES", 4))
        self.s_max_age.setValue(defaults.get("MAX_LEVEL_AGE_DAYS", 21))
        self.s_lookback.setValue(defaults.get("LOOKBACK_DAYS", 90))
        self.s_use_trailing.setChecked(defaults.get("USE_TRAILING_STOP", False))
        self.s_trail_start.setValue(defaults.get("TRAILING_START_PCT", 4.0))
        self.s_trail_step.setValue(defaults.get("TRAILING_STEP_PCT", 1.0))
        self.s_trail_sec.setValue(defaults.get("TRAILING_UPDATE_SEC", 60))
        self.s_use_mtf.setChecked(defaults.get("USE_MULTI_TIMEFRAME", False))
        self.s_w_daily.setValue(defaults.get("MTF_WEIGHT_DAILY", 0.4))
        self.s_w_4h.setValue(defaults.get("MTF_WEIGHT_4H", 0.3))
        self.s_w_15m.setValue(defaults.get("MTF_WEIGHT_15M", 0.3))
        self.s_use_adaptive.setChecked(defaults.get("USE_ADAPTIVE_SIZE", False))
        self.s_atr_low.setValue(defaults.get("ADAPTIVE_ATR_LOW", 5.0))
        self.s_atr_high.setValue(defaults.get("ADAPTIVE_ATR_HIGH", 12.0))
        self.s_size_min_pct.setValue(defaults.get("ADAPTIVE_SIZE_MIN_PCT", 3.0))
        self.s_size_max_pct.setValue(defaults.get("ADAPTIVE_SIZE_MAX_PCT", 8.0))
        self.s_use_pyramid.setChecked(defaults.get("USE_PYRAMIDING", False))
        self.s_pyr_start.setValue(defaults.get("PYRAMID_START_PCT", 2.0))
        self.s_pyr_step.setValue(defaults.get("PYRAMID_STEP_PCT", 2.0))
        self.s_pyr_max.setValue(defaults.get("PYRAMID_MAX_ADD", 2))
        self.s_use_hedge.setChecked(defaults.get("USE_HEDGING", False))
        self.s_hedge_trigger.setValue(defaults.get("HEDGE_TRIGGER_PCT", -2.5))
        self.s_hedge_ratio.setValue(defaults.get("HEDGE_SIZE_RATIO", 0.5))
        self.s_auto_manage.setChecked(defaults.get("AUTO_MANAGE_COINS", True))
        self.s_coin_hours.setValue(defaults.get("COIN_ANALYSIS_HOURS", 6))
        self.s_coin_min_trades.setValue(defaults.get("COIN_MIN_TRADES", 5))
        self.s_coin_min_pnl.setValue(defaults.get("COIN_MIN_PNL_PCT", -3.0))
        self.s_coin_losses.setValue(defaults.get("COIN_CONSECUTIVE_LOSSES", 2))
        self.s_commission.setValue(defaults.get("COMMISSION_PCT", 0.055))
        self.s_slippage.setValue(defaults.get("SLIPPAGE_PCT", 0.02))

        coins = defaults.get("AUTO_SYMBOLS", config.AUTO_SYMBOLS)
        self.text_coins.setPlainText("\n".join(coins))

        self.notify("Поля сброшены к стандартным. Нажмите «Сохранить» для применения.", "info", 4000)
        self.add_log("↺ Поля сброшены к стандартным", Palette.TEXT_DIM)

    def on_save_as_default(self):
        reply = QMessageBox.question(
            self, "Эталон",
            "Сделать ТЕКУЩИЕ настройки config.py эталонными?\n\n"
            "Файл defaults.json будет перезаписан. "
            "Кнопка «Сбросить» впредь будет возвращать к этим значениям.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            keys = [
                'AUTO_POSITION_PCT', 'AUTO_MAX_TRADES_PER_DAY', 'AUTO_DAILY_STOP_PCT',
                'MAX_POSITIONS_TOTAL', 'AUTO_CHECK_INTERVAL_SEC',
                'AUTO_MIN_POSITION_USD', 'AUTO_MAX_POSITION_USD', 'AUTO_MIN_FREE_BALANCE',
                'MAX_AUTO_LEVERAGE', 'DEFAULT_LEVERAGE', 'USE_AUTO_LEVERAGE',
                'STOP_PCT_CALM', 'TAKE_PCT_CALM', 'COOLDOWN_MINUTES',
                'USE_ADAPTIVE_STOP', 'ADAPTIVE_STOP_ATR_MULT', 'ADAPTIVE_TAKE_ATR_MULT',
                'ADAPTIVE_STOP_MIN_PCT', 'ADAPTIVE_STOP_MAX_PCT',
                'ADAPTIVE_TAKE_MIN_PCT', 'ADAPTIVE_TAKE_MAX_PCT',
                'NEAR_LEVEL_PCT', 'PINBAR_SHADOW_RATIO', 'MIN_SHADOW_PCT', 'USE_BOUNCE_SIGNAL',
                'CLUSTER_PCT', 'MIN_TOUCHES', 'MAX_LEVEL_AGE_DAYS', 'LOOKBACK_DAYS',
                'USE_TRAILING_STOP', 'TRAILING_START_PCT', 'TRAILING_STEP_PCT', 'TRAILING_UPDATE_SEC',
                'USE_MULTI_TIMEFRAME', 'MTF_WEIGHT_DAILY', 'MTF_WEIGHT_4H', 'MTF_WEIGHT_15M',
                'USE_ADAPTIVE_SIZE', 'ADAPTIVE_ATR_LOW', 'ADAPTIVE_ATR_HIGH',
                'ADAPTIVE_SIZE_MIN_PCT', 'ADAPTIVE_SIZE_MAX_PCT',
                'USE_PYRAMIDING', 'PYRAMID_START_PCT', 'PYRAMID_STEP_PCT', 'PYRAMID_MAX_ADD',
                'USE_HEDGING', 'HEDGE_TRIGGER_PCT', 'HEDGE_SIZE_RATIO',
                'AUTO_MANAGE_COINS', 'COIN_ANALYSIS_HOURS', 'COIN_MIN_TRADES',
                'COIN_MIN_PNL_PCT', 'COIN_CONSECUTIVE_LOSSES',
                'COMMISSION_PCT', 'SLIPPAGE_PCT',
            ]
            snapshot = {}
            for k in keys:
                snapshot[k] = getattr(config, k, None)
            snapshot['AUTO_SYMBOLS'] = list(config.AUTO_SYMBOLS)

            with open("defaults.json", "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)

            self._defaults = {}
            self._refresh_hints_for_settings()

            self.notify("Текущие настройки сохранены как эталон", "success")
            self.add_log("📌 defaults.json обновлён", Palette.GREEN)
        except Exception as e:
            self.notify(str(e), "error")

    def _update_config_file(self, values, coins):
        with open('config.py', 'r', encoding='utf-8') as f:
            content = f.read()

        for key, val in values.items():
            safe_key = re.escape(key)
            pattern = rf'^{safe_key}\s*=\s*[^\n]+'
            if isinstance(val, bool):
                new_line = f"{key} = {val}"
            elif isinstance(val, str):
                safe_val = str(val).replace("\\", "\\\\").replace("'", "\\'")
                new_line = f"{key} = '{safe_val}'"
            else:
                new_line = f"{key} = {val}"

            if re.search(pattern, content, flags=re.MULTILINE):
                content = re.sub(
                    pattern,
                    lambda m: new_line,
                    content,
                    flags=re.MULTILINE,
                )
            else:
                content += f"\n{new_line}\n"

        coins_block = "AUTO_SYMBOLS = [\n"
        for c in coins:
            coins_block += f"    '{c}',\n"
        coins_block += "]"

        content = re.sub(
            r'^AUTO_SYMBOLS\s*=\s*\[[^\]]*\]',
            coins_block, content,
            flags=re.MULTILINE | re.DOTALL
        )

        with open('config.py', 'w', encoding='utf-8') as f:
            f.write(content)

    # ============================================================
    # РУЧНОЕ ОТКРЫТИЕ / ГРАФИКИ
    # ============================================================
    def on_manual_open(self):
        from PyQt6.QtWidgets import QInputDialog
        symbols = config.AUTO_SYMBOLS
        symbol, ok = QInputDialog.getItem(self, "Открыть позицию", "Монета:", symbols, 0, False)
        if not ok:
            return
        side, ok = QInputDialog.getItem(self, "Открыть позицию", "Сторона:", ["LONG", "SHORT"], 0, False)
        if not ok:
            return

        try:
            self.add_log(f"▶ Ручное: {side} {symbol}...", Palette.PURPLE)
            ok, msg, pos = self.bot.trader.open_position(symbol, side)
            if ok:
                self.add_log(f"✅ {msg}", Palette.GREEN)
                self.notify(msg, "success")
                self.on_sync_positions()
            else:
                self.add_log(f"❌ {msg}", Palette.RED)
                self.notify(msg, "error")
        except Exception as e:
            self.notify(str(e), "error")

    def refresh_all_charts(self):
        try:
            self.update_price_chart()
            self.update_equity_chart()
        except Exception:
            pass

    def update_price_chart(self):
        if not CHART_AVAILABLE:
            return
        try:
            symbol = self.combo_chart_symbol.currentText()
            if not symbol:
                return
            raw = self.bot.trader.exchange.fetch_ohlcv(symbol, '15m', limit=100)
            import pandas as pd
            df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            levels = []
            if symbol in self.bot.levels_cache:
                levels = self.bot.levels_cache[symbol]['levels']
            positions = []
            if symbol in self.bot.trader.state.get('open_positions', {}):
                positions.append(self.bot.trader.state['open_positions'][symbol])
            self.price_chart.plot(df, levels, f"{symbol}", positions)
        except Exception:
            pass

    def update_equity_chart(self):
        if not CHART_AVAILABLE or not self.equity:
            return
        try:
            points = self.equity.get_points(days=30)
            self.equity_chart.plot(points)
        except Exception:
            pass

    # ============================================================
    # ИСТОРИЯ
    # ============================================================
    def refresh_history(self):
        try:
            history = self.bot.get_history(limit=200)
            self.table_history.setRowCount(len(history))
            for i, t in enumerate(history):
                ts = t.get('exit_ts', '')[:19].replace('T', ' ')
                pnl_pct = t.get('pnl_pct', 0)
                pnl_usd = t.get('pnl_usd', 0)

                if pnl_usd > 0:
                    row_bg = QColor(25, 55, 25)
                elif pnl_usd < 0:
                    row_bg = QColor(55, 25, 25)
                else:
                    row_bg = QColor(0, 0, 0, 0)

                row_items = [
                    QTableWidgetItem(ts),
                    QTableWidgetItem(t.get('symbol', '')),
                    QTableWidgetItem(t.get('side', '')),
                    QTableWidgetItem(f"{t.get('entry',0):.6f}"),
                    QTableWidgetItem(f"{t.get('exit',0):.6f}"),
                    QTableWidgetItem(f"${t.get('usd_size',0):.2f}"),
                    QTableWidgetItem(f"{pnl_pct:+.2f}%"),
                    QTableWidgetItem(f"${pnl_usd:+.2f}"),
                ]

                side_item = row_items[2]
                side_item.setForeground(QColor(Palette.GREEN if t.get('side') == 'LONG' else Palette.RED))
                f = QFont(); f.setBold(True); side_item.setFont(f)

                row_items[6].setForeground(QColor(Palette.GREEN if pnl_pct > 0 else Palette.RED))
                row_items[7].setForeground(QColor(Palette.GREEN if pnl_usd > 0 else Palette.RED))

                for j, it in enumerate(row_items):
                    it.setBackground(row_bg)
                    self.table_history.setItem(i, j, it)

                if i == 0:
                    emoji = "✅" if pnl_usd > 0 else "❌"
                    color = Palette.GREEN if pnl_usd > 0 else Palette.RED
                    self.lbl_last_trade.setText(
                        f"{emoji}  Последняя: {t.get('side','')} {t.get('symbol','')} → "
                        f"{pnl_pct:+.2f}% (${pnl_usd:+.2f})"
                    )
                    self.lbl_last_trade.setStyleSheet(
                        f"font-size: 13px; color: {color}; font-weight: 700; "
                        f"border: none; background: transparent;"
                    )
        except Exception:
            pass

    def on_export_csv(self):
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Экспорт истории",
                f"history_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "CSV (*.csv)"
            )
            if not filename:
                return
            history = self.bot.get_history(limit=10000)
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(['Дата', 'Монета', 'Сторона', 'Вход', 'Выход', 'Размер', 'P&L %', 'P&L $'])
                for t in history:
                    writer.writerow([
                        t.get('exit_ts', '')[:19],
                        t.get('symbol', ''), t.get('side', ''),
                        t.get('entry', 0), t.get('exit', 0),
                        t.get('usd_size', 0), t.get('pnl_pct', 0), t.get('pnl_usd', 0)
                    ])
            self.add_log(f"💾 {filename}", Palette.GREEN)
            self.notify("История экспортирована", "success")
        except Exception as e:
            self.notify(str(e), "error")

    def on_clear_history(self):
        reply = QMessageBox.question(
            self, "Очистить",
            "Удалить всю историю сделок?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.bot.trade_history = []
            self.bot._save_history()
            self.refresh_history()
            self.refresh_stats()
            self.add_log("🗑 История очищена", Palette.ORANGE)
            self.notify("История очищена", "info")
        except Exception as e:
            self.notify(str(e), "error")

    def refresh_stats(self):
        try:
            s7 = self.bot.get_stats(days=7)
            s30 = self.bot.get_stats(days=30)
            sall = self.bot.get_stats(days=3650)

            def fmt(s, label):
                if s['total'] == 0:
                    return f"── {label} ──\n  Нет сделок\n\n"
                return (f"── {label} ──\n"
                        f"  Сделок:      {s['total']}\n"
                        f"  Winrate:     {s['winrate']:.1f}% ({s['wins']}/{s['total']})\n"
                        f"  P&L:         {s['pnl_pct']:+.2f}%  (${s['pnl_usd']:+.2f})\n"
                        f"  Средний:     {s['avg']:+.2f}%\n"
                        f"  Лучшая:      {s['best']:+.2f}%\n"
                        f"  Худшая:      {s['worst']:+.2f}%\n\n")

            text = "════════════ ВСЁ ВРЕМЯ ════════════\n"
            text += fmt(sall, "Всего")
            text += "════════════ 30 ДНЕЙ ════════════\n"
            text += fmt(s30, "Месяц")
            text += "════════════ 7 ДНЕЙ ════════════\n"
            text += fmt(s7, "Неделя")

            if self.equity:
                st = self.equity.get_streaks()
                text += "════════════ СЕРИЯ ════════════\n"
                text += f"  Текущая:     {st['current']} {st['type']}\n"
                text += f"  Макс побед:  {st['max_win']}\n"
                text += f"  Макс убытков:{st['max_loss']}\n"

                eqs = self.equity.get_stats()
                if eqs['start'] > 0:
                    text += "\n════════════ EQUITY ════════════\n"
                    text += f"  Начало:      ${eqs['start']:.2f}\n"
                    text += f"  Сейчас:      ${eqs['current']:.2f}\n"
                    text += f"  Рост:        {eqs['total_growth_pct']:+.2f}%\n"
                    text += f"  Max DD:      ${eqs['max_dd']:.2f}\n"

            self.stats_label.setText(text)

            if self.equity:
                st = self.equity.get_streaks()
                self.lbl_streak.setText(f"Серия: {st['current']} {st['type']}")
        except Exception as e:
            self.stats_label.setText(f"Ошибка: {e}")

    # ============================================================
    # АВТОПОДБОР МОНЕТ
    # ============================================================
    def on_refresh_coins(self):
        if not SCANNER_AVAILABLE:
            self.notify("step7_coin_scanner.py не найден", "warning")
            return
        if self.bot.is_running:
            reply = QMessageBox.question(
                self, "Автоподбор",
                "Бот запущен. Остановить для автоподбора?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.on_stop()

        self.btn_refresh_coins.setEnabled(False)
        self.btn_refresh_coins.setText("⏳  Сканирую...")

        self.scanner_worker = ScannerWorker(top_n=10)
        self.scanner_worker.log_message.connect(self.add_log)
        self.scanner_worker.finished_ok.connect(self._on_scan_ok)
        self.scanner_worker.finished_err.connect(self._on_scan_err)
        self.scanner_worker.finished.connect(self._on_scan_done)
        self.scanner_worker.start()

    def _on_scan_ok(self, new_symbols):
        added = set(new_symbols) - set(config.AUTO_SYMBOLS)
        removed = set(config.AUTO_SYMBOLS) - set(new_symbols)
        config.AUTO_SYMBOLS = new_symbols
        self.coins_group.setTitle(f"Монеты ({len(new_symbols)})")
        self.coins_label.setText("  ".join(new_symbols))
        self.text_coins.setPlainText("\n".join(new_symbols))
        self.combo_chart_symbol.clear()
        self.combo_chart_symbol.addItems(new_symbols)
        try:
            self._update_config_file({}, new_symbols)
            self.add_log("💾 Сохранено в config.py", Palette.GREEN)
        except Exception:
            pass
        self.add_log(f"✅ Обновлено ({len(new_symbols)})", Palette.GREEN)
        if added:
            self.add_log(f"   + {', '.join(sorted(added))}", Palette.GREEN)
        if removed:
            self.add_log(f"   − {', '.join(sorted(removed))}", Palette.ORANGE)
        self.notify(f"Автоподбор: {len(new_symbols)} монет", "success")

    def _on_scan_err(self, err):
        self.add_log(f"❌ {err}", Palette.RED)
        self.notify(err, "error")

    def _on_scan_done(self):
        self.btn_refresh_coins.setEnabled(True)
        self.btn_refresh_coins.setText("🔄  АВТОПОДБОР МОНЕТ")
        self.scanner_worker = None

    # ============================================================
    # БЭКТЕСТ — сбор настроек и запуск
    # ============================================================
    def _collect_backtest_config(self):
        cfg = {}
        if self.bt_chk_adaptive_stop.isChecked():
            cfg['USE_ADAPTIVE_STOP'] = True
            cfg['ADAPTIVE_STOP_ATR_MULT'] = self.bt_stop_atr_mult.value()
            cfg['ADAPTIVE_TAKE_ATR_MULT'] = self.bt_take_atr_mult.value()
        if self.bt_chk_mtf.isChecked():
            cfg['USE_MULTI_TIMEFRAME'] = True
            cfg['MTF_WEIGHT_DAILY'] = self.bt_w_daily.value()
            cfg['MTF_WEIGHT_4H'] = self.bt_w_4h.value()
            cfg['MTF_WEIGHT_15M'] = self.bt_w_15m.value()
        if self.bt_chk_trailing.isChecked():
            cfg['USE_TRAILING_STOP'] = True
            cfg['TRAILING_START_PCT'] = self.bt_trail_start.value()
            cfg['TRAILING_STEP_PCT'] = self.bt_trail_step.value()
        if self.bt_chk_adaptive.isChecked():
            cfg['USE_ADAPTIVE_SIZE'] = True
            cfg['ADAPTIVE_ATR_LOW'] = self.bt_atr_low.value()
            cfg['ADAPTIVE_ATR_HIGH'] = self.bt_atr_high.value()
            cfg['ADAPTIVE_SIZE_MIN_PCT'] = self.bt_size_min.value()
            cfg['ADAPTIVE_SIZE_MAX_PCT'] = self.bt_size_max.value()
        if self.bt_chk_pyramid.isChecked():
            cfg['USE_PYRAMIDING'] = True
            cfg['PYRAMID_START_PCT'] = self.bt_pyr_start.value()
            cfg['PYRAMID_MAX_ADD'] = self.bt_pyr_max.value()
        if self.bt_chk_hedge.isChecked():
            cfg['USE_HEDGING'] = True
            cfg['HEDGE_TRIGGER_PCT'] = self.bt_hedge_trigger.value()
            cfg['HEDGE_SIZE_RATIO'] = self.bt_hedge_ratio.value()
        return cfg

    def _collect_backtest_days(self):
        days_list = []
        for days, chk in self.bt_period_checks.items():
            if chk.isChecked():
                days_list.append(days)
        if self.bt_custom_chk.isChecked():
            days_list.append(self.bt_custom_days.value())
        if not days_list:
            days_list = [14]
        return days_list

    def on_run_backtest_from_settings(self):
        if not BACKTEST_AVAILABLE:
            self.notify("backtest_runner.py не найден", "warning")
            return
        if self.backtest_worker is not None or self.compare_worker is not None:
            self.notify("Уже запущено", "warning")
            return

        symbols = config.AUTO_SYMBOLS
        days_list = self._collect_backtest_days()
        cfg_override = self._collect_backtest_config()
        compare_mode = self.bt_mode_compare.isChecked() and not self.bt_mode_single.isChecked()

        self.btn_bt_run.setEnabled(False)
        self.btn_bt_run.setText("⏳  Расчёт...")
        self.tabs.setCurrentIndex(7)

        if compare_mode:
            configs = [{'name': 'База (без функций)', 'config': {}}]

            if cfg_override:
                configs.append({'name': '+ Всё вместе', 'config': dict(cfg_override)})

            feature_keys = ['USE_ADAPTIVE_STOP', 'USE_MULTI_TIMEFRAME', 'USE_TRAILING_STOP',
                            'USE_ADAPTIVE_SIZE', 'USE_PYRAMIDING', 'USE_HEDGING']
            feature_names = {
                'USE_ADAPTIVE_STOP': 'AdaptiveStop',
                'USE_MULTI_TIMEFRAME': 'MTF',
                'USE_TRAILING_STOP': 'Trailing',
                'USE_ADAPTIVE_SIZE': 'AdaptiveSize',
                'USE_PYRAMIDING': 'Pyramid',
                'USE_HEDGING': 'Hedge',
            }
            feature_params = {
                'USE_ADAPTIVE_STOP': ['ADAPTIVE_STOP_ATR_MULT', 'ADAPTIVE_TAKE_ATR_MULT'],
                'USE_MULTI_TIMEFRAME': ['MTF_WEIGHT_DAILY', 'MTF_WEIGHT_4H', 'MTF_WEIGHT_15M'],
                'USE_TRAILING_STOP': ['TRAILING_START_PCT', 'TRAILING_STEP_PCT'],
                'USE_ADAPTIVE_SIZE': ['ADAPTIVE_ATR_LOW', 'ADAPTIVE_ATR_HIGH',
                                       'ADAPTIVE_SIZE_MIN_PCT', 'ADAPTIVE_SIZE_MAX_PCT'],
                'USE_PYRAMIDING': ['PYRAMID_START_PCT', 'PYRAMID_MAX_ADD'],
                'USE_HEDGING': ['HEDGE_TRIGGER_PCT', 'HEDGE_SIZE_RATIO'],
            }
            for key in feature_keys:
                if cfg_override.get(key):
                    single = {key: True}
                    for pk in feature_params.get(key, []):
                        if pk in cfg_override:
                            single[pk] = cfg_override[pk]
                    configs.append({'name': f'+ {feature_names[key]}', 'config': single})

            self._run_compare_worker(symbols, configs, days_list[0])
        else:
            self._run_single_backtest(symbols, days_list[0], cfg_override)

    def _run_single_backtest(self, symbols, days, override):
        self.progress_backtest.setValue(0)
        self.progress_backtest.setMaximum(len(symbols))
        self.progress_backtest.setFormat(f"0/{len(symbols)}")
        self.btn_cancel_backtest.setEnabled(True)
        self.lbl_backtest_status.setText(f"⏳ {len(symbols)} монет, {days} дней...")
        self.table_backtest.setRowCount(0)
        self.lbl_backtest_summary.setText("Расчёт...")

        self.backtest_worker = BacktestWorker(symbols, days, override_config=override)
        self.backtest_worker.log_message.connect(self.add_log)
        self.backtest_worker.progress.connect(self._on_backtest_progress)
        self.backtest_worker.finished_ok.connect(self._on_backtest_ok)
        self.backtest_worker.finished_err.connect(self._on_backtest_err)
        self.backtest_worker.finished.connect(self._on_backtest_done)
        self.backtest_worker.start()

    def _run_compare_worker(self, symbols, configs, days):
        self.lbl_backtest_status.setText(f"🔬 Сравнение: {len(configs)} конфигураций, {days} дней...")
        self.table_backtest.setRowCount(0)
        self.lbl_backtest_summary.setText("A/B сравнение...")

        self.compare_worker = CompareConfigsWorker(symbols, configs, days)
        self.compare_worker.log_message.connect(self.add_log)
        self.compare_worker.finished_ok.connect(self._on_compare_ok)
        self.compare_worker.finished_err.connect(self._on_compare_err)
        self.compare_worker.finished.connect(self._on_compare_done)
        self.compare_worker.start()

    def on_save_backtest_settings(self):
        try:
            values = {
                'USE_ADAPTIVE_STOP': self.bt_chk_adaptive_stop.isChecked(),
                'ADAPTIVE_STOP_ATR_MULT': self.bt_stop_atr_mult.value(),
                'ADAPTIVE_TAKE_ATR_MULT': self.bt_take_atr_mult.value(),
                'USE_MULTI_TIMEFRAME': self.bt_chk_mtf.isChecked(),
                'MTF_WEIGHT_DAILY': self.bt_w_daily.value(),
                'MTF_WEIGHT_4H': self.bt_w_4h.value(),
                'MTF_WEIGHT_15M': self.bt_w_15m.value(),
                'USE_TRAILING_STOP': self.bt_chk_trailing.isChecked(),
                'TRAILING_START_PCT': self.bt_trail_start.value(),
                'TRAILING_STEP_PCT': self.bt_trail_step.value(),
                'USE_ADAPTIVE_SIZE': self.bt_chk_adaptive.isChecked(),
                'ADAPTIVE_ATR_LOW': self.bt_atr_low.value(),
                'ADAPTIVE_ATR_HIGH': self.bt_atr_high.value(),
                'ADAPTIVE_SIZE_MIN_PCT': self.bt_size_min.value(),
                'ADAPTIVE_SIZE_MAX_PCT': self.bt_size_max.value(),
                'USE_PYRAMIDING': self.bt_chk_pyramid.isChecked(),
                'PYRAMID_START_PCT': self.bt_pyr_start.value(),
                'PYRAMID_MAX_ADD': self.bt_pyr_max.value(),
                'USE_HEDGING': self.bt_chk_hedge.isChecked(),
                'HEDGE_TRIGGER_PCT': self.bt_hedge_trigger.value(),
                'HEDGE_SIZE_RATIO': self.bt_hedge_ratio.value(),
            }
            self._update_config_file(values, config.AUTO_SYMBOLS)
            for k, v in values.items():
                setattr(config, k, v)
            self.notify("Настройки бэктеста сохранены в config.py", "success")
            self.add_log("💾 Бэктест-настройки → config.py", Palette.GREEN)
        except Exception as e:
            self.notify(str(e), "error")

    # ============================================================
    # БЭКТЕСТ — старый вызов
    # ============================================================
    def on_backtest(self):
        if not BACKTEST_AVAILABLE:
            self.notify("backtest_runner.py не найден", "warning")
            return
        if self.backtest_worker is not None:
            return
        self.tabs.setCurrentIndex(7)
        days = self.combo_period.currentData()
        symbols = config.AUTO_SYMBOLS
        self._run_single_backtest(symbols, days, {})

    def _on_backtest_progress(self, current, total, symbol):
        try:
            self.progress_backtest.setMaximum(total)
            self.progress_backtest.setValue(current)
            self.progress_backtest.setFormat(f"{current}/{total} — {symbol}")
        except Exception:
            pass

    def on_cancel_backtest(self):
        if self.backtest_worker:
            self.backtest_worker.cancel()
            self.add_log("⏹ Отмена бэктеста...", Palette.ORANGE)
            self.btn_cancel_backtest.setEnabled(False)

    def _on_backtest_ok(self, result):
        rows = result.get('results', [])
        summary = result.get('summary')
        days = result.get('period_days', 10)

        self.bt_trades_data = result.get('trades_list', [])

        self.combo_bt_symbol.blockSignals(True)
        self.combo_bt_symbol.clear()
        self.combo_bt_symbol.addItem("Все", None)
        symbols_set = sorted(set(t.get('symbol', '') for t in self.bt_trades_data))
        for sym in symbols_set:
            self.combo_bt_symbol.addItem(sym, sym)
        self.combo_bt_symbol.blockSignals(False)

        self.refresh_bt_trades()

        self.table_backtest.setRowCount(len(rows))
        for i, r in enumerate(rows):
            sym = r.get('symbol', '?')
            self.table_backtest.setItem(i, 0, QTableWidgetItem(sym))
            if r.get('error'):
                err = QTableWidgetItem("ОШИБКА")
                err.setForeground(QColor(Palette.RED))
                self.table_backtest.setItem(i, 1, err)
                continue
            if r.get('total', 0) == 0:
                for j in range(1, 7):
                    item = QTableWidgetItem("—")
                    item.setForeground(QColor("#666"))
                    self.table_backtest.setItem(i, j, item)
                continue
            self.table_backtest.setItem(i, 1, QTableWidgetItem(str(r['total'])))

            wr = QTableWidgetItem(f"{r['winrate']:.1f}%")
            wr.setForeground(QColor(
                Palette.GREEN if r['winrate'] >= 40
                else Palette.ORANGE if r['winrate'] >= 33
                else Palette.RED
            ))
            self.table_backtest.setItem(i, 2, wr)

            pnl = QTableWidgetItem(f"{r['pnl']:+.2f}%")
            pnl.setForeground(QColor(Palette.GREEN if r['pnl'] > 0 else Palette.RED))
            f = QFont(); f.setBold(True); pnl.setFont(f)
            self.table_backtest.setItem(i, 3, pnl)

            self.table_backtest.setItem(i, 4, QTableWidgetItem(f"{r['gross']:+.2f}%"))
            self.table_backtest.setItem(i, 5, QTableWidgetItem(f"{r['pf']:.2f}"))
            self.table_backtest.setItem(i, 6, QTableWidgetItem(f"{r['dd']:.2f}%"))

            if summary:
                text = "═══ ИТОГО ═══\n"
                text += f"Период:          {days} дней\n"
                text += f"Монет:           {result['symbols_count']}\n"
                text += f"Сделок:          {summary['total']}\n"
                text += f"Прибыльных:      {summary['wins']} ({summary['winrate']:.1f}%)\n"
                text += f"─────────────────────\n"
                text += f"Депозит:         ${summary.get('start_balance', 540):.2f} → ${summary.get('end_balance', 540):.2f}\n"
                text += f"P&L:             {summary['pnl']:+.2f}%  (${summary['pnl_usd']:+.2f})\n"
                text += f"  (средний по сделке: {summary.get('pnl_avg_pct', 0):+.2f}%)\n"
                text += f"Издержки:        -{summary['costs']:.2f}% от депозита\n"
                text += f"Profit Factor:   {summary['pf']:.2f}\n"
                text += f"Max Drawdown:    {summary['dd']:.2f}%  (${summary.get('dd_usd', 0):.2f})\n"
                text += f"─────────────────────\n"
                text += f"Slippage:        {summary.get('slippage_used', 0.1):.2f}% (1 сторона)\n"
                text += f"Commission:      {summary.get('commission_used', 0.055):.3f}% (1 сторона)\n"
                text += f"В плюсе/минусе:  {summary['positive']}/{summary['negative']}"
                self.lbl_backtest_summary.setText(text)

    def _on_backtest_err(self, err):
        self.lbl_backtest_status.setText(f"❌ {err}")
        self.add_log(f"❌ Бэктест: {err}", Palette.RED)
        self.notify(f"Бэктест: {err}", "error")

    def _on_backtest_done(self):
        self.btn_run_backtest.setEnabled(True)
        self.btn_run_backtest.setText("▶  ЗАПУСТИТЬ")
        self.btn_bt_run.setEnabled(True)
        self.btn_bt_run.setText("▶  ЗАПУСТИТЬ ТЕСТ")
        self.btn_cancel_backtest.setEnabled(False)
        self.progress_backtest.setValue(0)
        self.progress_backtest.setFormat("")
        self.backtest_worker = None

    # ============================================================
    # СДЕЛКИ БЭКТЕСТА
    # ============================================================
    def refresh_bt_trades(self):
        if not hasattr(self, 'bt_trades_data'):
            return

        filter_sym = self.combo_bt_symbol.currentData()
        filter_res = self.combo_bt_result.currentData()

        filtered = self.bt_trades_data
        if filter_sym:
            filtered = [t for t in filtered if t.get('symbol') == filter_sym]
        if filter_res:
            filtered = [t for t in filtered if t.get('result') == filter_res]

        self.table_bt_trades.setRowCount(len(filtered))
        for i, t in enumerate(filtered):
            pnl_pct = t.get('pnl', 0)
            pnl_usd = t.get('pnl_usd', 0)

            if pnl_pct > 0:
                row_bg = QColor(25, 55, 25)
            elif pnl_pct < 0:
                row_bg = QColor(55, 25, 25)
            else:
                row_bg = QColor(0, 0, 0, 0)

            ts_str = ''
            try:
                ts_str = str(t.get('entry_ts'))[:19].replace('T', ' ')
            except Exception:
                pass

            row_items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(ts_str),
                QTableWidgetItem(t.get('symbol', '')),
                QTableWidgetItem(t.get('type', '')),
                QTableWidgetItem(f"{t.get('entry',0):.6f}"),
                QTableWidgetItem(f"{t.get('exit',0):.6f}"),
                QTableWidgetItem(f"{pnl_pct:+.2f}%"),
                QTableWidgetItem(f"${pnl_usd:+.2f}"),
                QTableWidgetItem(t.get('reason', '?')),
                QTableWidgetItem(f"{t.get('duration_h', 0):.1f}"),
            ]

            side_item = row_items[3]
            side_item.setForeground(QColor(Palette.GREEN if t.get('type') == 'LONG' else Palette.RED))
            f = QFont(); f.setBold(True); side_item.setFont(f)

            row_items[6].setForeground(QColor(Palette.GREEN if pnl_pct > 0 else Palette.RED))
            row_items[7].setForeground(QColor(Palette.GREEN if pnl_usd > 0 else Palette.RED))

            reason = t.get('reason', '')
            if reason == 'TAKE':
                row_items[8].setForeground(QColor(Palette.GREEN))
            elif reason == 'STOP':
                row_items[8].setForeground(QColor(Palette.RED))
            elif reason == 'TRAILING':
                row_items[8].setForeground(QColor(Palette.ORANGE))

            for j, it in enumerate(row_items):
                it.setBackground(row_bg)
                self.table_bt_trades.setItem(i, j, it)

        self.lbl_bt_count.setText(f"Показано: {len(filtered)} из {len(self.bt_trades_data)}")

    def on_export_bt_trades(self):
        if not self.bt_trades_data:
            self.notify("Нет данных. Запустите бэктест.", "warning")
            return
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Экспорт сделок",
                f"bt_trades_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "CSV (*.csv)"
            )
            if not filename:
                return
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow([
                    '#', 'Дата', 'Монета', 'Сторона', 'Вход', 'Выход',
                    'P&L %', 'P&L $', 'Причина', 'Часы', 'Плечо', 'Размер $',
                    'SL %', 'TP %', 'ATR %'
                ])
                for i, t in enumerate(self.bt_trades_data):
                    writer.writerow([
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
                    ])
            self.add_log(f"💾 Экспортировано: {filename}", Palette.GREEN)
            self.notify("Сделки экспортированы", "success")
        except Exception as e:
            self.notify(str(e), "error")

    # ============================================================
    # A/B СРАВНЕНИЕ
    # ============================================================
    def on_run_compare_from_bt(self):
        if not COMPARE_AVAILABLE:
            self.notify("backtest_compare.py не найден", "warning")
            return
        if self.compare_worker is not None or self.backtest_worker is not None:
            self.notify("Уже запущено", "warning")
            return

        self.tabs.setCurrentIndex(9)
        symbols = config.AUTO_SYMBOLS
        days_list = self._collect_backtest_days()
        days = days_list[0] if days_list else 14
        cfg_override = self._collect_backtest_config()

        configs = [{'name': 'База (без функций)', 'config': {}}]
        if cfg_override:
            configs.append({'name': '+ Всё вместе', 'config': dict(cfg_override)})

        feature_keys = ['USE_ADAPTIVE_STOP', 'USE_MULTI_TIMEFRAME', 'USE_TRAILING_STOP',
                        'USE_ADAPTIVE_SIZE', 'USE_PYRAMIDING', 'USE_HEDGING']
        feature_names = {
            'USE_ADAPTIVE_STOP': 'AdaptiveStop',
            'USE_MULTI_TIMEFRAME': 'MTF',
            'USE_TRAILING_STOP': 'Trailing',
            'USE_ADAPTIVE_SIZE': 'AdaptiveSize',
            'USE_PYRAMIDING': 'Pyramid',
            'USE_HEDGING': 'Hedge',
        }
        feature_params = {
            'USE_ADAPTIVE_STOP': ['ADAPTIVE_STOP_ATR_MULT', 'ADAPTIVE_TAKE_ATR_MULT'],
            'USE_MULTI_TIMEFRAME': ['MTF_WEIGHT_DAILY', 'MTF_WEIGHT_4H', 'MTF_WEIGHT_15M'],
            'USE_TRAILING_STOP': ['TRAILING_START_PCT', 'TRAILING_STEP_PCT'],
            'USE_ADAPTIVE_SIZE': ['ADAPTIVE_ATR_LOW', 'ADAPTIVE_ATR_HIGH',
                                   'ADAPTIVE_SIZE_MIN_PCT', 'ADAPTIVE_SIZE_MAX_PCT'],
            'USE_PYRAMIDING': ['PYRAMID_START_PCT', 'PYRAMID_MAX_ADD'],
            'USE_HEDGING': ['HEDGE_TRIGGER_PCT', 'HEDGE_SIZE_RATIO'],
        }
        for key in feature_keys:
            if cfg_override.get(key):
                single = {key: True}
                for pk in feature_params.get(key, []):
                    if pk in cfg_override:
                        single[pk] = cfg_override[pk]
                configs.append({'name': f'+ {feature_names[key]}', 'config': single})

        self.btn_run_compare.setEnabled(False)
        self.btn_run_compare.setText("⏳  Идёт сравнение...")
        self.lbl_compare_status.setText(f"Сравниваю {len(configs)} конфигураций, {days} дней...")
        self.table_compare.setRowCount(0)
        self.lbl_compare_conclusion.setText("Идёт расчёт...")

        self._run_compare_worker(symbols, configs, days)
    
    def on_run_entry_ab(self):
        """A/B-тест параметров входа (MIN_TOUCHES, NEAR, CLUSTER и т.д.)."""
        if not COMPARE_AVAILABLE:
            self.notify("backtest_compare.py не найден", "warning")
            return
        if self.compare_worker is not None or self.backtest_worker is not None:
            self.notify("Уже запущено", "warning")
            return

        try:
            from backtest_compare import build_entry_ab_configs
        except ImportError:
            self.notify("build_entry_ab_configs не найден", "error")
            return

        self.tabs.setCurrentIndex(9)  # вкладка сравнения
        symbols = config.AUTO_SYMBOLS
        days_list = self._collect_backtest_days()
        days = days_list[0] if days_list else 14

        configs = build_entry_ab_configs()

        self.btn_run_compare.setEnabled(False)
        self.btn_run_compare.setText("⏳  Идёт A/B...")
        if hasattr(self, 'btn_run_entry_ab'):
            self.btn_run_entry_ab.setEnabled(False)
            self.btn_run_entry_ab.setText("⏳  Идёт A/B...")

        self.lbl_compare_status.setText(f"🎯 A/B вход: {len(configs)} конфигураций, {days} дней...")
        self.table_compare.setRowCount(0)
        self.lbl_compare_conclusion.setText("Идёт A/B-тест параметров входа...")

        self._run_compare_worker(symbols, configs, days)

    def _on_compare_ok(self, results):
        self.compare_results = results
        self.table_compare.setRowCount(len(results))

        baseline_pnl = None
        for i, r in enumerate(results):
            name_item = QTableWidgetItem(r.get('name', '?'))
            f = QFont(); f.setBold(True); name_item.setFont(f)
            self.table_compare.setItem(i, 0, name_item)

            if r.get('error') or not r.get('summary'):
                err = QTableWidgetItem("ОШИБКА")
                err.setForeground(QColor(Palette.RED))
                self.table_compare.setItem(i, 1, err)
                continue

            self.table_compare.setItem(i, 1, QTableWidgetItem(str(r.get('trades_count', 0))))

            wr = r.get('winrate', 0)
            wr_item = QTableWidgetItem(f"{wr:.1f}%")
            wr_item.setForeground(QColor(
                Palette.GREEN if wr >= 50
                else Palette.ORANGE if wr >= 33
                else Palette.RED
            ))
            self.table_compare.setItem(i, 2, wr_item)

            pnl = r.get('pnl', 0)
            pnl_item = QTableWidgetItem(f"{pnl:+.2f}%")
            pnl_item.setForeground(QColor(Palette.GREEN if pnl > 0 else Palette.RED))
            f2 = QFont(); f2.setBold(True); pnl_item.setFont(f2)
            self.table_compare.setItem(i, 3, pnl_item)

            if i == 0:
                baseline_pnl = pnl

            self.table_compare.setItem(i, 4, QTableWidgetItem(f"${r.get('pnl_usd', 0):+.2f}"))

            pf = r.get('pf', 0)
            pf_item = QTableWidgetItem(f"{pf:.2f}")
            pf_item.setForeground(QColor(
                Palette.GREEN if pf >= 1.5
                else Palette.ORANGE if pf >= 1.0
                else Palette.RED
            ))
            self.table_compare.setItem(i, 5, pf_item)

            dd = r.get('dd', 0)
            dd_item = QTableWidgetItem(f"{dd:.2f}%")
            dd_item.setForeground(QColor(
                Palette.GREEN if dd < 15
                else Palette.ORANGE if dd < 30
                else Palette.RED
            ))
            self.table_compare.setItem(i, 6, dd_item)

        if baseline_pnl is not None:
            text = "═══ ВЫВОДЫ ═══\n\n"
            text += f"База (без функций): P&L {baseline_pnl:+.2f}%\n\n"
            text += "Влияние функций:\n"
            for r in results[1:]:
                if r.get('error') or not r.get('summary'):
                    continue
                diff = r.get('pnl', 0) - baseline_pnl
                icon = "✅" if diff > 1 else "⚠️" if diff > -1 else "❌"
                text += (
                    f"  {icon} {r['name']}: {diff:+.2f}% "
                    f"({r.get('trades_count', 0)} сделок, "
                    f"{r.get('winrate', 0):.1f}% wr)\n"
                )
            self.lbl_compare_conclusion.setText(text)

        self.lbl_compare_status.setText("✅ Сравнение завершено")
        self.notify("A/B сравнение завершено", "success")

    def _on_compare_err(self, err):
        self.lbl_compare_status.setText(f"❌ Ошибка: {err}")
        self.add_log(f"❌ Сравнение: {err}", Palette.RED)
        self.notify(f"Сравнение: {err}", "error")

    def _on_compare_done(self):
        self.btn_run_compare.setEnabled(True)
        self.btn_run_compare.setText("🔬  ЗАПУСТИТЬ СРАВНЕНИЕ")
        if hasattr(self, 'btn_run_entry_ab'):
            self.btn_run_entry_ab.setEnabled(True)
            self.btn_run_entry_ab.setText("🎯  A/B ТЕСТ ВХОДА")
        self.compare_worker = None
        self.btn_bt_run.setEnabled(True)
        self.btn_bt_run.setText("▶  ЗАПУСТИТЬ ТЕСТ")

    # ============================================================
    # СТАРТ / СТОП / ЗАКРЫТИЕ
    # ============================================================
    def on_start(self):
        msg = (
            f"Запустить АВТОБОТ?\n\n"
            f"• Размер:       {config.AUTO_POSITION_PCT}%  "
            f"(адаптивный: {config.USE_ADAPTIVE_SIZE})\n"
            f"• Плечо:        до {config.MAX_AUTO_LEVERAGE}x\n"
            f"• Позиций:      {config.MAX_POSITIONS_TOTAL}\n"
            f"• Сделок/день:  {config.AUTO_MAX_TRADES_PER_DAY}\n"
            f"• Адапт. стоп:  {config.USE_ADAPTIVE_STOP}\n"
            f"• MTF:          {config.USE_MULTI_TIMEFRAME}\n"
            f"• Trailing:     {config.USE_TRAILING_STOP}\n"
            f"• Пирамидинг:   {config.USE_PYRAMIDING}\n"
            f"• Хедж:         {config.USE_HEDGING}\n\n"
            f"Продолжить?"
        )
        reply = QMessageBox.question(
            self, "Запуск", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_status.setText("🟢 РАБОТАЕТ")
        self.lbl_status.setStyleSheet(
            f"font-size: 15px; font-weight: 700; padding: 8px 16px; "
            f"color: {Palette.GREEN}; background: {Palette.BG_PANEL}; "
            f"border-radius: 8px; border: 1px solid {Palette.GREEN_DARK};"
        )

        self.bot.start()
        self.run_cycle()
        self.timer.start(config.AUTO_CHECK_INTERVAL_SEC * 1000)
        self.notify("Автобот запущен", "success")

    def on_stop(self):
        self.timer.stop()
        self.bot.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("⏸ Остановлен")
        self.lbl_status.setStyleSheet(
            f"font-size: 15px; font-weight: 700; padding: 8px 16px; "
            f"color: {Palette.TEXT_DIM}; background: {Palette.BG_PANEL}; "
            f"border-radius: 8px; border: 1px solid {Palette.BORDER};"
        )
        self.refresh_history()
        self.refresh_stats()
        self.notify("Автобот остановлен", "info")

    def on_close_all(self):
        positions = self.bot.trader.state['open_positions']
        if not positions:
            self.notify("Нет открытых позиций", "info")
            return
        reply = QMessageBox.question(
            self, "Закрыть всё",
            f"Закрыть {len(positions)} позиций?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            results = self.bot.trader.close_all()
            for r in results:
                self.add_log(f"  {r}", Palette.ORANGE)
            self.add_log("✅ Позиции закрыты", Palette.GREEN)
            self.notify("Позиции закрыты", "success")
        except Exception as e:
            self.add_log(f"❌ {str(e)[:100]}", Palette.RED)
            self.notify(str(e), "error")

    # ============================================================
    # ЦИКЛ
    # ============================================================
    def run_cycle(self):
        if not self.bot.is_running:
            return
        try:
            self.bot.check_cycle()
            self._cycle_count += 1
            if self._cycle_count % 5 == 0:
                self.refresh_history()
                self.refresh_stats()
                self.on_sync_positions()
        except Exception as e:
            self.add_log(f"❌ Цикл: {str(e)[:100]}", Palette.RED)

    def on_balance(self, bal):
        pass

    def on_signal(self, symbol, side, level):
        self.lbl_status.setText(f"⚡ {side} {symbol}")
        QTimer.singleShot(3000, lambda: self.lbl_status.setText("🟢 РАБОТАЕТ"))
        if getattr(config, 'SOUND_ON_SIGNAL', True):
            try:
                QApplication.beep()
            except Exception:
                pass

    def on_positions(self, positions):
        self.table_positions.setRowCount(len(positions))
        for i, p in enumerate(positions):
            pnl_pct = p['pnl_pct']
            lev = p.get('leverage', 1)
            pnl_usd = p['usd_size'] * pnl_pct / 100 * lev

            if pnl_pct > 0.5:
                row_bg = QColor(22, 55, 22)
            elif pnl_pct < -0.5:
                row_bg = QColor(55, 22, 22)
            else:
                row_bg = QColor(35, 35, 35)

            row_items = [
                QTableWidgetItem(p['symbol']),
                QTableWidgetItem(p['side']),
                QTableWidgetItem(f"{lev:.1f}x"),
                QTableWidgetItem(f"{p['entry']:.6f}"),
                QTableWidgetItem(f"{p['current']:.6f}"),
                QTableWidgetItem(f"${p['usd_size']:.2f}"),
                QTableWidgetItem(f"{p['stop']:.6f}"),
                QTableWidgetItem(f"{p['take']:.6f}"),
                QTableWidgetItem(f"{pnl_pct:+.2f}%"),
                QTableWidgetItem(f"${pnl_usd:+.2f}"),
                QTableWidgetItem(" ".join(filter(None, [
                    f"+{p.get('adds_count', 0)}" if p.get('adds_count') else "",
                    "HEDGE" if p.get('has_hedge') else ""
                ]))),
            ]

            side_item = row_items[1]
            side_item.setForeground(QColor(Palette.GREEN if p['side'] == 'LONG' else Palette.RED))
            f = QFont(); f.setBold(True); side_item.setFont(f)

            row_items[8].setForeground(QColor(Palette.GREEN if pnl_pct > 0 else Palette.RED))
            f2 = QFont(); f2.setBold(True); row_items[8].setFont(f2)

            row_items[9].setForeground(QColor(Palette.GREEN if pnl_usd > 0 else Palette.RED))

            for j, it in enumerate(row_items):
                it.setBackground(row_bg)
                self.table_positions.setItem(i, j, it)

    def on_status(self, status):
        self.lbl_positions_info.setText(f"Позиций: {status['open_positions']}/{config.MAX_POSITIONS_TOTAL}")
        self.lbl_trades_info.setText(f"Сделок: {status['trades_today']}/{config.AUTO_MAX_TRADES_PER_DAY}")
        self.status_positions.setText(f"📊  Позиций: {status['open_positions']}/{config.MAX_POSITIONS_TOTAL}")
        self.status_trades.setText(f"📈  Сделок: {status['trades_today']}/{config.AUTO_MAX_TRADES_PER_DAY}")

        pnl = status['pnl_today']
        color = Palette.GREEN if pnl >= 0 else Palette.RED
        self.lbl_daily_pnl.setText(f"{pnl:+.2f}%")
        self.lbl_daily_pnl.setStyleSheet(
            f"font-size: 26px; font-weight: 800; color: {color}; "
            f"border: none; background: transparent;"
        )

    # ============================================================
    # ТЕМА / BYBIT
    # ============================================================
    def on_toggle_theme(self):
        new = 'light' if self.theme == 'dark' else 'dark'
        self._apply_theme(new)
        self.add_log(f"🎨 Тема: {new}", Palette.TEXT_DIM)

    def on_open_bybit(self):
        QDesktopServices.openUrl(QUrl(BYBIT_URL))

    # ============================================================
    # СОБЫТИЯ
    # ============================================================
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F5:
            self.on_sync_positions()
        elif event.key() == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.on_sync_positions()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.bot.is_running:
            reply = QMessageBox.question(
                self, "Выход",
                "Автобот работает. Остановить и выйти?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.on_stop()
        event.accept()


# ============================================================
# ЗАПУСК
# ============================================================
def main():
    app = QApplication(sys.argv)
    window = AutoTraderWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()