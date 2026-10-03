"""Создаёт структуру gui/ с пустыми файлами."""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

files = [
    "gui/__init__.py",
    "gui/palette.py",
    "gui/widgets.py",
    "gui/workers.py",
    "gui/main_window.py",
    "gui/tabs/__init__.py",
    "gui/tabs/tab_bot.py",
    "gui/tabs/tab_strategy.py",
    "gui/tabs/tab_backtest.py",
    "gui/tabs/tab_scanner.py",
    "gui/tabs/tab_api.py",
    "gui/tabs/tab_reports.py",
]

for rel in files:
    path = os.path.join(BASE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
        print(f"✅ создан: {rel}")
    else:
        print(f"⏭  уже есть: {rel}")

print("\nГотово! Теперь вставь код в каждый файл.")