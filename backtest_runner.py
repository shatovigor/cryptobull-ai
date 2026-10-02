"""
Бэктест на основе ТЕКУЩИХ настроек из config.py.
Поддерживает override_config и адаптивный стоп по ATR.

ВАЖНО: корректный расчёт без look-ahead bias:
  - Уровни/тренд/ATR строятся ТОЛЬКО по свечам до точки входа.
  - Вход по open следующей свечи (как market-ордер в реальности).
  - P&L итоговый считается от депозита, а не суммой процентов.
  - Издержки: taker fee + реалистичный slippage + funding.
"""
import ccxt
import pandas as pd
import numpy as np

import config


# ============================================================
# ВСПОМОГАТЕЛЬНОЕ: расчёт уровней по подокну
# ============================================================
def _build_levels_from_window(df_window, cluster_pct, min_touches):
    """
    Строит уровни по фрейму df_window (только прошлое!).
    Возвращает список уровней [{price, touches, last_ts}, ...].
    """
    if df_window is None or len(df_window) < 5:
        return []

    points = []
    for i in range(len(df_window)):
        points.append({'price': df_window['high'].iloc[i],
                       'ts': df_window['ts'].iloc[i]})
        points.append({'price': df_window['low'].iloc[i],
                       'ts': df_window['ts'].iloc[i]})

    if not points:
        return []

    points.sort(key=lambda x: x['price'])

    clusters = []
    cur = [points[0]]
    for p in points[1:]:
        if cur[-1]['price'] == 0:
            cur.append(p)
            continue
        diff_pct = abs(p['price'] - cur[-1]['price']) / cur[-1]['price'] * 100
        if diff_pct < cluster_pct:
            cur.append(p)
        else:
            clusters.append(cur)
            cur = [p]
    clusters.append(cur)

    levels = []
    for c in clusters:
        if len(c) < min_touches:
            continue
        levels.append({
            'price': np.mean([p['price'] for p in c]),
            'touches': len(c),
            'last_ts': max(p['ts'] for p in c),
        })
    return levels


def _calc_atr_pct_from_window(df_window, lookback=20):
    """ATR% по последним N свечам окна."""
    if df_window is None or len(df_window) < 5:
        return None
    tail = df_window.tail(lookback)
    if len(tail) == 0:
        return None
    return ((tail['high'] - tail['low']) / tail['close'] * 100).mean()


