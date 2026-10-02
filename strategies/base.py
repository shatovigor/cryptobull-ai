"""
Базовый интерфейс стратегии.

Каждая стратегия получает:
  - trader: объект Trader (доступ к exchange и state)
  - log_fn: callable(msg, color) — для вывода в лог GUI

И возвращает Signal | None из check_symbol().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable


@dataclass
class Signal:
    """Результат проверки одного символа."""
    direction: str                              # "LONG" | "SHORT"
    confidence: float = 1.0                     # 0..1, для логирования
    stop_pct: Optional[float] = None            # % от входа; None → Trader посчитает сам
    take_pct: Optional[float] = None            # % от входа; None → Trader посчитает сам
    leverage: Optional[float] = None            # None → config.DEFAULT_LEVERAGE
    size_usd: Optional[float] = None            # None → AutoTrader посчитает _calc_position_size
    reason: str = ""                            # "PINBAR", "BOUNCE", "AML p=0.72"
    meta: dict = field(default_factory=dict)    # signal_type, touches, atr_pct, trend, features...


class StrategyBase(ABC):
    name: str = "base"
    display_name: str = "Base"

    def __init__(self, trader, log_fn: Callable[[str, str], None]):
        self.trader = trader
        self._log = log_fn

    @abstractmethod
    def check_symbol(self, symbol: str, free_balance: float) -> Optional[Signal]:
        """
        Проверить один символ. Вернуть Signal или None.

        Параметры:
            symbol: 'LIT/USDT:USDT'
            free_balance: доступный USDT-баланс
        """
        ...

    def on_trade_closed(self, trade: dict) -> None:
        """
        Хук: сделка закрыта.

        trade = {
            'symbol', 'side', 'entry', 'exit', 'usd_size',
            'pnl_pct', 'pnl_usd', 'open_ts', 'exit_ts',
            'signal_type', 'touches', 'atr_pct', 'trend',
            'distance_to_level_pct',
            'features': <features на момент входа | None>
        }

        Используется adaptive_ml для онлайн-обучения.
        """
        pass

    @classmethod
    def params_schema(cls) -> list:
        """
        Список параметров для GUI.

        Формат: (config_key, label, type, default, min, max, step)
            type: 'float' | 'int' | 'bool' | 'str'
        """
        return []

    def describe(self) -> str:
        return self.display_name