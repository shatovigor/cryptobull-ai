"""
Адаптивная ML-стратегия.

Портирована из FX-проекта (adaptive_learning_bot.py).
Принципы:
  - Онлайн-обучение: SGDClassifier дообучается каждые N сделок
  - Признаки: RSI, MACD, ATR, SMA-ratios, returns (30–40 штук)
  - Гибрид: не используется (нет fixed-модели под крипту) — только adaptive
  - Размер: Kelly + ограничение по макс. % от баланса
  - Стоп/тейк: ATR × множитель, но с ограничением min/max

При первом запуске модель не обучена → стратегия возвращает None,
пока не наберётся AML_UPDATE_INTERVAL сделок (или пока не загрузится
сохранённая модель из AML_MODEL_DIR).
"""
import os
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler

from .base import StrategyBase, Signal
import config


class AdaptiveMLStrategy(StrategyBase):
    name = "adaptive_ml"
    display_name = "🧠 Адаптивная ML"

    # ============================================================
    # INIT
    # ============================================================
    def __init__(self, trader, log_fn):
        super().__init__(trader, log_fn)

        self.model_dir = Path(getattr(config, 'AML_MODEL_DIR', 'storage/models/adaptive'))
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.online_model = SGDClassifier(
            loss='log_loss',
            penalty='l2',
            alpha=0.0001,
            learning_rate='adaptive',
            eta0=0.01,
            max_iter=1000,
            random_state=42,
            warm_start=True,
        )
        self.scaler = StandardScaler()
        self.trained = False

        # Буфер (features, label) для partial_fit
        self.buffer = []

        # Сколько сделок до обновления модели
        self.update_interval = getattr(config, 'AML_UPDATE_INTERVAL', 50)

        # Пороги
        self.conf_threshold = getattr(config, 'AML_CONF_THRESHOLD', 0.65)
        self.min_move_pct = getattr(config, 'AML_MIN_MOVE_PCT', 0.35)

        # Kelly / размер
        self.kelly_fraction = getattr(config, 'AML_KELLY_FRACTION', 0.25)
        self.max_size_pct = getattr(config, 'AML_MAX_SIZE_PCT', 0.15)

        # Плечо
        self.max_leverage = getattr(config, 'AML_MAX_LEVERAGE', 3.0)

        # Стоп/тейк
        self.stop_atr_mult = getattr(config, 'AML_STOP_ATR_MULT', 2.0)
        self.take_atr_mult = getattr(config, 'AML_TAKE_ATR_MULT', 4.0)

        # Кэш фичей для последнего вызова (нужен AutoTrader для сохранения)
        self._last_features = None

        # Имя файла модели (по всем символам — одна модель)
        self._model_file = self.model_dir / 'aml_model.pkl'
        self._load()

        if self.trained:
            self._log(f"🧠 AML: модель загружена (обучена)", "#7C4DFF")
        else:
            self._log(f"🧠 AML: модель ещё не обучена — ждём {self.update_interval} сделок", "#888")

    # ============================================================
    # ПРИЗНАКИ
    # ============================================================
    def _fetch_candles(self, symbol, timeframe, limit):
        raw = self.trader.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df

    def _features(self, df: pd.DataFrame) -> pd.DataFrame:
        f = pd.DataFrame(index=df.index)
        c = df['close']

        # Returns
        for p in [1, 3, 5, 10, 20]:
            f[f'ret_{p}'] = c.pct_change(p)

        # SMA ratios
        for p in [5, 10, 20, 50]:
            sma = c.rolling(p).mean()
            f[f'sma_{p}_ratio'] = c / sma - 1

        # RSI
        delta = c.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = -delta.where(delta < 0, 0).rolling(14).mean()
        f['rsi_14'] = 100 - 100 / (1 + gain / loss)

        # MACD
        ema12 = c.ewm(span=12).mean()
        ema26 = c.ewm(span=26).mean()
        f['macd'] = ema12 - ema26
        f['macd_sig'] = f['macd'].ewm(span=9).mean()

        # ATR%
        hl = df['high'] - df['low']
        hc = (df['high'] - c.shift()).abs()
        lc = (df['low'] - c.shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        f['atr_14'] = tr.rolling(14).mean() / c

        # Volatility
        f['vol_20'] = c.pct_change().rolling(20).std()

        # Volume
        if 'volume' in df.columns:
            v = df['volume']
            f['vol_ratio'] = v / v.rolling(20).mean()

        return f.ffill().bfill()

    # ============================================================
    # ПРЕДСКАЗАНИЕ
    # ============================================================
    def _predict(self, feat_row: np.ndarray):
        """Вернуть вероятность класса 1 (up) или None."""
        if not self.trained:
            return None
        try:
            x = self.scaler.transform(feat_row.reshape(1, -1))
            return float(self.online_model.predict_proba(x)[0][1])
        except Exception as e:
            self._log(f"⚠ AML predict: {str(e)[:60]}", "#ff9800")
            return None

    # ============================================================
    # KELLY
    # ============================================================
    def _kelly(self, p: float, rr: float) -> float:
        if rr <= 0:
            return 0.0
        f = (p * (rr + 1) - 1) / rr
        f *= self.kelly_fraction
        return float(np.clip(f, 0.0, self.max_size_pct))

    # ============================================================
    # ГЛАВНЫЙ МЕТОД
    # ============================================================
    def check_symbol(self, symbol, free_balance):
        # Если модель не обучена — сигналов нет
        if not self.trained:
            return None

        try:
            df = self._fetch_candles(symbol, config.TIMEFRAME_M15, 200)
        except Exception as e:
            self._log(f"⚠ AML fetch {symbol}: {str(e)[:60]}", "#ff9800")
            return None

        if len(df) < 60:
            return None

        feat_df = self._features(df)
        last_row = feat_df.iloc[-1].values
        self._last_features = last_row.tolist()

        prob_up = self._predict(last_row)
        if prob_up is None:
            return None

        # Определяем направление по порогу
        if prob_up >= self.conf_threshold:
            direction = "LONG"
            confidence = prob_up
        elif prob_up <= 1 - self.conf_threshold:
            direction = "SHORT"
            confidence = 1 - prob_up
        else:
            return None

        # ATR
        atr_pct = float(feat_df['atr_14'].iloc[-1]) * 100
        if atr_pct <= 0:
            return None

        stop_pct = max(1.5, min(8.0, atr_pct * self.stop_atr_mult))
        take_pct = max(3.0, min(16.0, atr_pct * self.take_atr_mult))

        # Kelly: rr = take/stop
        rr = take_pct / stop_pct if stop_pct > 0 else 0
        size_pct = self._kelly(confidence, rr)
        size_usd = free_balance * size_pct
        size_usd = max(getattr(config, 'AUTO_MIN_POSITION_USD', 10), size_usd)

        price = float(df['close'].iloc[-1])

        return Signal(
            direction=direction,
            confidence=confidence,
            stop_pct=stop_pct,
            take_pct=take_pct,
            leverage=self.max_leverage,
            size_usd=size_usd,
            reason=f"AML p={confidence:.2f}",
            meta={
                'signal_type': 'AML',
                'atr_pct': atr_pct,
                'price': price,
                'features': self._last_features,   # для онлайн-обучения
                'kelly_pct': size_pct,
            },
        )

    # ============================================================
    # ОНЛАЙН-ОБУЧЕНИЕ
    # ============================================================
    def on_trade_closed(self, trade: dict) -> None:
        """Вызывается AutoTrader'ом после закрытия сделки."""
        try:
            feat = trade.get('features')
            if feat is None:
                return

            pnl_pct = trade.get('pnl_pct', 0)
            label = 1 if pnl_pct > 0 else 0

            self.buffer.append((feat, label))
            self._log(
                f"🧠 AML: буфер {len(self.buffer)}/{self.update_interval} "
                f"(label={label}, pnl={pnl_pct:+.2f}%)",
                "#7C4DFF"
            )

            if len(self.buffer) >= self.update_interval:
                self._partial_fit()
        except Exception as e:
            self._log(f"⚠ AML on_trade_closed: {str(e)[:80]}", "#ff9800")

    def _partial_fit(self):
        try:
            X = np.array([x for x, _ in self.buffer])
            y = np.array([y for _, y in self.buffer])

            if X.ndim != 2 or X.shape[0] < 2:
                self._log("🧠 AML: мало данных для обучения", "#ff9800")
                self.buffer = []
                return

            # Защита от классов-одиночек
            if len(set(y)) < 2:
                self._log(f"🧠 AML: все метки = {y[0]}, пропуск обучения", "#ff9800")
                self.buffer = []
                return

            if not self.trained:
                X = self.scaler.fit_transform(X)
            else:
                X = self.scaler.transform(X)

            self.online_model.partial_fit(X, y, classes=[0, 1])
            self.trained = True
            self.buffer = []
            self._save()

            self._log(f"🧠 AML: модель обновлена на {len(y)} сэмплах", "#4caf50")
        except Exception as e:
            self._log(f"❌ AML _partial_fit: {str(e)[:80]}", "#f44336")
            self.buffer = []

    # ============================================================
    # СОХРАНЕНИЕ / ЗАГРУЗКА
    # ============================================================
    def _save(self):
        try:
            with open(self._model_file, 'wb') as f:
                pickle.dump({
                    'model': self.online_model,
                    'scaler': self.scaler,
                    'trained': self.trained,
                }, f)
        except Exception as e:
            self._log(f"⚠ AML save: {str(e)[:60]}", "#ff9800")

    def _load(self):
        if not self._model_file.exists():
            return
        try:
            with open(self._model_file, 'rb') as f:
                data = pickle.load(f)
            self.online_model = data.get('model', self.online_model)
            self.scaler = data.get('scaler', self.scaler)
            self.trained = bool(data.get('trained', False))
        except Exception as e:
            self._log(f"⚠ AML load: {str(e)[:60]}", "#ff9800")

    # ============================================================
    # SCHEMA для GUI
    # ============================================================
    @classmethod
    def params_schema(cls):
        return [
            ("AML_UPDATE_INTERVAL", "Сделок до обновления модели", "int",   50,   5,    500, 1),
            ("AML_CONF_THRESHOLD",  "Порог уверенности",           "float", 0.65, 0.5,  0.95, 0.01),
            ("AML_MIN_MOVE_PCT",    "Мин. движение (%)",           "float", 0.35, 0.05, 5.0,  0.05),
            ("AML_KELLY_FRACTION",  "Доля Kelly",                  "float", 0.25, 0.05, 1.0,  0.05),
            ("AML_MAX_LEVERAGE",    "Макс. плечо",                 "float", 3.0,  1.0,  20.0, 0.5),
            ("AML_MAX_SIZE_PCT",    "Макс. размер (% баланса)",    "float", 0.15, 0.01, 1.0,  0.01),
            ("AML_STOP_ATR_MULT",   "Стоп × ATR",                  "float", 2.0,  0.5,  5.0,  0.1),
            ("AML_TAKE_ATR_MULT",   "Тейк × ATR",                  "float", 4.0,  0.5,  10.0, 0.1),
        ]