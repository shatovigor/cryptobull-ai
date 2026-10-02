"""
Стратегия "Уровни + паттерны".

Обёртка над текущей логикой auto_trader.py.
Поведение не меняется — просто инкапсулировано в класс StrategyBase.
"""

from datetime import datetime, timezone
import numpy as np
import pandas as pd

from .base import StrategyBase, Signal
import config


class ClassicLevelsStrategy(StrategyBase):
    name = "classic_levels"
    display_name = "📊 Уровни + паттерны"

    def __init__(self, trader, log_fn):
        super().__init__(trader, log_fn)
        self.levels_cache = {}
        self.levels_cache_hours = 4
        self._last_mtf = {}

    # ============================================================
    # СВЕЧИ
    # ============================================================
    def _fetch_candles(self, symbol, timeframe, limit):
        raw = self.trader.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df

    # ============================================================
    # УРОВНИ
    # ============================================================
    def _get_levels(self, symbol):
        now = datetime.now(timezone.utc)
        if symbol in self.levels_cache:
            cached = self.levels_cache[symbol]
            age = (now - cached['ts']).total_seconds() / 3600
            if age < self.levels_cache_hours:
                return cached['levels'], cached['trend'], cached['atr']

        df = self._fetch_candles(symbol, '1d', config.LOOKBACK_DAYS)

        points = []
        for i in range(len(df)):
            points.append({'price': df['high'].iloc[i], 'ts': df['ts'].iloc[i]})
            points.append({'price': df['low'].iloc[i], 'ts': df['ts'].iloc[i]})
        points.sort(key=lambda x: x['price'])

        clusters = []
        cur = [points[0]]
        for p in points[1:]:
            if abs(p['price'] - cur[-1]['price']) / cur[-1]['price'] * 100 < config.CLUSTER_PCT:
                cur.append(p)
            else:
                clusters.append(cur)
                cur = [p]
        clusters.append(cur)

        levels = []
        for c in clusters:
            if len(c) < config.MIN_TOUCHES:
                continue
            levels.append({
                'price': np.mean([p['price'] for p in c]),
                'touches': len(c),
                'last_ts': max(p['ts'] for p in c),
            })

        trend = 'UP' if df['close'].iloc[-1] > df['close'].rolling(20).mean().iloc[-1] else 'DOWN'
        atr_pct = ((df['high'] - df['low']) / df['close'] * 100).tail(20).mean()

        self.levels_cache[symbol] = {
            'levels': levels, 'trend': trend, 'atr': atr_pct, 'ts': now,
        }
        return levels, trend, atr_pct

    # ============================================================
    # MTF
    # ============================================================
    def _check_multi_timeframe(self, symbol):
        if not getattr(config, 'USE_MULTI_TIMEFRAME', False):
            return None

        timeframes = getattr(config, 'MTF_TIMEFRAMES', ['1d', '4h', '15m'])
        weights = {
            '1d': getattr(config, 'MTF_WEIGHT_DAILY', 0.4),
            '4h': getattr(config, 'MTF_WEIGHT_4H', 0.3),
            '15m': getattr(config, 'MTF_WEIGHT_15M', 0.3),
        }

        signals = {}
        score = 0

        for tf in timeframes:
            try:
                df = self._fetch_candles(symbol, tf, 30)
                if len(df) < 20:
                    continue
                price = df['close'].iloc[-1]
                sma = df['close'].rolling(10).mean().iloc[-1]
                trend = 'UP' if price > sma else 'DOWN'
                signals[tf] = trend
                if trend == 'UP':
                    score += weights.get(tf, 0.3)
                else:
                    score -= weights.get(tf, 0.3)
            except Exception:
                continue

        return signals, score

    # ============================================================
    # ПАТТЕРНЫ
    # ============================================================
    def _is_bullish_pinbar(self, c):
        body = abs(c['close'] - c['open'])
        total = c['high'] - c['low']
        if total == 0:
            return False
        lower = min(c['open'], c['close']) - c['low']
        upper = c['high'] - max(c['open'], c['close'])
        bs = max(body, total * 0.05)
        return (lower >= bs * config.PINBAR_SHADOW_RATIO
                and upper <= bs * 0.5
                and lower / c['close'] * 100 >= config.MIN_SHADOW_PCT)

    def _is_bearish_pinbar(self, c):
        body = abs(c['close'] - c['open'])
        total = c['high'] - c['low']
        if total == 0:
            return False
        lower = min(c['open'], c['close']) - c['low']
        upper = c['high'] - max(c['open'], c['close'])
        bs = max(body, total * 0.05)
        return (upper >= bs * config.PINBAR_SHADOW_RATIO
                and lower <= bs * 0.5
                and upper / c['close'] * 100 >= config.MIN_SHADOW_PCT)

    def _price_from_above(self, df, i, lp):
        for j in range(max(0, i - config.LOOKBACK_CANDLES), i):
            if df['close'].iloc[j] > lp * 1.002:
                return True
        return False

    def _price_from_below(self, df, i, lp):
        for j in range(max(0, i - config.LOOKBACK_CANDLES), i):
            if df['close'].iloc[j] < lp * 0.998:
                return True
        return False

    def _is_bounce_long(self, df, i, lp):
        c = df.iloc[i]
        return (c['low'] <= lp * 1.001 and c['close'] > lp and c['close'] > c['open']
                and self._price_from_above(df, i, lp))

    def _is_bounce_short(self, df, i, lp):
        c = df.iloc[i]
        return (c['high'] >= lp * 0.999 and c['close'] < lp and c['close'] < c['open']
                and self._price_from_below(df, i, lp))

    # ============================================================
    # ГЛАВНЫЙ МЕТОД
    # ============================================================
    def check_symbol(self, symbol, free_balance):
        levels, trend, atr_cached = self._get_levels(symbol)
        if not levels:
            return None

        df = self._fetch_candles(symbol, config.TIMEFRAME_M15, 50)
        i = len(df) - 2
        c = df.iloc[i]
        price = c['close']
        ts = c['ts']

        near = [l for l in levels
                if abs(l['price'] - price) / price * 100 <= config.NEAR_LEVEL_PCT
                and (ts - l['last_ts']).days <= config.MAX_LEVEL_AGE_DAYS]
        if not near:
            return None

        nearest = min(near, key=lambda x: abs(x['price'] - price))
        is_support = nearest['price'] < price

        side = None
        sig_type = None

        if is_support:
            if self._is_bullish_pinbar(c):
                side, sig_type = 'LONG', 'PINBAR'
            elif config.USE_BOUNCE_SIGNAL and self._is_bounce_long(df, i, nearest['price']):
                side, sig_type = 'LONG', 'BOUNCE'
        else:
            if self._is_bearish_pinbar(c):
                side, sig_type = 'SHORT', 'PINBAR'
            elif config.USE_BOUNCE_SIGNAL and self._is_bounce_short(df, i, nearest['price']):
                side, sig_type = 'SHORT', 'BOUNCE'

        if not side:
            return None

        # MTF-фильтр
        if getattr(config, 'USE_MULTI_TIMEFRAME', False):
            mtf = self._check_multi_timeframe(symbol)
            if mtf:
                signals, score = mtf
                self._last_mtf[symbol] = (signals, score)
                self._log(f"   MTF {symbol}: {signals}, score={score:+.2f}", "#888")
                if side == 'LONG' and score < 0:
                    self._log(f"   ⚠ MTF против LONG, пропуск", "#ff9800")
                    return None
                if side == 'SHORT' and score > 0:
                    self._log(f"   ⚠ MTF против SHORT, пропуск", "#ff9800")
                    return None

        # 4h-фильтр тренда
        if getattr(config, 'USE_4H_TREND_FILTER', True):
            try:
                df_4h = self._fetch_candles(symbol, '4h', 30)
                if len(df_4h) >= 10:
                    price_4h = df_4h['close'].iloc[-1]
                    sma_4h = df_4h['close'].rolling(10).mean().iloc[-1]
                    trend_4h = 'UP' if price_4h > sma_4h else 'DOWN'

                    if side == 'LONG' and trend_4h == 'DOWN':
                        self._log(f"   ⚠ 4h вниз против LONG, пропуск", "#ff9800")
                        return None
                    if side == 'SHORT' and trend_4h == 'UP':
                        self._log(f"   ⚠ 4h вверх против SHORT, пропуск", "#ff9800")
                        return None
            except Exception:
                pass

        distance_pct = abs(nearest['price'] - price) / price * 100

        return Signal(
            direction=side,
            confidence=1.0,
            stop_pct=None,       # Trader посчитает через адаптивный ATR
            take_pct=None,
            leverage=None,       # AutoTrader посчитает через calc_leverage
            size_usd=None,       # AutoTrader посчитает через _calc_position_size
            reason=sig_type,
            meta={
                'signal_type': sig_type,
                'level_price': nearest['price'],
                'touches': nearest['touches'],
                'atr_pct': atr_cached,
                'trend': trend,
                'distance_to_level_pct': distance_pct,
                'price': price,
            },
        )

    @classmethod
    def params_schema(cls):
        # Все параметры уже в основной вкладке "Настройки".
        return []