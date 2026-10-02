# Настройки торговли.
# Полная версия с GUI-параметрами + адаптивный стоп по ATR.

# === ОБЩИЕ ===
TIMEFRAME_DAILY = '1d'
TIMEFRAME_M15 = '15m'
LOOKBACK_DAYS = 90

# === УРОВНИ ===
MAX_DISTANCE_PCT = 15.0
CLUSTER_PCT = 0.6
MIN_TOUCHES = 4
MAX_LEVEL_AGE_DAYS = 21

# === СИГНАЛЫ ===
NEAR_LEVEL_PCT = 0.8
PINBAR_SHADOW_RATIO = 2.0
MIN_SHADOW_PCT = 0.15
USE_BOUNCE_SIGNAL = True
LOOKBACK_CANDLES = 3

# === ОБЩИЕ СДЕЛКИ ===
LEVERAGE = 2
MAX_POSITION_USD = 10
RISK_PER_TRADE_PCT = 2.0
DAILY_LOSS_LIMIT_PCT = 5.0
MAX_TRADES_PER_DAY = 15

# === ИЗДЕРЖКИ ===
COMMISSION_PCT = 0.055
SLIPPAGE_PCT = 0.01

# === ФАЙЛЫ ===
TRADES_LOG = 'trades.log'
STATE_FILE = 'bot_state.json'
HISTORY_FILE = 'trade_history.json'

# === АВТОБОТ (общие) ===
AUTO_MIN_POSITION_USD = 10.0
AUTO_MAX_POSITION_USD = 10000.0
AUTO_MAX_TRADES_PER_DAY = 15
AUTO_DAILY_STOP_PCT = 3.0
AUTO_CHECK_INTERVAL_SEC = 60
AUTO_MIN_FREE_BALANCE = 50.0
AUTO_MAX_CONSECUTIVE_ERRORS = 3

# === ИНТЕРФЕЙС ===
THEME = "dark"
SOUND_ON_SIGNAL = True

# === GUI ===
CALENDAR_DAYS = 30
DAILY_REPORT_ENABLED = True
DAILY_REPORT_HOUR = 23
DAILY_REPORT_MINUTE = 0

# === КРЕДИТНОЕ ПЛЕЧО ===
USE_AUTO_LEVERAGE = True
MAX_AUTO_LEVERAGE = 5.0
DEFAULT_LEVERAGE = 2.0

# === МУЛЬТИ-ТАЙМФРЕЙМ ===
USE_MULTI_TF = True
LEVELS_TIMEFRAME = '1d'

MTF_CONFIG = {
    '15m': {
        'enabled': True,
        'size_pct': 3.0,
        'cooldown_min': 30,
        'max_positions': 2,
        'stop_pct': 1.5,
        'take_pct': 3.0,
        'trailing_start': 1.5,
        'trailing_step': 0.5,
        'check_candles': 100,
    },
    '1h': {
        'enabled': True,
        'size_pct': 5.0,
        'cooldown_min': 120,
        'max_positions': 2,
        'stop_pct': 2.5,
        'take_pct': 5.0,
        'trailing_start': 2.0,
        'trailing_step': 0.5,
        'check_candles': 100,
    },
}

MTF_MAX_TOTAL_POSITIONS = 4
MTF_TIMEFRAMES = ['15m', '1h']

# === MTF для сигналов (используется в auto_trader.py) ===
USE_MULTI_TIMEFRAME = True
MTF_WEIGHT_DAILY = 0.4
MTF_WEIGHT_4H = 0.3
MTF_WEIGHT_15M = 0.3

# === СТАРЫЕ НАСТРОЙКИ СДЕЛОК ===
STOP_PCT_CALM = 2.5
STOP_PCT_VOLATILE = 3.5
TAKE_PCT_CALM = 5.0
TAKE_PCT_VOLATILE = 6.0
VOLATILITY_THRESHOLD = 3.0
USE_TREND_FILTER = True
USE_4H_TREND_FILTER = True
COOLDOWN_MINUTES = 120

# === СТАРЫЙ АВТОБОТ ===
AUTO_POSITION_PCT = 15.0
MAX_POSITIONS_TOTAL = 4

# === АДАПТИВНЫЙ СТОП ПО ATR ===
USE_ADAPTIVE_STOP = True
ADAPTIVE_STOP_ATR_MULT = 0.6
ADAPTIVE_TAKE_ATR_MULT = 1.2
ADAPTIVE_STOP_MIN_PCT = 1.5
ADAPTIVE_STOP_MAX_PCT = 8.0
ADAPTIVE_TAKE_MIN_PCT = 3.0
ADAPTIVE_TAKE_MAX_PCT = 16.0

# === TRAILING ===
USE_TRAILING_STOP = False
TRAILING_START_PCT = 4.0
TRAILING_STEP_PCT = 1.0
TRAILING_UPDATE_SEC = 60

