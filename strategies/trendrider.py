"""
TrendRider Strategy — порт с Freqtrade-стратегии darkvolg/trendrider-strategy.

Что внутри:
  - 6 разных LONG-сигналов (pullback, ema50_bounce, rsi_bounce, ema_cross, bb_bounce, macd_reversal)
  - Confidence score (0..10) на базе 11 пунктов, порог: 5 (bull) / 6 (bear)
  - MTF: 4h + 1d + BTC-сентимент (RSI и is_bull)
  - Стоп/тейк через ATR (передаём None — Trader посчитает сам)

ДОБАВЛЕНО: метод evaluate_at() для бэктеста — работает БЕЗ сети,
на переданном DataFrame. BTC/4h/1d контекст в бэктесте нейтральный.
"""

from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

from .base import StrategyBase, Signal
import config


class TrendRiderStrategy(StrategyBase):
    name = "trendrider"
    display_name = "📈 TrendRider"

    def __init__(self, trader, log_fn):
        super().__init__(trader, log_fn)

        self.tf = getattr(config, 'TREND_TIMEFRAME', '1h')
        self.ema_fast = getattr(config, 'TREND_EMA_FAST', 9)
        self.ema_slow = getattr(config, 'TREND_EMA_SLOW', 16)
        self.rsi_period = getattr(config, 'TREND_RSI_PERIOD', 14)
        self.rsi_pl = getattr(config, 'TREND_RSI_PULLBACK_LOW', 40)
        self.rsi_ph = getattr(config, 'TREND_RSI_PULLBACK_HIGH', 58)
        self.rsi_bounce = getattr(config, 'TREND_RSI_BOUNCE', 30)
        self.adx_th = getattr(config, 'TREND_ADX_THRESHOLD', 25)
        self.vol_factor = getattr(config, 'TREND_VOLUME_FACTOR', 1.3)
        self.min_conf = getattr(config, 'TREND_MIN_CONF', 5)
        self.min_conf_bear = getattr(config, 'TREND_MIN_CONF_BEAR', 6)

        self._btc_cache = {'ts': None, 'rsi': 50.0, 'is_bull': 1}
        self._mtf_cache = {}

    # ============================================================
    # СВЕЧИ
    # ============================================================
    def _fetch(self, symbol, timeframe, limit):
        raw = self.trader.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df

    # ============================================================
    # ИНДИКАТОРЫ
    # ============================================================
    @staticmethod
    def _ema(s, period):
        return s.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _rsi(close, period):
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = -delta.where(delta < 0, 0).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - 100 / (1 + rs)

    @staticmethod
    def _atr(df, period=14):
        hl = df['high'] - df['low']
        hc = (df['high'] - df['close'].shift()).abs()
        lc = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def _adx(df, period=14):
        up = df['high'].diff()
        down = -df['low'].diff()
        plus_dm = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)

        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs(),
        ], axis=1).max(axis=1)

        atr = tr.rolling(period).mean()
        plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr.replace(0, np.nan)
        minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.rolling(period).mean()

        return adx, plus_di, minus_di

    @staticmethod
    def _macd(close):
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        return macd, signal, hist

    @staticmethod
    def _bb(close, period=20, std=2.0):
        m = close.rolling(period).mean()
        s = close.rolling(period).std()
        return m + std * s, m, m - std * s

    # ============================================================
    # BTC SENTIMENT (LIVE ONLY)
    # ============================================================
    def _btc_sentiment(self):
        now = datetime.now(timezone.utc)
        cache_sec = getattr(config, 'TREND_BTC_CACHE_SEC', 300)

        if self._btc_cache['ts'] is not None:
            age = (now - self._btc_cache['ts']).total_seconds()
            if age < cache_sec:
                return self._btc_cache['rsi'], self._btc_cache['is_bull']

        try:
            df = self._fetch('BTC/USDT:USDT', self.tf, 210)
            if len(df) < 60:
                return 50.0, 1

            rsi = self._rsi(df['close'], 14).iloc[-1]
            ema50 = self._ema(df['close'], 50).iloc[-1]
            ema200 = self._ema(df['close'], 200).iloc[-1]
            close = df['close'].iloc[-1]
            is_bull = 1 if (close > ema200 and ema50 > ema200) else 0

            self._btc_cache = {
                'ts': now,
                'rsi': float(rsi) if not np.isnan(rsi) else 50.0,
                'is_bull': is_bull,
            }
        except Exception as e:
            self._log(f"⚠ TrendRider BTC: {str(e)[:60]}", "#ff9800")

        return self._btc_cache['rsi'], self._btc_cache['is_bull']

    # ============================================================
    # MTF (LIVE ONLY)
    # ============================================================
    def _mtf_context(self, symbol):
        try:
            df4 = self._fetch(symbol, '4h', 210)
            if len(df4) < 60:
                is_bull_4h, rsi_4h, adx_4h = 0, 50.0, 0.0
            else:
                ema50 = self._ema(df4['close'], 50).iloc[-1]
                ema200 = self._ema(df4['close'], 200).iloc[-1]
                close = df4['close'].iloc[-1]
                is_bull_4h = 1 if (close > ema200 and ema50 > ema200) else 0
                rsi_4h = self._rsi(df4['close'], 14).iloc[-1]
                adx_4h, _, _ = self._adx(df4, 14)
                adx_4h = adx_4h.iloc[-1]

            df1 = self._fetch(symbol, '1d', 210)
            if len(df1) < 200:
                ema200_1d = 0.0
            else:
                ema200_1d = self._ema(df1['close'], 200).iloc[-1]

            return {
                'is_bull_4h': int(is_bull_4h) if not np.isnan(is_bull_4h) else 0,
                'rsi_4h':    float(rsi_4h)    if not np.isnan(rsi_4h)    else 50.0,
                'adx_4h':    float(adx_4h)    if not np.isnan(adx_4h)    else 0.0,
                'ema200_1d': float(ema200_1d) if not np.isnan(ema200_1d) else 0.0,
            }
        except Exception as e:
            self._log(f"⚠ TrendRider MTF {symbol}: {str(e)[:60]}", "#ff9800")
            return {'is_bull_4h': 0, 'rsi_4h': 50.0, 'adx_4h': 0.0, 'ema200_1d': 0.0}

    # ============================================================
    # МЕТРИКИ ПОСЛЕДНЕГО БАРА
    # ============================================================
    def _compute_indicators(self, df):
        close = df['close']

        ema_f = self._ema(close, self.ema_fast)
        ema_s = self._ema(close, self.ema_slow)
        ema50 = self._ema(close, 50)
        ema200 = self._ema(close, 200)

        rsi = self._rsi(close, self.rsi_period)
        rsi_series = self._rsi(close, self.rsi_period)
        adx, plus_di, minus_di = self._adx(df, 14)
        macd, macd_sig, macd_hist = self._macd(close)
        bb_u, bb_m, bb_l = self._bb(close, 20, 2.0)

        vol_ema = self._ema(df['volume'], 20)
        vol_ratio = df['volume'] / vol_ema.replace(0, np.nan)

        obv = (np.sign(close.diff()).fillna(0) * df['volume']).cumsum()
        obv_ema = self._ema(obv, 20)

        atr = self._atr(df, 14)
        bb_width = (bb_u - bb_l) / (bb_m.replace(0, np.nan))
        bb_width_sma = bb_width.rolling(50).mean()

        is_bull = ((close > ema200) & (ema50 > ema200)).astype(int)
        is_bear = ((close < ema200) & (ema50 < ema200)).astype(int)

        pullback_to_ema = (
            (df['low'] <= ema_s * 1.02) &
            (close > ema_s) &
            (close > df['open'])
        ).astype(int)

        ema50_bounce = (
            (df['low'] <= ema50 * 1.01) &
            (close > ema50) &
            (close > df['open'])
        ).astype(int)

        ema_cross_up = (
            (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
        )

        macd_hist_cross_up = (macd_hist > 0) & (macd_hist.shift(1) <= 0)
        rsi_prev = rsi_series.shift(1)

        last = {
            'close': close.iloc[-1],
            'open':  df['open'].iloc[-1],
            'low':   df['low'].iloc[-1],
            'volume': df['volume'].iloc[-1],

            'ema_f': ema_f.iloc[-1],
            'ema_s': ema_s.iloc[-1],
            'ema50': ema50.iloc[-1],
            'ema200': ema200.iloc[-1],

            'rsi': rsi.iloc[-1],
            'rsi_prev': rsi_prev.iloc[-1],

            'adx': adx.iloc[-1],
            'plus_di': plus_di.iloc[-1],
            'minus_di': minus_di.iloc[-1],

            'macd_hist': macd_hist.iloc[-1],
            'macd_hist_prev': macd_hist.shift(1).iloc[-1],

            'bb_upper': bb_u.iloc[-1],
            'bb_lower': bb_l.iloc[-1],
            'bb_width': bb_width.iloc[-1],
            'bb_width_sma': bb_width_sma.iloc[-1],

            'vol_ratio': vol_ratio.iloc[-1] if not np.isnan(vol_ratio.iloc[-1]) else 0.0,
            'obv': obv.iloc[-1],
            'obv_ema': obv_ema.iloc[-1],
            'atr': atr.iloc[-1],

            'is_bull': int(is_bull.iloc[-1]),
            'is_bear': int(is_bear.iloc[-1]),

            'pullback_to_ema': int(pullback_to_ema.iloc[-1]),
            'ema50_bounce': int(ema50_bounce.iloc[-1]),

            'ema_cross_up': int(ema_cross_up.iloc[-1]),
            'macd_hist_cross_up': int(macd_hist_cross_up.iloc[-1]),
        }
        for k, v in last.items():
            if isinstance(v, float) and np.isnan(v):
                last[k] = 0.0
        return last

    # ============================================================
    # 6 СИГНАЛОВ
    # ============================================================
    def _signals(self, m, ctx, btc_rsi, btc_bull):
        rsi = m['rsi']
        adx = m['adx']
        vol = m['vol_ratio']
        close = m['close']
        ema200 = m['ema200']
        plus_di = m['plus_di']
        minus_di = m['minus_di']
        obv = m['obv']
        obv_ema = m['obv_ema']
        bb_u = m['bb_upper']
        bb_l = m['bb_lower']
        macd_hist = m['macd_hist']
        macd_hist_prev = m['macd_hist_prev']
        is_bull = m['is_bull']
        ema_cross_up = m['ema_cross_up']
        macd_cross = m['macd_hist_cross_up']

        found = []

        if (is_bull == 1
            and m['pullback_to_ema'] == 1
            and self.rsi_pl < rsi < self.rsi_ph
            and adx > self.adx_th
            and vol > self.vol_factor
            and plus_di > minus_di
            and obv > obv_ema
            and btc_rsi > 35
            and rsi < 70
            and (ctx['ema200_1d'] == 0 or close > ctx['ema200_1d'])):
            found.append('trend_pullback')

        if (is_bull == 1
            and m['ema50_bounce'] == 1
            and 30 < rsi < 50
            and adx > 20
            and vol > 1.0
            and macd_hist > macd_hist_prev
            and btc_rsi > 35):
            found.append('ema50_bounce')

        if (close > ema200
            and m['rsi_prev'] < self.rsi_bounce
            and rsi > self.rsi_bounce
            and close > bb_l
            and close > m['open']
            and vol > 0.8
            and obv > obv_ema
            and btc_rsi > 35):
            found.append('rsi_bounce')

        if (ema_cross_up == 1
            and 40 < rsi < 75
            and close > ema200
            and vol > 0.5
            and btc_rsi > 35):
            found.append('ema_crossover')

        if (bb_l > 0 and close <= bb_l * 1.005
            and close > m['open']
            and rsi < 45
            and vol > 0.7
            and adx > 18
            and btc_rsi > 35):
            found.append('bb_bounce')

        if (macd_cross == 1
            and close > m['ema50']
            and close > ema200
            and 40 < rsi < 60
            and adx > 15
            and vol > 0.8
            and btc_rsi > 35):
            found.append('macd_reversal')

        return found

    # ============================================================
    # CONFIDENCE
    # ============================================================
    def _confidence(self, m, ctx, btc_rsi):
        score = 0.0
        rsi = m['rsi']
        adx = m['adx']
        vol = m['vol_ratio']
        macd_hist = m['macd_hist']
        macd_hist_prev = m['macd_hist_prev']
        plus_di = m['plus_di']
        minus_di = m['minus_di']
        close = m['close']
        bb_u = m['bb_upper']
        bb_l = m['bb_lower']

        if 35 < rsi < 60:
            score += 1.5

        if adx > 30:
            score += 2.5
        elif adx > self.adx_th:
            score += 1.5

        if vol > 1.5:
            score += 2.5
        elif vol > 1.0:
            score += 1.5

        if macd_hist > 0:
            score += 1.5
            if macd_hist > macd_hist_prev:
                score += 0.5

        if m['obv'] > m['obv_ema']:
            score += 1.5

        if 40 < btc_rsi < 70:
            score += 1.5

        if ctx['is_bull_4h'] == 1 and ctx['adx_4h'] > 20:
            score += 1.5

        bb_range = bb_u - bb_l if bb_u > bb_l else 0.0
        if bb_l > 0 and close > 0 and bb_range > 0:
            bb_pos = (close - bb_l) / bb_range
            if bb_pos < 0.35:
                score += 1.0

        if (plus_di - minus_di) > 10:
            score += 1.0

        score += 1.0
        score += 1.0

        numeric = max(1, min(10, round(score * 10 / 17.5)))

        if numeric >= 8:
            level = "STRONG"
        elif numeric >= 6:
            level = "GOOD"
        elif numeric >= 4:
            level = "MEDIUM"
        else:
            level = "WEAK"

        return numeric, level

    # ============================================================
    # ГЛАВНЫЙ МЕТОД (LIVE)
    # ============================================================
    def check_symbol(self, symbol, free_balance):
        try:
            df = self._fetch(symbol, self.tf, 250)
        except Exception as e:
            self._log(f"⚠ TrendRider fetch {symbol}: {str(e)[:60]}", "#ff9800")
            return None

        if len(df) < 210:
            return None

        try:
            m = self._compute_indicators(df)
        except Exception as e:
            self._log(f"⚠ TrendRider ind {symbol}: {str(e)[:60]}", "#ff9800")
            return None

        ctx = self._mtf_context(symbol)
        btc_rsi, btc_bull = self._btc_sentiment()

        sigs = self._signals(m, ctx, btc_rsi, btc_bull)
        if not sigs:
            return None

        numeric, level = self._confidence(m, ctx, btc_rsi)

        adx = m['adx']
        close = m['close']
        ema200 = m['ema200']
        is_bull = m['is_bull']
        if adx < 20:
            regime = "RANGING"
            min_conf = self.min_conf
        elif is_bull and close > ema200:
            regime = "BULL"
            min_conf = self.min_conf
        else:
            regime = "BEAR"
            min_conf = self.min_conf_bear

        if numeric < min_conf:
            self._log(
                f"   TrendRider {symbol}: conf {numeric}/10 < {min_conf} "
                f"({regime}) — skip [{','.join(sigs)}]",
                "#888"
            )
            return None

        atr_pct = (m['atr'] / m['close']) * 100 if m['close'] else 0.0

        return Signal(
            direction='LONG',
            confidence=numeric / 10.0,
            stop_pct=None,
            take_pct=None,
            leverage=None,
            size_usd=None,
            reason=f"TR[{','.join(sigs)}] {level} {numeric}/10",
            meta={
                'signal_type': 'TrendRider',
                'signal_name': ','.join(sigs),
                'atr_pct': atr_pct,
                'price': m['close'],
                'confidence_score': numeric,
                'confidence_level': level,
                'regime': regime,
                'level_price': 0,
                'touches': 0,
                'trend': 'UP' if is_bull else 'DOWN',
                'distance_to_level_pct': 0,
            },
        )

    # ============================================================
    # BACKTEST-РЕЖИМ
    # ============================================================
    def evaluate_at(self, df_1h, idx):
        """
        Оценивает сигнал TrendRider на свече idx.
        Работает БЕЗ сети — использует только df_1h.

        Упрощения (в бэктесте):
          - BTC-сентимент: нейтральный (rsi=50, is_bull=1)
          - 4h/1d контекст: пустой (ema200_1d=0)
        """
        if idx < 210 or idx >= len(df_1h):
            return None

        df = df_1h.iloc[:idx + 1].copy()
        if len(df) < 210:
            return None

        try:
            m = self._compute_indicators(df)
        except Exception:
            return None

        ctx = {'is_bull_4h': 0, 'rsi_4h': 50.0, 'adx_4h': 0.0, 'ema200_1d': 0.0}
        btc_rsi, btc_bull = 50.0, 1

        sigs = self._signals(m, ctx, btc_rsi, btc_bull)
        if not sigs:
            return None

        numeric, level = self._confidence(m, ctx, btc_rsi)

        adx = m['adx']
        close = m['close']
        ema200 = m['ema200']
        is_bull = m['is_bull']
        if adx < 20:
            regime = "RANGING"
            min_conf = self.min_conf
        elif is_bull and close > ema200:
            regime = "BULL"
            min_conf = self.min_conf
        else:
            regime = "BEAR"
            min_conf = self.min_conf_bear

        if numeric < min_conf:
            return None

        atr_pct = (m['atr'] / m['close']) * 100 if m['close'] else 0.0

        return Signal(
            direction='LONG',
            confidence=numeric / 10.0,
            stop_pct=None,
            take_pct=None,
            leverage=None,
            size_usd=None,
            reason=f"TR[{','.join(sigs)}] {level} {numeric}/10",
            meta={
                'signal_type': 'TrendRider',
                'signal_name': ','.join(sigs),
                'atr_pct': atr_pct,
                'price': m['close'],
                'confidence_score': numeric,
                'confidence_level': level,
                'regime': regime,
                'level_price': 0,
                'touches': 0,
                'trend': 'UP' if is_bull else 'DOWN',
                'distance_to_level_pct': 0,
            },
        )

    @classmethod
    def params_schema(cls):
        return [
            ("TREND_EMA_FAST",         "EMA fast",              "int",   9,    5,   30,  1),
            ("TREND_EMA_SLOW",         "EMA slow",              "int",   16,   10,  50,  1),
            ("TREND_RSI_PERIOD",       "RSI period",            "int",   14,   7,   21,  1),
            ("TREND_RSI_PULLBACK_LOW", "RSI pullback low",      "int",   40,   20,  50,  1),
            ("TREND_RSI_PULLBACK_HIGH","RSI pullback high",     "int",   58,   50,  80,  1),
            ("TREND_RSI_BOUNCE",       "RSI bounce",            "int",   30,   20,  40,  1),
            ("TREND_ADX_THRESHOLD",    "ADX threshold",         "int",   25,   10,  50,  1),
            ("TREND_VOLUME_FACTOR",    "Volume factor",         "float", 1.3,  0.5, 3.0, 0.1),
            ("TREND_MIN_CONF",         "Min confidence (bull)", "int",   5,    1,   10,  1),
            ("TREND_MIN_CONF_BEAR",    "Min confidence (bear)", "int",   6,    1,   10,  1),
        ]