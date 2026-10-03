"""
CryptoBullAI — GUI-пакет.

Модульная структура:
  - palette   — единая тема (цвета, шрифты)
  - widgets   — переиспользуемые UI-компоненты
  - workers   — фоновые потоки (сканирование, бэктест)
  - main_window — главное окно
  - tabs/*    — вкладки
"""

from .palette import Palette, build_stylesheet
from .widgets import (
    HintRow, StatCard, LoadingButton,
    Card, SectionTitle, make_button,
)
from .workers import (
    ScannerWorker, BacktestWorker, CompareWorker,
    SyncWorker, ManualOpenWorker,
)

__all__ = [
    'Palette', 'build_stylesheet',
    'HintRow', 'StatCard', 'LoadingButton',
    'Card', 'SectionTitle', 'make_button',
    'ScannerWorker', 'BacktestWorker', 'CompareWorker',
    'SyncWorker', 'ManualOpenWorker',
]