# === АДАПТИВНЫЙ РАЗМЕР ===
USE_ADAPTIVE_SIZE = True
ADAPTIVE_ATR_LOW = 5.0
ADAPTIVE_ATR_HIGH = 12.0
ADAPTIVE_SIZE_MIN_PCT = 3.0
ADAPTIVE_SIZE_MAX_PCT = 8.0

# === АВТОУПРАВЛЕНИЕ МОНЕТАМИ ===
AUTO_MANAGE_COINS = True
COIN_ANALYSIS_HOURS = 6
COIN_MIN_TRADES = 5
COIN_MIN_PNL_PCT = -3.0
COIN_CONSECUTIVE_LOSSES = 3
COIN_EXCLUDE_DAYS = 7
COIN_MIN_COUNT = 5
COIN_MAX_COUNT = 15

# === ПИРАМИДИНГ И ХЕДЖ ===
USE_PYRAMIDING = False
PYRAMID_START_PCT = 2.0
PYRAMID_STEP_PCT = 2.0
PYRAMID_MAX_ADD = 2

USE_HEDGING = False
HEDGE_TRIGGER_PCT = -2.5
HEDGE_SIZE_RATIO = 0.5

# === BACKTEST GUI PRESETS ===
BACKTEST_DEFAULT_DAYS = 14

# === СПИСОК МОНЕТ ===
AUTO_SYMBOLS = [
    'LIT/USDT:USDT',
    'FARTCOIN/USDT:USDT',
    'APT/USDT:USDT',
    'AERO/USDT:USDT',
    '1000PEPE/USDT:USDT',
    'TRUMP/USDT:USDT',
    'XLM/USDT:USDT',
]

# ============================================
# ФИЛЬТРЫ СКАНЕРА МОНЕТ
# ============================================
SCANNER_MAX_PRICE = 5.0
SCANNER_MIN_VOLUME_USD = 15000000.0
SCANNER_MIN_ATR_PCT = 6.0
SCANNER_MAX_ATR_PCT = 11.0
SCANNER_MIN_CHANGE_PCT = 2.0
SCANNER_MAX_CHANGE_PCT = 15.0
SCANNER_MIN_DAILY_CANDLES = 90
SCANNER_MAX_3DAY_MOVE_PCT = 20.0
SCANNER_TOP_N = 10

SCANNER_BLACKLIST = [
    'WLD/USDT:USDT',
    'LDO/USDT:USDT',
    'ICP/USDT:USDT',
    'DOT/USDT:USDT',
    'VIRTUAL/USDT:USDT',
    'ADA/USDT:USDT',
]

# Автоскан раз в N часов
SCANNER_AUTO_ENABLED = True
SCANNER_AUTO_HOURS = 6

# ============================================
# АКТИВНАЯ СТРАТЕГИЯ
# ============================================
# 'classic_levels' | 'adaptive_ml'
ACTIVE_STRATEGY = 'trendrider'

# === ADAPTIVE ML (используется когда ACTIVE_STRATEGY = 'adaptive_ml') ===
AML_UPDATE_INTERVAL = 50        # сделок до обновления онлайн-модели
AML_CONF_THRESHOLD = 0.65       # порог уверенности для входа
AML_MIN_MOVE_PCT = 0.35         # минимальное ожидаемое движение, %
AML_KELLY_FRACTION = 0.25       # доля Kelly
AML_MAX_LEVERAGE = 3.0          # макс. плечо для AML
AML_MAX_SIZE_PCT = 0.15         # макс. размер позиции, доля от баланса
AML_STOP_ATR_MULT = 2.0         # стоп = ATR × этот множитель
AML_TAKE_ATR_MULT = 4.0         # тейк = ATR × этот множитель
AML_MODEL_DIR = 'storage/models/adaptive'   # куда сохранять онлайн-модели

SCANNER_BLACKLIST = [
    'WLD/USDT:USDT',
    'LDO/USDT:USDT',
    'ICP/USDT:USDT',
    'DOT/USDT:USDT',
    'VIRTUAL/USDT:USDT',
    'ADA/USDT:USDT',
]
# ============================================
# TRENDRIDER
# ============================================
TREND_TIMEFRAME          = '1h'     # TF, на котором считаются индикаторы TrendRider
TREND_EMA_FAST           = 9
TREND_EMA_SLOW           = 16
TREND_RSI_PERIOD         = 14
TREND_RSI_PULLBACK_LOW   = 40
TREND_RSI_PULLBACK_HIGH  = 58
TREND_RSI_BOUNCE         = 30
TREND_RSI_EXIT           = 78
TREND_ADX_THRESHOLD      = 25
TREND_VOLUME_FACTOR      = 1.3
TREND_MIN_CONF           = 5        # 0..10, порог для входа (bull)
TREND_MIN_CONF_BEAR      = 6        # порог в bear-режиме
TREND_BTC_CACHE_SEC      = 300      # кэш BTC-данных, сек