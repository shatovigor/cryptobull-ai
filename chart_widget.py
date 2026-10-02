"""
Графики: свечной, equity, с зумом и уровнями.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt
import numpy as np

try:
    import pyqtgraph as pg
    PYQTGRAPH_AVAILABLE = True
except ImportError:
    PYQTGRAPH_AVAILABLE = False


class PriceChart(QWidget):
    """Свечной график цены с уровнями и зумом."""

    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.use_candles = True
        self.candle_item = None

        # Кнопки управления
        ctrl = QHBoxLayout()
        self.btn_candles = QPushButton("📊 Свечи")
        self.btn_candles.setCheckable(True)
        self.btn_candles.setChecked(True)
        self.btn_candles.clicked.connect(self._toggle_mode)
        ctrl.addWidget(self.btn_candles)

        self.btn_reset_zoom = QPushButton("🔍 Сброс зума")
        self.btn_reset_zoom.clicked.connect(self._reset_zoom)
        ctrl.addWidget(self.btn_reset_zoom)

        ctrl.addStretch()
        self.layout.addLayout(ctrl)

        if not PYQTGRAPH_AVAILABLE:
            label = QLabel("⚠ Установите pyqtgraph:\npip install pyqtgraph")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #ff9800; font-size: 14px; padding: 20px;")
            self.layout.addWidget(label)
            self.plot_widget = None
            return

        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', '#d4d4d4')

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.setLabel('left', 'Цена')
        self.plot_widget.setLabel('bottom', 'Свечи')

        # Включаем мышь для зума
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.enableAutoRange()

        self.layout.addWidget(self.plot_widget)

    def _toggle_mode(self):
        self.use_candles = self.btn_candles.isChecked()
        self.btn_candles.setText("📊 Свечи" if self.use_candles else "📈 Линия")

    def _reset_zoom(self):
        if self.plot_widget:
            self.plot_widget.enableAutoRange()
            self.plot_widget.autoRange()

    def plot(self, df, levels=None, title=None, positions=None):
        if not PYQTGRAPH_AVAILABLE or self.plot_widget is None:
            return

        self.plot_widget.clear()
        if df is None or len(df) == 0:
            return

        x = np.arange(len(df))

        if self.use_candles:
            # Свечной график через CandlestickItem
            self._plot_candles(df, x)
        else:
            # Линия
            closes = df['close'].values
            self.plot_widget.plot(x, closes, pen=pg.mkPen('#4caf50', width=2))

        # Уровни
        if levels:
            for lvl in levels:
                price = lvl['price']
                touches = lvl.get('touches', 1)
                color = '#ff5722' if touches >= 10 else '#ff9800' if touches >= 5 else '#888'
                line = pg.InfiniteLine(
                    pos=price, angle=0,
                    pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
                    label=f"x{touches}",
                    labelOpts={'position': 0.9, 'color': color}
                )
                self.plot_widget.addItem(line)

        # Позиции
        if positions:
            for pos in positions:
                entry = pos.get('entry')
                stop = pos.get('stop')
                take = pos.get('take')
                if entry:
                    line = pg.InfiniteLine(
                        pos=entry, angle=0,
                        pen=pg.mkPen('#0277bd', width=2),
                        label=f"Вход {pos['side']}",
                        labelOpts={'position': 0.1, 'color': '#0277bd'}
                    )
                    self.plot_widget.addItem(line)
                if stop:
                    line = pg.InfiniteLine(
                        pos=stop, angle=0,
                        pen=pg.mkPen('#f44336', width=1, style=Qt.PenStyle.DotLine),
                        label='SL',
                        labelOpts={'position': 0.2, 'color': '#f44336'}
                    )
                    self.plot_widget.addItem(line)
                if take:
                    line = pg.InfiniteLine(
                        pos=take, angle=0,
                        pen=pg.mkPen('#4caf50', width=1, style=Qt.PenStyle.DotLine),
                        label='TP',
                        labelOpts={'position': 0.3, 'color': '#4caf50'}
                    )
                    self.plot_widget.addItem(line)

        if title:
            self.plot_widget.setTitle(title, color='#d4d4d4', size='12pt')

    def _plot_candles(self, df, x):
        """Рисует свечи."""
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values

        # Через BarGraphItem — кастомные "свечи"
        # Зелёные свечи (растущие)
        up_mask = closes >= opens
        down_mask = ~up_mask

        w = 0.6

        # Рисуем высокие-низкие (фитили)
        for i in range(len(df)):
            color = '#4caf50' if closes[i] >= opens[i] else '#f44336'
            self.plot_widget.plot(
                [x[i], x[i]], [lows[i], highs[i]],
                pen=pg.mkPen(color, width=1)
            )

        # Тела свечей
        bar_up = pg.BarGraphItem(
            x=x[up_mask], height=closes[up_mask] - opens[up_mask],
            y0=opens[up_mask], width=w,
            brush=pg.mkBrush('#4caf50'), pen=pg.mkPen('#4caf50')
        )
        self.plot_widget.addItem(bar_up)

        bar_down = pg.BarGraphItem(
            x=x[down_mask], height=closes[down_mask] - opens[down_mask],
            y0=opens[down_mask], width=w,
            brush=pg.mkBrush('#f44336'), pen=pg.mkPen('#f44336')
        )
        self.plot_widget.addItem(bar_down)


class EquityChart(QWidget):
    """График equity."""

    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        if not PYQTGRAPH_AVAILABLE:
            label = QLabel("⚠ Установите pyqtgraph")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #ff9800; padding: 20px;")
            self.layout.addWidget(label)
            self.plot_widget = None
            return

        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', '#d4d4d4')

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.setLabel('left', 'Equity $')
        self.plot_widget.setLabel('bottom', 'Время')
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.layout.addWidget(self.plot_widget)

    def plot(self, points):
        if not PYQTGRAPH_AVAILABLE or self.plot_widget is None:
            return

        self.plot_widget.clear()
        if not points:
            self.plot_widget.setTitle("Нет данных", color='#888')
            return

        x = np.arange(len(points))
        y = np.array([p['equity'] for p in points])

        self.plot_widget.plot(x, y, pen=pg.mkPen('#4caf50', width=2))

        start = y[0]
        self.plot_widget.addLine(y=start, pen=pg.mkPen('#888', width=1, style=Qt.PenStyle.DashLine))

        self.plot_widget.setTitle(
            f"Equity: ${y[-1]:.2f} ({y[-1] - start:+.2f}, {(y[-1] - start) / start * 100:+.2f}%)",
            color='#d4d4d4', size='12pt'
        )