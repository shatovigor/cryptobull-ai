"""
Реестр стратегий.
"""

from .classic_levels import ClassicLevelsStrategy
from .adaptive_ml import AdaptiveMLStrategy
from .trendrider import TrendRiderStrategy


STRATEGIES = {
    "classic_levels": ClassicLevelsStrategy,
    "adaptive_ml":    AdaptiveMLStrategy,
    "trendrider":     TrendRiderStrategy,
}


def get_strategy(name: str, trader, log_fn):
    cls = STRATEGIES.get(name)
    if not cls:
        raise ValueError(
            f"Unknown strategy: {name!r}. Доступные: {list(STRATEGIES.keys())}"
        )
    return cls(trader, log_fn)


def list_strategies():
    """[('classic_levels', '📊 Уровни + паттерны'), ...]"""
    return [(k, cls.display_name) for k, cls in STRATEGIES.items()]