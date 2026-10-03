"""
Реестр вкладок.
"""

from .tab_bot import BotTab
from .tab_strategy import StrategyTab
from .tab_backtest import BacktestTab
from .tab_scanner import ScannerTab
from .tab_api import ApiTab
from .tab_reports import ReportsTab

__all__ = [
    'BotTab',
    'StrategyTab',
    'BacktestTab',
    'ScannerTab',
    'ApiTab',
    'ReportsTab',
]