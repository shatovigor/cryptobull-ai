"""
Вкладка «Стратегия» — УНИВЕРСАЛЬНАЯ.

Логика:
  - Сверху выбор стратегии: classic_levels / adaptive_ml / trendrider
  - Ниже — ДИНАМИЧЕСКИЙ блок параметров, релевантных выбранной стратегии
  - Ещё ниже — ОБЩИЙ блок «Риск и размер» (применяется ко всем стратегиям)

Смена стратегии останавливает бота (если запущен), применяет новые
параметры, сохраняет их в config.py.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QFormLayout, QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit,
    QGroupBox, QScrollArea, QMessageBox, QFrame,
)
from PyQt6.QtCore import Qt

from ..palette import Palette
from ..widgets import make_button, Card, HintRow
import config


# ============================================================
# СХЕМЫ ПАРАМЕТРОВ ДЛЯ КАЖДОЙ СТРАТЕГИИ
# ============================================================
# Формат: (config_key, label, type, min, max, step, suffix)
#   type: 'float' | 'int' | 'bool'
# ============================================================

CLASSIC_LEVELS_SCHEMA = [
    ("MIN_TOUCHES",           "Мин. касаний уровня",     'int',   2,  20,  1,   ""),
    ("CLUSTER_PCT",           "Кластер уровней",         'float', 0.1, 5.0, 0.1, " %"),
    ("MAX_LEVEL_AGE_DAYS",    "Макс. возраст уровня",    'int',   1,  365, 1,   " дн"),
    ("LOOKBACK_DAYS",         "Lookback для уровней",    'int',   30, 365, 1,   " дн"),
    ("NEAR_LEVEL_PCT",        "Близость к уровню",       'float', 0.1, 5.0, 0.1, " %"),
    ("PINBAR_SHADOW_RATIO",   "Pinbar: shadow ratio",    'float', 0.5, 5.0, 0.1, ""),
    ("MIN_SHADOW_PCT",        "Pinbar: мин. тень",       'float', 0.01, 2.0, 0.05, " %"),
    ("USE_BOUNCE_SIGNAL",     "Bounce-сигнал",           'bool',  0,  0,  0,   ""),
    ("USE_TREND_FILTER",      "Фильтр тренда (daily)",   'bool',  0,  0,  0,   ""),
    ("USE_4H_TREND_FILTER",   "Фильтр тренда (4h)",      'bool',  0,  0,  0,   ""),
    ("COOLDOWN_MINUTES",      "Cooldown между сделками", 'int',   0,  1440, 5,  " мин"),
]

ADAPTIVE_ML_SCHEMA = [
    ("AML_CONF_THRESHOLD",    "Порог уверенности",       'float', 0.5, 0.95, 0.01, ""),
    ("AML_MIN_MOVE_PCT",      "Мин. ожидаемое движение", 'float', 0.05, 3.0, 0.05, " %"),
    ("AML_UPDATE_INTERVAL",   "Обновление модели",       'int',   10, 500, 5,   " сделок"),
    ("AML_KELLY_FRACTION",    "Доля Kelly",              'float', 0.05, 1.0, 0.05, ""),
    ("AML_MAX_LEVERAGE",      "Макс. плечо",             'float', 1.0, 10.0, 0.5, " x"),
    ("AML_MAX_SIZE_PCT",      "Макс. размер позиции",    'float', 0.01, 1.0, 0.01, " (доля)"),
    ("AML_STOP_ATR_MULT",     "Стоп × ATR",              'float', 0.5, 5.0, 0.1, ""),
    ("AML_TAKE_ATR_MULT",     "Тейк × ATR",              'float', 1.0, 10.0, 0.5, ""),
]

TRENDRIDER_SCHEMA = [
    ("TREND_EMA_FAST",        "EMA быстрая",             'int',   3,  50,  1,  ""),
    ("TREND_EMA_SLOW",        "EMA медленная",           'int',   5,  200, 1,  ""),
    ("TREND_RSI_PERIOD",      "RSI период",              'int',   5,  50,  1,  ""),
    ("TREND_RSI_PULLBACK_LOW","RSI pullback low",        'int',   20, 50,  1,  ""),
    ("TREND_RSI_PULLBACK_HIGH","RSI pullback high",      'int',   50, 80,  1,  ""),
    ("TREND_RSI_BOUNCE",      "RSI bounce",              'int',   10, 50,  1,  ""),
    ("TREND_RSI_EXIT",        "RSI exit",                'int',   60, 90,  1,  ""),
    ("TREND_ADX_THRESHOLD",   "ADX порог",               'int',   10, 50,  1,  ""),
    ("TREND_VOLUME_FACTOR",   "Множитель объёма",        'float', 0.5, 3.0, 0.1, " x"),
    ("TREND_MIN_CONF",        "Мин. уверенность (bull)", 'int',   0,  10,  1,  ""),
    ("TREND_MIN_CONF_BEAR",   "Мин. уверенность (bear)", 'int',   0,  10,  1,  ""),
]

STRATEGY_SCHEMAS = {
    'classic_levels': CLASSIC_LEVELS_SCHEMA,
    'adaptive_ml':    ADAPTIVE_ML_SCHEMA,
    'trendrider':     TRENDRIDER_SCHEMA,
}

STRATEGY_LABELS = {
    'classic_levels': "📊 Уровни + паттерны",
    'adaptive_ml':    "🧠 Адаптивная ML",
    'trendrider':     "📈 TrendRider",
}

STRATEGY_DESCRIPTIONS = {
    'classic_levels': (
        "Классическая стратегия: поиск горизонтальных уровней по истории, "
        "вход по пинбару или bounce к уровню. Работает в любую сторону — "
        "нужен только тренд-фильтр."
    ),
    'adaptive_ml': (
        "Онлайн-обучаемая ML-модель на 15 фичах (returns, SMA-ratio, RSI, "
        "MACD, ATR, объём). Требует накопления 50+ сделок для старта, "
        "далее обновляется каждые N сделок."
    ),
    'trendrider': (
        "Трендовая стратегия на 1h: EMA cross, RSI pullback, фильтр ADX, "
        "подтверждение по объёму. Вход только в направлении тренда."
    ),
}


class StrategyTab(QWidget):
    def __init__(self, bot, main_window):
        super().__init__()
        self.bot = bot
        self.mw = main_window

        # Хранилище виджетов параметров: {config_key: widget}
        self._widgets = {}
        # Хранилище HintRow-обёрток для обновления подсказок
        self._hint_rows = {}

        self._defaults = self._load_defaults()
        self._build_ui()

    # ============================================================
    # UI
    # ============================================================
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        # ==== БЛОК 1: ВЫБОР СТРАТЕГИИ ====
        layout.addWidget(self._build_strategy_selector())

        # ==== БЛОК 2: ОПИСАНИЕ ====
        self.lbl_description = QLabel()
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 12px; "
            f"background: {Palette.BG_PANEL}; padding: 12px 14px; "
            f"border-radius: 8px; border: 1px solid {Palette.BORDER};"
        )
        layout.addWidget(self.lbl_description)

        # ==== БЛОК 3: ДИНАМИЧЕСКИЕ ПАРАМЕТРЫ СТРАТЕГИИ ====
        self.params_group = QGroupBox("Параметры стратегии")
        self.params_form = QFormLayout(self.params_group)
        self.params_form.setSpacing(10)
        self.params_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.params_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        layout.addWidget(self.params_group)

        # ==== БЛОК 4: ОБЩИЙ «РИСК И РАЗМЕР» ====
        layout.addWidget(self._build_risk_group())

        # ==== КНОПКИ ====
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_save = make_button("💾  Сохранить в config.py", kind='accent')
        self.btn_save.clicked.connect(self._on_save)
        btns.addWidget(self.btn_save)

        self.btn_reset = make_button("↺  Сбросить к стандарту", kind='ghost')
        self.btn_reset.clicked.connect(self._on_reset)
        btns.addWidget(self.btn_reset)

        self.btn_reload = make_button("🔄  Перезагрузить из файла", kind='ghost')
        self.btn_reload.clicked.connect(self._on_reload)
        btns.addWidget(self.btn_reload)

        btns.addStretch()
        layout.addLayout(btns)

        layout.addStretch()

        # Первая отрисовка
        self._rebuild_params()

    # ------------------------------------------------------------
    def _build_strategy_selector(self):
        card = Card(padding=14)
        lay = QVBoxLayout()
        lay.setSpacing(10)

        title = QLabel("Активная стратегия")
        title.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 11px; "
            f"text-transform: uppercase; letter-spacing: 0.5px; "
            f"background: transparent;"
        )
        lay.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.combo_strategy = QComboBox()
        for key, label in STRATEGY_LABELS.items():
            self.combo_strategy.addItem(label, key)
        self.combo_strategy.setMinimumWidth(280)
        self.combo_strategy.setStyleSheet(
            f"QComboBox {{ font-size: 14px; font-weight: 600; padding: 10px 14px; }}"
        )

        # Установить текущую
        current = getattr(config, 'ACTIVE_STRATEGY', 'classic_levels')
        idx = self.combo_strategy.findData(current)
        if idx >= 0:
            self.combo_strategy.setCurrentIndex(idx)

        self.combo_strategy.currentIndexChanged.connect(self._on_strategy_changed)
        row.addWidget(self.combo_strategy)

        self.lbl_strategy_status = QLabel("—")
        self.lbl_strategy_status.setStyleSheet(
            f"color: {Palette.SUCCESS}; font-weight: 600; "
            f"background: transparent; padding: 0 8px;"
        )
        row.addWidget(self.lbl_strategy_status)
        row.addStretch()

        lay.addLayout(row)
        card.layout().addLayout(lay)
        return card

    # ------------------------------------------------------------
    def _build_risk_group(self):
        group = QGroupBox("Риск и размер позиции (общее для всех стратегий)")
        form = QFormLayout(group)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # % от баланса
        self.risk_pct = self._make_widget(
            config.AUTO_POSITION_PCT, 'float', 0.5, 50.0, 0.5
        )
        self._add_hint_row(form, "Размер позиции", self.risk_pct,
                           config.AUTO_POSITION_PCT,
                           self._defaults.get("AUTO_POSITION_PCT", 5.0),
                           "%", "AUTO_POSITION_PCT")

        # Макс. плечо
        self.risk_max_lev = self._make_widget(
            config.MAX_AUTO_LEVERAGE, 'float', 1.0, 20.0, 0.5
        )
        self._add_hint_row(form, "Макс. плечо", self.risk_max_lev,
                           config.MAX_AUTO_LEVERAGE,
                           self._defaults.get("MAX_AUTO_LEVERAGE", 2.0),
                           "x", "MAX_AUTO_LEVERAGE")

        # Авто-плечо
        self.risk_auto_lev = QCheckBox("Авто-плечо по ATR и силе сигнала")
        self.risk_auto_lev.setChecked(getattr(config, 'USE_AUTO_LEVERAGE', True))
        form.addRow("", self.risk_auto_lev)

        # Макс. позиций
        self.risk_max_pos = self._make_widget(
            config.MAX_POSITIONS_TOTAL, 'int', 1, 30, 1
        )
        self._add_hint_row(form, "Макс. позиций", self.risk_max_pos,
                           config.MAX_POSITIONS_TOTAL,
                           self._defaults.get("MAX_POSITIONS_TOTAL", 4),
                           "", "MAX_POSITIONS_TOTAL")

        # Дневной стоп
        self.risk_daily_stop = self._make_widget(
            config.AUTO_DAILY_STOP_PCT, 'float', 0.5, 50.0, 0.5
        )
        self._add_hint_row(form, "Дневной стоп", self.risk_daily_stop,
                           config.AUTO_DAILY_STOP_PCT,
                           self._defaults.get("AUTO_DAILY_STOP_PCT", 3.0),
                           "%", "AUTO_DAILY_STOP_PCT")

        # Сделок в день
        self.risk_max_trades = self._make_widget(
            config.AUTO_MAX_TRADES_PER_DAY, 'int', 1, 100, 1
        )
        self._add_hint_row(form, "Сделок в день", self.risk_max_trades,
                           config.AUTO_MAX_TRADES_PER_DAY,
                           self._defaults.get("AUTO_MAX_TRADES_PER_DAY", 15),
                           "", "AUTO_MAX_TRADES_PER_DAY")

        # Мин. размер
        self.risk_min_size = self._make_widget(
            config.AUTO_MIN_POSITION_USD, 'float', 1.0, 1000.0, 5.0
        )
        self._add_hint_row(form, "Мин. размер позиции", self.risk_min_size,
                           config.AUTO_MIN_POSITION_USD,
                           self._defaults.get("AUTO_MIN_POSITION_USD", 10.0),
                           "$", "AUTO_MIN_POSITION_USD")

        # Макс. размер
        self.risk_max_size = self._make_widget(
            config.AUTO_MAX_POSITION_USD, 'float', 10.0, 100000.0, 50.0
        )
        self._add_hint_row(form, "Макс. размер позиции", self.risk_max_size,
                           config.AUTO_MAX_POSITION_USD,
                           self._defaults.get("AUTO_MAX_POSITION_USD", 500.0),
                           "$", "AUTO_MAX_POSITION_USD")

        # Адаптивный размер
        self.risk_adaptive_size = QCheckBox("Адаптивный размер по ATR")
        self.risk_adaptive_size.setChecked(getattr(config, 'USE_ADAPTIVE_SIZE', False))
        form.addRow("", self.risk_adaptive_size)

        return group

    # ============================================================
    # ДИНАМИЧЕСКАЯ ПЕРЕРИСОВКА ПАРАМЕТРОВ СТРАТЕГИИ
    # ============================================================
    def _rebuild_params(self):
        # Очистить форму
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self._widgets.clear()
        self._hint_rows.clear()

        key = self.combo_strategy.currentData()
        schema = STRATEGY_SCHEMAS.get(key, [])

        self.lbl_description.setText(STRATEGY_DESCRIPTIONS.get(key, ""))
        self.params_group.setTitle(
            f"Параметры: {STRATEGY_LABELS.get(key, key)}"
        )

        if not schema:
            lbl = QLabel("У этой стратегии нет настраиваемых параметров.")
            lbl.setStyleSheet(f"color: {Palette.TEXT_MUTED}; padding: 8px;")
            self.params_form.addRow(lbl)
            return

        for spec in schema:
            ckey, label, typ, mn, mx, step, suffix = spec

            current_val = getattr(config, ckey, None)
            default_val = self._defaults.get(ckey, current_val)

            if typ == 'bool':
                w = QCheckBox()
                w.setChecked(bool(current_val))
                self.params_form.addRow("", w)
                self._widgets[ckey] = w
                continue

            w = self._make_widget(current_val, typ, mn, mx, step)
            self._add_hint_row(self.params_form, label, w,
                               current_val, default_val, suffix, ckey)
            self._widgets[ckey] = w

        # Если стратегия не активна — бот может быть запущен, предупреждаем
        self._update_status_label()

    def _make_widget(self, value, typ, mn, mx, step):
        if typ == 'int':
            w = QSpinBox()
            w.setRange(int(mn), int(mx))
            w.setSingleStep(int(step) or 1)
            w.setValue(int(value) if value is not None else int(mn))
        elif typ == 'float':
            w = QDoubleSpinBox()
            w.setRange(float(mn), float(mx))
            w.setDecimals(3 if mx <= 3 else 2)
            w.setSingleStep(float(step) or 0.1)
            w.setValue(float(value) if value is not None else float(mn))
        else:
            w = QLineEdit(str(value) if value is not None else "")
        w.setMinimumWidth(140)
        return w

    def _add_hint_row(self, form, label, widget, current, default, suffix, config_key):
        """Добавляет строку с подсказкой «сейчас / стандарт»."""
        row = HintRow(widget, current, default, suffix)
        form.addRow(label, row)
        self._hint_rows[config_key] = row

    def _update_status_label(self):
        key = self.combo_strategy.currentData()
        active = getattr(config, 'ACTIVE_STRATEGY', 'classic_levels')

        if key == active:
            self.lbl_strategy_status.setText("✓ активна")
            self.lbl_strategy_status.setStyleSheet(
                f"color: {Palette.SUCCESS}; font-weight: 600; "
                f"background: transparent; padding: 0 8px;"
            )
        else:
            self.lbl_strategy_status.setText("выбрана, но не применена")
            self.lbl_strategy_status.setStyleSheet(
                f"color: {Palette.WARNING}; font-weight: 600; "
                f"background: transparent; padding: 0 8px;"
            )

    # ============================================================
    # СОБЫТИЯ
    # ============================================================
    def _on_strategy_changed(self, idx):
        key = self.combo_strategy.currentData()
        active = getattr(config, 'ACTIVE_STRATEGY', 'classic_levels')

        # Если это НЕ текущая активная — спросим, применять ли
        if key == active:
            self._rebuild_params()
            return

        reply = QMessageBox.question(
            self, "Смена стратегии",
            f"Переключиться на «{STRATEGY_LABELS.get(key, key)}»?\n\n"
            f"Текущая стратегия: {STRATEGY_LABELS.get(active, active)}\n\n"
            f"Если бот запущен — он будет остановлен.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            # Откатываем комбобокс
            i = self.combo_strategy.findData(active)
            if i >= 0:
                self.combo_strategy.blockSignals(True)
                self.combo_strategy.setCurrentIndex(i)
                self.combo_strategy.blockSignals(False)
            self._rebuild_params()
            return

        if self.bot.is_running:
            self.mw.on_stop()

        try:
            self.bot.set_strategy(key)
            config.ACTIVE_STRATEGY = key
            self._save_config_key('ACTIVE_STRATEGY', key)

            self.mw.tab_bot.log(
                f"🎯 Стратегия: {STRATEGY_LABELS.get(key, key)}",
                Palette.ACCENT
            )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

        self._rebuild_params()

    # ============================================================
    # СОХРАНЕНИЕ / СБРОС
    # ============================================================
    def _on_save(self):
        # 1. Параметры стратегии
        strategy_key = self.combo_strategy.currentData()
        schema = STRATEGY_SCHEMAS.get(strategy_key, [])

        values = {}

        for spec in schema:
            ckey, _, typ, *_ = spec
            w = self._widgets.get(ckey)
            if w is None:
                continue
            if typ == 'bool':
                values[ckey] = w.isChecked()
            elif typ == 'int':
                values[ckey] = w.value()
            elif typ == 'float':
                values[ckey] = w.value()
            else:
                values[ckey] = w.text()

        # 2. Общие параметры риска
        values['AUTO_POSITION_PCT'] = self.risk_pct.value()
        values['MAX_AUTO_LEVERAGE'] = self.risk_max_lev.value()
        values['USE_AUTO_LEVERAGE'] = self.risk_auto_lev.isChecked()
        values['MAX_POSITIONS_TOTAL'] = self.risk_max_pos.value()
        values['AUTO_DAILY_STOP_PCT'] = self.risk_daily_stop.value()
        values['AUTO_MAX_TRADES_PER_DAY'] = self.risk_max_trades.value()
        values['AUTO_MIN_POSITION_USD'] = self.risk_min_size.value()
        values['AUTO_MAX_POSITION_USD'] = self.risk_max_size.value()
        values['USE_ADAPTIVE_SIZE'] = self.risk_adaptive_size.isChecked()

        # 3. Применяем в runtime config
        try:
            for k, v in values.items():
                setattr(config, k, v)

            # 4. Сохраняем в config.py
            self._update_config_file(values)

            # 5. Обновляем подсказки
            self._refresh_hints()

            QMessageBox.information(
                self, "Сохранено",
                f"Параметры стратегии «{STRATEGY_LABELS.get(strategy_key)}» "
                f"и общие настройки сохранены в config.py.\n\n"
                f"Перезапустите автобот для применения."
            )
            self.mw.tab_bot.log("💾 Настройки стратегии → config.py",
                                Palette.SUCCESS)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сохранения", str(e))

    def _on_reset(self):
        reply = QMessageBox.question(
            self, "Сброс",
            "Сбросить поля к стандартным значениям?\n\n"
            "config.py не изменится, пока вы не нажмёте «Сохранить».",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        strategy_key = self.combo_strategy.currentData()
        schema = STRATEGY_SCHEMAS.get(strategy_key, [])

        for spec in schema:
            ckey, _, typ, mn, *_ = spec
            default_val = self._defaults.get(ckey)
            if default_val is None:
                continue
            w = self._widgets.get(ckey)
            if w is None:
                continue
            if typ == 'bool':
                w.setChecked(bool(default_val))
            elif typ == 'int':
                w.setValue(int(default_val))
            elif typ == 'float':
                w.setValue(float(default_val))

        # Общие
        self.risk_pct.setValue(self._defaults.get("AUTO_POSITION_PCT", 5.0))
        self.risk_max_lev.setValue(self._defaults.get("MAX_AUTO_LEVERAGE", 2.0))
        self.risk_auto_lev.setChecked(self._defaults.get("USE_AUTO_LEVERAGE", True))
        self.risk_max_pos.setValue(self._defaults.get("MAX_POSITIONS_TOTAL", 4))
        self.risk_daily_stop.setValue(self._defaults.get("AUTO_DAILY_STOP_PCT", 3.0))
        self.risk_max_trades.setValue(self._defaults.get("AUTO_MAX_TRADES_PER_DAY", 15))
        self.risk_min_size.setValue(self._defaults.get("AUTO_MIN_POSITION_USD", 10.0))
        self.risk_max_size.setValue(self._defaults.get("AUTO_MAX_POSITION_USD", 500.0))
        self.risk_adaptive_size.setChecked(self._defaults.get("USE_ADAPTIVE_SIZE", False))

        self._refresh_hints()
        self.mw.tab_bot.log("↺ Поля сброшены к стандарту", Palette.TEXT_DIM)

    def _on_reload(self):
        """Перезагружает значения из текущего config.py."""
        import importlib
        try:
            importlib.reload(config)
        except Exception:
            pass

        self._defaults = self._load_defaults()

        # Обновляем общие
        self.risk_pct.setValue(getattr(config, 'AUTO_POSITION_PCT', 5.0))
        self.risk_max_lev.setValue(getattr(config, 'MAX_AUTO_LEVERAGE', 2.0))
        self.risk_auto_lev.setChecked(getattr(config, 'USE_AUTO_LEVERAGE', True))
        self.risk_max_pos.setValue(getattr(config, 'MAX_POSITIONS_TOTAL', 4))
        self.risk_daily_stop.setValue(getattr(config, 'AUTO_DAILY_STOP_PCT', 3.0))
        self.risk_max_trades.setValue(getattr(config, 'AUTO_MAX_TRADES_PER_DAY', 15))
        self.risk_min_size.setValue(getattr(config, 'AUTO_MIN_POSITION_USD', 10.0))
        self.risk_max_size.setValue(getattr(config, 'AUTO_MAX_POSITION_USD', 500.0))
        self.risk_adaptive_size.setChecked(getattr(config, 'USE_ADAPTIVE_SIZE', False))

        # Обновляем стратегию-параметры
        self._rebuild_params()
        self.mw.tab_bot.log("🔄 Значения перезагружены из config.py",
                            Palette.TEXT_DIM)

    # ============================================================
    # ХЕЛПЕРЫ
    # ============================================================
    def _refresh_hints(self):
        """Обновляет подсказки «сейчас / стандарт» для стратегии."""
        strategy_key = self.combo_strategy.currentData()
        schema = STRATEGY_SCHEMAS.get(strategy_key, [])

        for spec in schema:
            ckey = spec[0]
            row = self._hint_rows.get(ckey)
            if row is None:
                continue
            current = getattr(config, ckey, None)
            default = self._defaults.get(ckey, current)
            row.refresh(current, default)

    def _load_defaults(self):
        import json
        import os
        if os.path.exists("defaults.json"):
            try:
                with open("defaults.json", "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_config_key(self, key, value):
        """Сохраняет одну пару ключ=значение в config.py."""
        self._update_config_file({key: value})

    def _update_config_file(self, values):
        """Безопасно обновляет config.py — заменяет только существующие ключи."""
        import re

        with open('config.py', 'r', encoding='utf-8') as f:
            content = f.read()

        for key, val in values.items():
            safe_key = re.escape(key)

            if isinstance(val, bool):
                new_line = f"{key} = {val}"
            elif isinstance(val, str):
                safe_val = str(val).replace("\\", "\\\\").replace("'", "\\'")
                new_line = f"{key} = '{safe_val}'"
            else:
                new_line = f"{key} = {val}"

            pattern = rf'^{safe_key}\s*=\s*[^\n]+'
            if re.search(pattern, content, flags=re.MULTILINE):
                content = re.sub(pattern, lambda m: new_line,
                                 content, flags=re.MULTILINE)
            else:
                content += f"\n{new_line}\n"

        with open('config.py', 'w', encoding='utf-8') as f:
            f.write(content)