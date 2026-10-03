"""
CryptoBullAI — точка входа GUI.

Все компоненты вынесены в пакет gui/. Этот файл — только запуск.
"""
import sys
import os
import traceback

# Корень проекта в sys.path (чтобы gui/ импортировался)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMessageBox


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CryptoBullAI")
    app.setStyle("Fusion")

    # 1. Инициализация бота
    bot = None
    try:
        from auto_trader import AutoTrader
        bot = AutoTrader()
    except Exception as e:
        tb = traceback.format_exc()
        print("=" * 60)
        print("ОШИБКА ИНИЦИАЛИЗАЦИИ AutoTrader:")
        print(tb)
        print("=" * 60)
        QMessageBox.critical(
            None, "Ошибка запуска",
            f"Не удалось инициализировать AutoTrader:\n\n{e}\n\n"
            f"Проверьте:\n"
            f"  1. Файл .env с ключами Bybit\n"
            f"  2. Наличие интернета\n"
            f"  3. Правильность API-ключей"
        )
        sys.exit(1)

    # 2. Главное окно
    try:
        from gui.main_window import MainWindow
        window = MainWindow(bot)
    except Exception as e:
        tb = traceback.format_exc()
        print("=" * 60)
        print("ОШИБКА СОЗДАНИЯ MainWindow:")
        print(tb)
        print("=" * 60)
        QMessageBox.critical(
            None, "Ошибка GUI",
            f"Не удалось создать окно:\n\n{e}\n\n"
            f"Подробности в консоли."
        )
        sys.exit(1)

    # 3. Приветственное сообщение в лог
    try:
        window.tab_bot.log("🤖 CryptoBullAI готов к работе", "#7C5CFF")
        window.tab_bot.log(
            f"Стратегия: {bot.strategy.display_name}",
            "#8B92A0"
        )
        window.tab_bot.log(
            f"Монет: {len(__import__('config').AUTO_SYMBOLS)}",
            "#8B92A0"
        )
    except Exception as e:
        print(f"⚠ Не удалось записать приветствие в лог: {e}")

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()