def _calc_trend_from_window(df_window, ma_period=20):
    """Тренд по последним ma_period свечам окна."""
    if df_window is None or len(df_window) < ma_period + 1:
        return 'NEUTRAL'
    close = df_window['close']
    ma = close.rolling(ma_period).mean().iloc[-1]
    if pd.isna(ma):
        return 'NEUTRAL'
    return 'UP' if close.iloc[-1] > ma else 'DOWN'


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================
def run_backtest(symbols=None, backtest_days=10,
                 progress_callback=None,
                 cancel_check=None,
                 status_callback=None,
                 override_config=None):
    if symbols is None:
        symbols = list(config.AUTO_SYMBOLS)

    cfg = {}
    keys = [
        'MIN_TOUCHES', 'CLUSTER_PCT', 'NEAR_LEVEL_PCT', 'USE_TREND_FILTER',
        'USE_MULTI_TIMEFRAME', 'USE_TRAILING_STOP', 'USE_ADAPTIVE_SIZE',
        'USE_PYRAMIDING', 'USE_HEDGING',
        'MAX_AUTO_LEVERAGE', 'STOP_PCT_CALM', 'TAKE_PCT_CALM',
        'COOLDOWN_MINUTES', 'USE_TREND_FILTER',
        'TRAILING_START_PCT', 'TRAILING_STEP_PCT',
        'ADAPTIVE_ATR_LOW', 'ADAPTIVE_ATR_HIGH',
        'ADAPTIVE_SIZE_MIN_PCT', 'ADAPTIVE_SIZE_MAX_PCT',
        'PYRAMID_START_PCT', 'PYRAMID_MAX_ADD',
        'HEDGE_TRIGGER_PCT', 'HEDGE_SIZE_RATIO',
        'MTF_WEIGHT_DAILY', 'MTF_WEIGHT_4H', 'MTF_WEIGHT_15M',
        'USE_ADAPTIVE_STOP', 'ADAPTIVE_STOP_ATR_MULT', 'ADAPTIVE_TAKE_ATR_MULT',
        'ADAPTIVE_STOP_MIN_PCT', 'ADAPTIVE_STOP_MAX_PCT',
        'ADAPTIVE_TAKE_MIN_PCT', 'ADAPTIVE_TAKE_MAX_PCT',
    ]
    for key in keys:
        cfg[key] = getattr(config, key, None)
    if override_config:
        cfg.update(override_config)

    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    })

    # ==== ПАРАМЕТРЫ ====
    LOOKBACK_DAYS = config.LOOKBACK_DAYS
    MAX_LEVEL_AGE_DAYS = config.MAX_LEVEL_AGE_DAYS
    CLUSTER_PCT = cfg.get('CLUSTER_PCT', config.CLUSTER_PCT)
    MIN_TOUCHES = cfg.get('MIN_TOUCHES', config.MIN_TOUCHES)
    NEAR_LEVEL_PCT = config.NEAR_LEVEL_PCT
    PINBAR_SHADOW_RATIO = config.PINBAR_SHADOW_RATIO
    MIN_SHADOW_PCT = config.MIN_SHADOW_PCT
    USE_BOUNCE_SIGNAL = config.USE_BOUNCE_SIGNAL
    LOOKBACK_CANDLES = config.LOOKBACK_CANDLES
    COMMISSION_PCT = config.COMMISSION_PCT
    # ==== ФИКС #5: реалистичный slippage ====
    # В реальности market-ордер на волатильном альте даёт 0.05-0.15%
    SLIPPAGE_PCT = max(getattr(config, 'SLIPPAGE_PCT', 0.02), 0.1)
    FUNDING_PCT_PER_8H = 0.01

    STOP_PCT_CALM = cfg.get('STOP_PCT_CALM') or 2.5
    TAKE_PCT_CALM = cfg.get('TAKE_PCT_CALM') or 5.0
    COOLDOWN_MINUTES = cfg.get('COOLDOWN_MINUTES') or 120
    USE_TREND_FILTER = cfg.get('USE_TREND_FILTER')
    if USE_TREND_FILTER is None:
        USE_TREND_FILTER = True

    MAX_LEVERAGE = cfg.get('MAX_AUTO_LEVERAGE') or 1.0
    USE_AUTO_LEVERAGE = True

    USE_TRAILING = cfg.get('USE_TRAILING_STOP') or False
    TRAIL_START_PCT = cfg.get('TRAILING_START_PCT') or 4.0
    TRAIL_STEP_PCT = cfg.get('TRAILING_STEP_PCT') or 1.0

    USE_MTF = cfg.get('USE_MULTI_TIMEFRAME') or False
    MTF_W_1D = cfg.get('MTF_WEIGHT_DAILY', 0.4)
    MTF_W_4H = cfg.get('MTF_WEIGHT_4H', 0.3)
    MTF_W_15M = cfg.get('MTF_WEIGHT_15M', 0.3)

    USE_ADAPTIVE = cfg.get('USE_ADAPTIVE_SIZE') or False
    ADAPTIVE_ATR_LOW = cfg.get('ADAPTIVE_ATR_LOW') or 5.0
    ADAPTIVE_ATR_HIGH = cfg.get('ADAPTIVE_ATR_HIGH') or 12.0
    ADAPTIVE_SIZE_MIN_PCT = cfg.get('ADAPTIVE_SIZE_MIN_PCT') or 3.0
    ADAPTIVE_SIZE_MAX_PCT = cfg.get('ADAPTIVE_SIZE_MAX_PCT') or 8.0

    USE_ADAPTIVE_STOP = cfg.get('USE_ADAPTIVE_STOP') or False
    ADAPTIVE_STOP_ATR_MULT = cfg.get('ADAPTIVE_STOP_ATR_MULT') or 0.6
    ADAPTIVE_TAKE_ATR_MULT = cfg.get('ADAPTIVE_TAKE_ATR_MULT') or 1.2
    ADAPTIVE_STOP_MIN_PCT = cfg.get('ADAPTIVE_STOP_MIN_PCT') or 1.5
    ADAPTIVE_STOP_MAX_PCT = cfg.get('ADAPTIVE_STOP_MAX_PCT') or 8.0
    ADAPTIVE_TAKE_MIN_PCT = cfg.get('ADAPTIVE_TAKE_MIN_PCT') or 3.0
    ADAPTIVE_TAKE_MAX_PCT = cfg.get('ADAPTIVE_TAKE_MAX_PCT') or 16.0

    BASE_SIZE_PCT = getattr(config, 'AUTO_POSITION_PCT', 5.0)
    START_BALANCE = 540.0
    # ==== ФИКС: убираем жёсткий кэп, берём из config ====
    AUTO_MIN_SIZE_USD = getattr(config, 'AUTO_MIN_POSITION_USD', 10)
    AUTO_MAX_SIZE_USD = getattr(config, 'AUTO_MAX_POSITION_USD', 10_000_000)

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    # ==== УТИЛИТЫ ====
    def is_bullish_pinbar(c):
        body = abs(c['close'] - c['open'])
        total = c['high'] - c['low']
        if total == 0:
            return False
        lower = min(c['open'], c['close']) - c['low']
        upper = c['high'] - max(c['open'], c['close'])
        bs = max(body, total * 0.05)
        return (lower >= bs * PINBAR_SHADOW_RATIO
                and upper <= bs * 0.5
                and lower / c['close'] * 100 >= MIN_SHADOW_PCT)

    def is_bearish_pinbar(c):
        body = abs(c['close'] - c['open'])
        total = c['high'] - c['low']
        if total == 0:
            return False
        lower = min(c['open'], c['close']) - c['low']
        upper = c['high'] - max(c['open'], c['close'])
        bs = max(body, total * 0.05)
        return (upper >= bs * PINBAR_SHADOW_RATIO
                and lower <= bs * 0.5
                and upper / c['close'] * 100 >= MIN_SHADOW_PCT)

    def price_from_above(df, i, lp):
        start = max(0, i - LOOKBACK_CANDLES)
        for j in range(start, i):
            if df['close'].iloc[j] > lp * 1.002:
                return True
        return False

    def price_from_below(df, i, lp):
        start = max(0, i - LOOKBACK_CANDLES)
        for j in range(start, i):
            if df['close'].iloc[j] < lp * 0.998:
                return True
        return False

    def is_bounce_long(df, i, lp):
        c = df.iloc[i]
        return (c['low'] <= lp * 1.001 and c['close'] > lp
                and c['close'] > c['open']
                and price_from_above(df, i, lp))

    def is_bounce_short(df, i, lp):
        c = df.iloc[i]
        return (c['high'] >= lp * 0.999 and c['close'] < lp
                and c['close'] < c['open']
                and price_from_below(df, i, lp))

    def check_mtf(symbol, entry_ts, side):
        """MTF-фильтр. Тянем свечи с since=entry_ts-30*4h, без look-ahead."""
        if not USE_MTF:
            return True
        try:
            since_ms = int(
                (pd.Timestamp(entry_ts) - pd.Timedelta(hours=4 * 30)).timestamp() * 1000
            )
            raw = exchange.fetch_ohlcv(symbol, '4h', since=since_ms, limit=100)
            if not raw or len(raw) < 20:
                return True
            df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms')
            mask = df['ts'] <= entry_ts
            if mask.sum() < 20:
                return True
            idx = mask.sum() - 1
            if idx < 10:
                return True
            price = df['close'].iloc[idx]
            sma = df['close'].iloc[max(0, idx - 10):idx].mean()
            trend_4h = 'UP' if price > sma else 'DOWN'
            if side == 'LONG' and trend_4h == 'DOWN':
                return False
            if side == 'SHORT' and trend_4h == 'UP':
                return False
            return True
        except Exception:
            return True

    def calc_position_size(balance, atr_pct):
        """Размер позиции от баланса. Убран жёсткий кэп $500."""
        if USE_ADAPTIVE and atr_pct is not None:
            if atr_pct <= ADAPTIVE_ATR_LOW:
                pct = ADAPTIVE_SIZE_MAX_PCT
            elif atr_pct >= ADAPTIVE_ATR_HIGH:
                pct = ADAPTIVE_SIZE_MIN_PCT
            else:
                ratio = (atr_pct - ADAPTIVE_ATR_LOW) / (ADAPTIVE_ATR_HIGH - ADAPTIVE_ATR_LOW)
                pct = ADAPTIVE_SIZE_MAX_PCT - ratio * (ADAPTIVE_SIZE_MAX_PCT - ADAPTIVE_SIZE_MIN_PCT)
        else:
            pct = BASE_SIZE_PCT
        size = balance * pct / 100
        size = max(AUTO_MIN_SIZE_USD, min(AUTO_MAX_SIZE_USD, size))
        return size, pct

    def calc_leverage_atr(atr_pct, max_lev, use_auto):
        if not use_auto:
            return 1.0
        if atr_pct is None:
            return 1.0
        if atr_pct < 5:
            base = 5.0
        elif atr_pct < 8:
            base = 4.0
        elif atr_pct < 12:
            base = 3.0
        elif atr_pct < 20:
            base = 2.0
        else:
            base = 1.0
        return min(base, max_lev)

    def calc_stop_take(atr_pct):
        if USE_ADAPTIVE_STOP and atr_pct is not None:
            stop_pct = atr_pct * ADAPTIVE_STOP_ATR_MULT
            take_pct = atr_pct * ADAPTIVE_TAKE_ATR_MULT
            stop_pct = max(ADAPTIVE_STOP_MIN_PCT, min(ADAPTIVE_STOP_MAX_PCT, stop_pct))
            take_pct = max(ADAPTIVE_TAKE_MIN_PCT, min(ADAPTIVE_TAKE_MAX_PCT, take_pct))
            return stop_pct, take_pct
        return STOP_PCT_CALM, TAKE_PCT_CALM

    # ============================================================
    # БЭКТЕСТ ОДНОЙ МОНЕТЫ (с инкрементальными уровнями)
    # ============================================================
    def backtest_symbol(symbol):
        # 1) Дневные свечи — для построения уровней «на текущий момент»
        raw_daily = exchange.fetch_ohlcv(symbol, '1d', limit=LOOKBACK_DAYS)
        if not raw_daily or len(raw_daily) < 20:
            return None
        df_daily = pd.DataFrame(
            raw_daily, columns=['ts', 'open', 'high', 'low', 'close', 'volume']
        )
        df_daily['ts'] = pd.to_datetime(df_daily['ts'], unit='ms')

        # 2) 15m свечи для бэктеста
        limit_m15 = backtest_days * 96 + 50
        raw = exchange.fetch_ohlcv(symbol, '15m', limit=limit_m15)
        if not raw or len(raw) < LOOKBACK_CANDLES + 10:
            return None
        df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')

        # Границы по времени
        ts_start = df['ts'].iloc[0]
        ts_end = df['ts'].iloc[-1]
        # Дневные свечи, попавшие в окно
        daily_in_window = df_daily[
            (df_daily['ts'] >= ts_start - pd.Timedelta(days=LOOKBACK_DAYS))
            & (df_daily['ts'] <= ts_end)
        ].reset_index(drop=True)

        # 3) Уровни/тренд/ATR — пересчитываем по подокну на каждой итерации
        # Для скорости: обновляем раз в 4 часа (96 свечей 15m)
        REFRESH_EVERY = 96
        current_levels = []
        current_trend = 'NEUTRAL'
        current_atr = None
        current_stop_pct = STOP_PCT_CALM
        current_take_pct = TAKE_PCT_CALM
        current_leverage = 1.0

        # Строим начальное состояние по свечам до df['ts'][LOOKBACK_CANDLES-1]
        warmup_end_ts = df['ts'].iloc[LOOKBACK_CANDLES - 1]

        def rebuild_state(as_of_ts):
            """Строит уровни/тренд/ATR только по свечам ДО as_of_ts."""
            window = daily_in_window[daily_in_window['ts'] < as_of_ts]
            window = window.tail(LOOKBACK_DAYS)

            lvls = _build_levels_from_window(window, CLUSTER_PCT, MIN_TOUCHES)
            tr = _calc_trend_from_window(window, ma_period=20)
            atr = _calc_atr_pct_from_window(window, lookback=20)

            stop_p, take_p = calc_stop_take(atr)
            lev = calc_leverage_atr(atr, MAX_LEVERAGE, USE_AUTO_LEVERAGE)
            return lvls, tr, atr, stop_p, take_p, lev

        current_levels, current_trend, current_atr, \
            current_stop_pct, current_take_pct, current_leverage = rebuild_state(warmup_end_ts)

        trades = []
        in_pos = False
        pos = None
        last_ts = None
        pending = None
        balance = START_BALANCE

        for i in range(LOOKBACK_CANDLES, len(df) - 1):
            c = df.iloc[i]
            ts = c['ts']

            # Обновляем состояние раз в REFRESH_EVERY свечей
            if i % REFRESH_EVERY == 0:
                current_levels, current_trend, current_atr, \
                    current_stop_pct, current_take_pct, current_leverage = rebuild_state(ts)

            # ==== ВХОД в позицию по open СЛЕДУЮЩЕЙ свечи ====
            if pending and not in_pos:
                nxt = df.iloc[i]
                entry_price = nxt['open']  # ФИКС #4: вход по open, а не по close

                pos = pending
                pos['entry'] = entry_price
                pos['entry_ts'] = nxt['ts']

                if pos['type'] == 'LONG':
                    pos['stop'] = entry_price * (1 - current_stop_pct / 100)
                    pos['take'] = entry_price * (1 + current_take_pct / 100)
                else:
                    pos['stop'] = entry_price * (1 + current_stop_pct / 100)
                    pos['take'] = entry_price * (1 - current_take_pct / 100)

                pos['best_price'] = entry_price
                pos['trail_active'] = False

                size_usd, used_pct = calc_position_size(balance, current_atr)
                pos['size_usd'] = size_usd
                pos['used_pct'] = used_pct
                pos['leverage'] = current_leverage
                pos['stop_pct'] = current_stop_pct
                pos['take_pct'] = current_take_pct
                pos['atr_pct'] = current_atr

                in_pos = True
                last_ts = nxt['ts']
                pending = None

            # ==== ВЕДЕНИЕ позиции ====
            if in_pos:
                nxt = df.iloc[i + 1]
                exit_price = None
                result = None
                exit_reason = None

                # Trailing stop
                if USE_TRAILING:
                    if pos['type'] == 'LONG':
                        if nxt['high'] > pos['best_price']:
                            pos['best_price'] = nxt['high']
                    else:
                        if nxt['low'] < pos['best_price']:
                            pos['best_price'] = nxt['low']

                    if pos['type'] == 'LONG':
                        cur_pnl = (pos['best_price'] - pos['entry']) / pos['entry'] * 100
                    else:
                        cur_pnl = (pos['entry'] - pos['best_price']) / pos['entry'] * 100

                    if cur_pnl >= TRAIL_START_PCT:
                        pos['trail_active'] = True

                    if pos['trail_active']:
                        if pos['type'] == 'LONG':
                            new_stop = pos['best_price'] * (1 - TRAIL_STEP_PCT / 100)
                            if new_stop > pos['stop']:
                                pos['stop'] = new_stop
                        else:
                            new_stop = pos['best_price'] * (1 + TRAIL_STEP_PCT / 100)
                            if new_stop < pos['stop']:
                                pos['stop'] = new_stop

                # Проверка стоп/тейк
                if pos['type'] == 'LONG':
                    if nxt['low'] <= pos['stop']:
                        exit_price = pos['stop']
                        result = 'TAKE' if pos['stop'] > pos['entry'] else 'STOP'
                        if pos['trail_active'] and pos['stop'] > pos['entry']:
                            exit_reason = 'TRAILING'
                        elif pos['stop'] < pos['entry']:
                            exit_reason = 'STOP'
                        else:
                            exit_reason = 'TAKE'
                    elif nxt['high'] >= pos['take']:
                        exit_price = pos['take']
                        result = 'TAKE'
                        exit_reason = 'TAKE'
                else:
                    if nxt['high'] >= pos['stop']:
                        exit_price = pos['stop']
                        result = 'TAKE' if pos['stop'] < pos['entry'] else 'STOP'
                        if pos['trail_active'] and pos['stop'] < pos['entry']:
                            exit_reason = 'TRAILING'
                        elif pos['stop'] > pos['entry']:
                            exit_reason = 'STOP'
                        else:
                            exit_reason = 'TAKE'
                    elif nxt['low'] <= pos['take']:
                        exit_price = pos['take']
                        result = 'TAKE'
                        exit_reason = 'TAKE'

                if exit_price is not None:
                    if pos['type'] == 'LONG':
                        gross_pct = (exit_price - pos['entry']) / pos['entry'] * 100
                    else:
                        gross_pct = (pos['entry'] - exit_price) / pos['entry'] * 100

                    gross_with_lev = gross_pct * pos['leverage']

                    costs_base = 2 * (COMMISSION_PCT + SLIPPAGE_PCT)
                    dur_h = (nxt['ts'] - pos['entry_ts']).total_seconds() / 3600
                    funding_base = (dur_h / 8) * FUNDING_PCT_PER_8H
                    costs_lev = (costs_base + funding_base) * pos['leverage']

                    net_pct = gross_with_lev - costs_lev
                    pnl_usd = pos['size_usd'] * net_pct / 100

                    trades.append({
                        'symbol': symbol,
                        'type': pos['type'],
                        'entry': pos['entry'],
                        'exit': exit_price,
                        'entry_ts': pos['entry_ts'],
                        'exit_ts': nxt['ts'],
                        'duration_h': dur_h,
                        'result': result,
                        'reason': exit_reason,
                        'gross': gross_with_lev,
                        'costs': costs_lev,
                        'pnl': net_pct,
                        'pnl_usd': pnl_usd,
                        'leverage': pos['leverage'],
                        'size_usd': pos['size_usd'],
                        'stop_pct': pos['stop_pct'],
                        'take_pct': pos['take_pct'],
                        'atr_pct': pos['atr_pct'],
                    })

                    balance += pnl_usd
                    in_pos = False
                continue

            # Cooldown
            if last_ts is not None:
                dt_min = (ts - last_ts).total_seconds() / 60
                if dt_min < COOLDOWN_MINUTES:
                    continue

            # ==== ПОИСК СИГНАЛА (по уровням «на текущий момент») ====
            if not current_levels:
                continue

            price = c['close']
            near = []
            for l in current_levels:
                if l['price'] == 0:
                    continue
                dist_pct = abs(l['price'] - price) / price * 100
                if dist_pct > NEAR_LEVEL_PCT:
                    continue
                age_days = (ts - l['last_ts']).days
                if age_days > MAX_LEVEL_AGE_DAYS:
                    continue
                near.append(l)

            if not near:
                continue

            nearest = min(near, key=lambda x: abs(x['price'] - price))
            is_support = nearest['price'] < price
            signal = None
            side = None

            if is_support:
                if is_bullish_pinbar(c):
                    signal = 'PINBAR'
                    side = 'LONG'
                elif USE_BOUNCE_SIGNAL and is_bounce_long(df, i, nearest['price']):
                    signal = 'BOUNCE'
                    side = 'LONG'
                if signal and USE_TREND_FILTER and current_trend != 'UP':
                    continue
            else:
                if is_bearish_pinbar(c):
                    signal = 'PINBAR'
                    side = 'SHORT'
                elif USE_BOUNCE_SIGNAL and is_bounce_short(df, i, nearest['price']):
                    signal = 'BOUNCE'
                    side = 'SHORT'
                if signal and USE_TREND_FILTER and current_trend != 'DOWN':
                    continue

            if signal:
                # A/B: отключение PINBAR или BOUNCE через override
                if cfg.get('PINBAR_DISABLED', False) and signal == 'PINBAR':
                    continue
                if cfg.get('BOUNCE_DISABLED', False) and signal == 'BOUNCE':
                    continue

                if USE_MTF:
                    if not check_mtf(symbol, ts, side):
                        continue
                pending = {'type': side}

        return trades

    # ============================================================
    # МЕТРИКИ
    # ============================================================
    def metrics(trades):
        if not trades:
            return None
        total = len(trades)
        wins = sum(1 for t in trades if t['result'] == 'TAKE')
        pnl_usd_total = sum(t['pnl_usd'] for t in trades)
        gross_usd = sum(t['gross'] * t['size_usd'] / 100 for t in trades)

        # ==== ФИКС #10: P&L от депозита, а не сумма процентов ====
        # Общий P&L % от стартового депозита
        pnl_pct_from_deposit = pnl_usd_total / START_BALANCE * 100

        # Средний P&L по сделке (для информации)
        pnl_pct_avg = sum(t['pnl'] for t in trades) / total

        profit_usd = sum(t['pnl_usd'] for t in trades if t['pnl_usd'] > 0)
        loss_usd = abs(sum(t['pnl_usd'] for t in trades if t['pnl_usd'] < 0))
        pf = profit_usd / loss_usd if loss_usd > 0 else 99.99

        # Drawdown по equity (в USD)
        eq_usd = [0.0]
        for t in trades:
            eq_usd.append(eq_usd[-1] + t['pnl_usd'])
        peak = eq_usd[0]
        dd_usd = 0.0
        for e in eq_usd:
            if e > peak:
                peak = e
            dd_usd = max(dd_usd, peak - e)

        # DD в % от стартового депозита
        dd_pct = dd_usd / START_BALANCE * 100 if START_BALANCE > 0 else 0

        avg_lev = sum(t.get('leverage', 1.0) for t in trades) / total
        avg_dur = sum(t.get('duration_h', 0) for t in trades) / total

        return {
            'total': total,
            'wins': wins,
            'winrate': wins / total * 100,
            'pnl': pnl_pct_from_deposit,       # ← % от депозита
            'pnl_avg_pct': pnl_pct_avg,         # ← средний % по сделке
            'gross': pnl_pct_from_deposit + sum(t['costs'] for t in trades) / total,
            'costs': sum(t['costs'] * t['size_usd'] / 100 for t in trades) / START_BALANCE * 100,
            'pf': pf,
            'dd': dd_pct,
            'dd_usd': dd_usd,
            'avg': pnl_pct_from_deposit / total if total else 0,
            'pnl_usd': pnl_usd_total,
            'avg_leverage': avg_lev,
            'avg_duration_h': avg_dur,
            'start_balance': START_BALANCE,
            'end_balance': START_BALANCE + pnl_usd_total,
        }

    # ============================================================
    # ПРОГОН ПО ВСЕМ МОНЕТАМ
    # ============================================================
    results = []
    all_trades = []
    positive = 0
    negative = 0

    total_syms = len(symbols)
    for idx, sym in enumerate(symbols):
        if cancel_check and cancel_check():
            log("⏹ Отменено пользователем")
            break

        log(f"[{idx + 1}/{total_syms}] Проверка {sym}...")
        if status_callback:
            try:
                status_callback({'current': idx + 1, 'total': total_syms, 'symbol': sym})
            except Exception:
                pass

        try:
            trades = backtest_symbol(sym)
            if not trades:
                results.append({'symbol': sym, 'total': 0})
                continue

            all_trades.extend(trades)
            m = metrics(trades)
            m['symbol'] = sym
            results.append(m)

            if m['pnl_usd'] > 0:
                positive += 1
            else:
                negative += 1
        except Exception as e:
            log(f"Ошибка {sym}: {str(e)[:80]}")
            results.append({'symbol': sym, 'error': str(e)[:80]})

    summary = None
    if all_trades:
        summary = metrics(all_trades)
        summary['positive'] = positive
        summary['negative'] = negative
        summary['period_days'] = backtest_days
        summary['symbols_count'] = len(symbols)
        summary['max_leverage'] = MAX_LEVERAGE
        summary['slippage_used'] = SLIPPAGE_PCT
        summary['commission_used'] = COMMISSION_PCT

    return {
        'results': results,
        'summary': summary,
        'trades_list': all_trades,
        'period_days': backtest_days,
        'symbols_count': len(symbols),
    }