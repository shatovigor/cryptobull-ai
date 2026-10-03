"""
Вкладка «API».

Позволяет:
  - Ввести и проверить API-ключи
  - Сохранить их в .env
  - Посмотреть текущий статус подключения и баланс
"""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QFormLayout, QGroupBox, QMessageBox,
)
from PyQt6.QtCore import Qt

from ..palette import Palette
from ..widgets import make_button, Card
import config


class ApiTab(QWidget):
    def __init__(self, bot, main_window):
        super().__init__()
        self.bot = bot
        self.mw = main_window

        self._build_ui()
        self._load_current()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        # ==== ИНФО-КАРТОЧКА ====
        info_card = Card(padding=14)
        info_lbl = QLabel(
            "API-ключи Bybit. Создать: bybit.com → Профиль → API Management.\n\n"
            "⚠ Важно: давайте ключу ТОЛЬКО права на торговлю (Trade), "
            "без права вывода (Withdraw)."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 12px; "
            f"background: transparent;"
        )
        info_card.layout().addWidget(info_lbl)
        layout.addWidget(info_card)

        # ==== ФОРМА ====
        form_group = QGroupBox("Ключи")
        form = QFormLayout(form_group)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.input_key = QLineEdit()
        self.input_key.setPlaceholderText("API Key")
        form.addRow("API Key:", self.input_key)

        self.input_secret = QLineEdit()
        self.input_secret.setPlaceholderText("API Secret")
        self.input_secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Secret:", self.input_secret)

        self.chk_testnet = QCheckBox("Использовать Testnet")
        form.addRow("", self.chk_testnet)

        layout.addWidget(form_group)

        # ==== КНОПКИ ====
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_test = make_button("🔍  Проверить подключение", kind='accent')
        self.btn_test.clicked.connect(self._on_test)
        btns.addWidget(self.btn_test)

        self.btn_save = make_button("💾  Сохранить в .env", kind='success')
        self.btn_save.clicked.connect(self._on_save)
        btns.addWidget(self.btn_save)

        btns.addStretch()
        layout.addLayout(btns)

        # ==== СТАТУС ====
        self.lbl_status = QLabel("Статус: не проверено")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(
            f"color: {Palette.TEXT_DIM}; font-size: 12px; "
            f"background: {Palette.BG_PANEL}; padding: 12px 14px; "
            f"border-radius: 8px; border: 1px solid {Palette.BORDER};"
        )
        layout.addWidget(self.lbl_status)

        layout.addStretch()

    def _load_current(self):
        """Загружает текущие ключи (маскированные)."""
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)

            key = os.getenv('BYBIT_API_KEY', '')
            secret = os.getenv('BYBIT_API_SECRET', '')
            testnet = os.getenv('BYBIT_TESTNET', 'False').lower() == 'true'

            if key:
                self.input_key.setText(key)
            if secret:
                self.input_secret.setText(secret)
            self.chk_testnet.setChecked(testnet)

            if key and secret:
                self.lbl_status.setText(
                    f"✅ Ключи загружены из .env "
                    f"(key: {key[:6]}...{key[-4:]})"
                )
                self.lbl_status.setStyleSheet(
                    f"color: {Palette.SUCCESS}; font-size: 12px; "
                    f"background: {Palette.BG_PANEL}; padding: 12px 14px; "
                    f"border-radius: 8px; border: 1px solid {Palette.SUCCESS};"
                )
        except Exception:
            pass

    def _on_test(self):
        key = self.input_key.text().strip()
        secret = self.input_secret.text().strip()

        if not key or not secret:
            QMessageBox.warning(self, "Пусто",
                                "Заполните API Key и API Secret.")
            return

        self.btn_test.setEnabled(False)
        self.btn_test.setText("⏳ Проверка...")
        self.lbl_status.setText("🔍 Проверяю подключение...")

        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            from bybit_client import test_api_keys
            ok, msg = test_api_keys(key, secret, self.chk_testnet.isChecked())
        except Exception as e:
            ok, msg = False, str(e)

        self.lbl_status.setText(f"{'✅' if ok else '❌'}  {msg}")
        self.lbl_status.setStyleSheet(
            f"color: {Palette.SUCCESS if ok else Palette.DANGER}; "
            f"font-size: 12px; "
            f"background: {Palette.BG_PANEL}; padding: 12px 14px; "
            f"border-radius: 8px; "
            f"border: 1px solid {Palette.SUCCESS if ok else Palette.DANGER};"
        )
        self.btn_test.setEnabled(True)
        self.btn_test.setText("🔍  Проверить подключение")

    def _on_save(self):
        key = self.input_key.text().strip()
        secret = self.input_secret.text().strip()

        if not key or not secret:
            QMessageBox.warning(self, "Пусто",
                                "Заполните API Key и API Secret.")
            return

        reply = QMessageBox.question(
            self, "Сохранить",
            "Сохранить ключи в .env?\n\n"
            "⚠ Убедитесь, что .env находится в .gitignore.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            with open('.env', 'w', encoding='utf-8') as f:
                f.write(f"BYBIT_API_KEY={key}\n")
                f.write(f"BYBIT_API_SECRET={secret}\n")
                f.write(f"BYBIT_TESTNET={'True' if self.chk_testnet.isChecked() else 'False'}\n")

            QMessageBox.information(
                self, "Сохранено",
                "Ключи сохранены в .env.\n\n"
                "Перезапустите приложение для применения."
            )
            self.mw.tab_bot.log("🔑 API-ключи обновлены", Palette.WARNING)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))