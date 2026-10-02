"""
Пакет стратегий для CryptoBullAI.

Каждая стратегия — класс, унаследованный от StrategyBase.
Реестр STRATEGIES связывает ключ → класс.
"""

from .base import StrategyBase, Signal
from .registry import STRATEGIES, get_strategy, list_strategies

__all__ = [
    "StrategyBase",
    "Signal",
    "STRATEGIES",
    "get_strategy",
    "list_strategies",
]