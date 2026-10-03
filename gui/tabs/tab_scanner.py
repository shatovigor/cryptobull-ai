"""
Вкладка «Сканер монет».

Фильтры читаются из config.py и сохраняются туда же.
Кнопка «Сканировать сейчас» запускает ScannerWorker в фоне.
"""
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFormLayout,
    QSpinBox, QDoubleSpinBox, QGroupBox, QTextEdit, QScrollArea,
    QMessageBox,
)
from PyQt6.QtCore import Qt

from ..palette import Palette
from ..widgets import make_button, Card, HintRow
from ..workers import ScannerWorker
import config


class ScannerTab(QWidget):
    def __init__(self, bot, main_window):
        super().__init__()
        self.bot = bot
        self.mw = main_window

        self._worker = None
        self._hint_rows = {}
        self._defaults = self._load_defaults()

        self._build_ui()

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

        # ==== ФИЛЬТРЫ ====
        layout.addWidget(self._build_filter_group())

        # ==== ЧЁРНЫЙ СПИСОК ====
        layout.addWidget(self._build_blacklist_group())

        # ==== КНОПКИ ====
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_save = make_button("💾  Сохранить в config.py", kind='accent')
        self.btn_save.clicked.connect(self._on_save)
        btns.addWidget(self.btn_save)

        self.btn_reset = make_button("↺  Сбросить к стандарту", kind='ghost')
        self.btn_reset.clicked.connect(self._on_reset)
        btns.addWidget(self.btn_reset)

        btns.addStretch()

        self.btn_scan = make_button("🔍  Сканировать сейчас", kind='accent')
        self.btn_scan.clicked.connect(self._on_scan_now)
        btns.addWidget(self.btn_scan)

        layout.addLayout(btns)
        layout.addStretch()

    def _build_filter_group(self):
        group = QGroupBox("Параметры фильтра")
        form = QFormLayout(group)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        specs = [
            ("SCANNER_MAX_PRICE",         "Макс. цена",          'float', 0.001, 1000.0, 0.1, " $"),
            ("SCANNER_MIN_VOLUME_USD",    "Мин. объём 24ч",      'float', 100_000, 10_000_000_000, 1_000_000, " $"),
            ("SCANNER_MIN_ATR_PCT",       "ATR% мин",            'float', 0.5, 50.0, 0.5, " %"),
            ("SCANNER_MAX_ATR_PCT",       "ATR% макс",           'float', 0.5, 50.0, 0.5, " %"),
            ("SCANNER_MIN_CHANGE_PCT",    "Изменение 24ч мин",   'float', 0.1, 50.0, 0.5, " %"),
            ("SCANNER_MAX_CHANGE_PCT",    "Изменение 24ч макс",  'float', 0.1, 100.0, 0.5, " %"),
            ("SCANNER_MIN_DAILY_CANDLES", "Мин. история",        'int',   10, 365, 5, " дн"),
            ("SCANNER_MAX_3DAY_MOVE_PCT", "Макс. движение 3д",   'float', 1.0, 100.0, 1.0, " %"),
            ("SCANNER_TOP_N",             "Топ N монет",         'int',   3, 50, 1, ""),
        ]

        for ckey, label, typ, mn, mx, step, suffix in specs:
            current = getattr(config, ckey, mn)
            default = self._defaults.get(ckey, current)

            if typ == 'int':
                w = QSpinBox()
                w.setRange(int(mn), int(mx))
                w.setSingleStep(int(step) or 1)
                w.setValue(int(current))
            else:
                w = QDoubleSpinBox()
                w.setRange(float(mn), float(mx))
                w.setDecimals(0 if mx > 1000 else 2)
                w.setSingleStep(float(step) or 1.0)
                w.setValue(float(current))

            w.setMinimumWidth(140)
            row = HintRow(w, current, default, suffix)
            form.addRow(label, row)
            self._hint_rows[ckey] = row
            setattr(self, f"_w_{ckey}", w)

        return group

    def _build_blacklist_group(self):
        group = QGroupBox("Чёрный список монет")
        lay = QVBoxLayout(group)
        lay.setSpacing(8)

        info = QLabel(
            "Монеты, которые НИКОГДА не будут добавлены сканером "
            "(по одной на строку). Формат: BASE/USDT:USDT"
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 11px; "
            f"background: transparent;"
        )
        lay.addWidget(info)

        self.txt_blacklist = QTextEdit()
        self.txt_blacklist.setMaximumHeight(160)
        self.txt_blacklist.setStyleSheet(
            f"QTextEdit {{ font-family: 'JetBrains Mono', monospace; "
            f"font-size: 12px; }}"
        )
        current = getattr(config, 'SCANNER_BLACKLIST', [])
        self.txt_blacklist.setPlainText("\n".join(current))
        lay.addWidget(self.txt_blacklist)

        return group

    # ============================================================
    # СОБЫТИЯ
    # ============================================================
    def _on_save(self):
        # Валидация blacklist
        raw = self.txt_blacklist.toPlainText().strip()
        blacklist = [b.strip() for b in raw.split('\n') if b.strip()]

        for b in blacklist:
            if not re.match(r'^[A-Z0-9]+/USDT:USDT$', b):
                QMessageBox.warning(
                    self, "Ошибка формата",
                    f"Неверный формат в чёрном списке:\n  {b}\n\n"
                    f"Ожидается: BASE/USDT:USDT"
                )
                return

        values = {}
        for ckey, row in self._hint_rows.items():
            w = getattr(self, f"_w_{ckey}", None)
            if w is None:
                continue
            values[ckey] = w.value()

        try:
            # Применяем в runtime
            for k, v in values.items():
                setattr(config, k, v)
            config.SCANNER_BLACKLIST = blacklist

            # Пишем в файл
            self._update_config_file(values, blacklist)
            self._refresh_hints()

            QMessageBox.information(
                self, "Сохранено",
                "Фильтры сканера сохранены в config.py."
            )
            self.mw.tab_bot.log("💾 Фильтры сканера → config.py",
                                Palette.SUCCESS)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _on_reset(self):
        reply = QMessageBox.question(
            self, "Сброс",
            "Сбросить фильтры сканера к стандартным?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for ckey, row in self._hint_rows.items():
            w = getattr(self, f"_w_{ckey}", None)
            if w is None:
                continue
            default = self._defaults.get(ckey)
            if default is None:
                continue
            if isinstance(w, QSpinBox):
                w.setValue(int(default))
            else:
                w.setValue(float(default))

        bl = self._defaults.get("SCANNER_BLACKLIST", [])
        self.txt_blacklist.setPlainText("\n".join(bl))

        self._refresh_hints()
        self.mw.tab_bot.log("↺ Фильтры сканера сброшены к стандарту",
                            Palette.TEXT_DIM)

    def _on_scan_now(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.warning(self, "Занято", "Сканирование уже идёт.")
            return

        top_n = getattr(self, "_w_SCANNER_TOP_N").value()

        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("⏳ Сканирую...")

        self._worker = ScannerWorker(top_n=top_n)
        self._worker.log_message.connect(
            lambda msg, color: self.mw.tab_bot.log(msg, color)
        )
        self._worker.finished_ok.connect(self._on_scan_ok)
        self._worker.finished_err.connect(self._on_scan_err)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_scan_ok(self, symbols):
        old_set = set(getattr(config, 'AUTO_SYMBOLS', []))
        new_set = set(symbols)

        added = new_set - old_set
        removed = old_set - new_set

        config.AUTO_SYMBOLS = list(symbols)

        # Обновляем карточку монет в bot-tab
        self.mw.tab_bot._refresh_coins()

        # Логируем изменения
        self.mw.tab_bot.log(
            f"✅ Автоподбор: {len(symbols)} монет", Palette.SUCCESS
        )
        if added:
            self.mw.tab_bot.log(
                f"  + {', '.join(sorted(added))}", Palette.SUCCESS
            )
        if removed:
            self.mw.tab_bot.log(
                f"  − {', '.join(sorted(removed))}", Palette.WARNING
            )

        # Сохраняем AUTO_SYMBOLS в config.py
        try:
            self._save_symbols(symbols)
        except Exception:
            pass

    def _on_scan_err(self, err):
        self.mw.tab_bot.log(f"❌ Сканер: {err}", Palette.DANGER)
        QMessageBox.warning(self, "Ошибка сканера", err)

    def _on_scan_done(self):
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("🔍  Сканировать сейчас")
        self._worker = None

    # ============================================================
    # ХЕЛПЕРЫ
    # ============================================================
    def _load_defaults(self):
        import json, os
        if os.path.exists("defaults.json"):
            try:
                with open("defaults.json", "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _refresh_hints(self):
        for ckey, row in self._hint_rows.items():
            w = getattr(self, f"_w_{ckey}", None)
            if w is None:
                continue
            current = w.value()
            default = self._defaults.get(ckey, current)
            row.refresh(current, default)

    def _update_config_file(self, values, blacklist):
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

        # Blacklist — отдельно (список)
        block = "SCANNER_BLACKLIST = [\n"
        for b in blacklist:
            block += f"    '{b}',\n"
        block += "]"

        content = re.sub(
            r'^SCANNER_BLACKLIST\s*=\s*\[[^\]]*\]',
            block, content,
            flags=re.MULTILINE | re.DOTALL,
        )

        with open('config.py', 'w', encoding='utf-8') as f:
            f.write(content)

    def _save_symbols(self, symbols):
        with open('config.py', 'r', encoding='utf-8') as f:
            content = f.read()

        block = "AUTO_SYMBOLS = [\n"
        for c in symbols:
            block += f"    '{c}',\n"
        block += "]"

        content = re.sub(
            r'^AUTO_SYMBOLS\s*=\s*\[[^\]]*\]',
            block, content,
            flags=re.MULTILINE | re.DOTALL,
        )

        with open('config.py', 'w', encoding='utf-8') as f:
            f.write(content)