"""
Бэктест на основе ТЕКУЩИХ настроек из config.py.
Поддерживает override_config, стратегии и адаптивный стоп по ATR.
"""
import ccxt
import pandas as pd
import numpy as np

import config


def _build_levels_from_window(df_window, cluster_pct, min_touches):
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
    if df_window is None or len(df_window) < 5:
        return None
    tail = df_window.tail(lookback)
    if len(tail) == 0:
        return None
    return ((tail['high'] - tail['low']) / tail['close'] * 100).mean()


def _calc_trend_from_window(df_window, ma_period=20):
    if df_window is None or len(df_window) < ma_period + 1:
        return 'NEUTRAL'
    close = df_window['close']
    ma = close.rolling(ma_period).mean().iloc[-1]
    if pd.isna(ma):
        return 'NEUTRAL'
    return 'UP' if close.iloc[-1] > ma else 'DOWN'


def run_backtest(symbols=None, backtest_days=10,
                 progress_callback=None,
                 cancel_check=None,
                 status_callback=None,
                 override_config=None,
                 strategy_name=None):
    if symbols is None:
        symbols = list(config.AUTO_SYMBOLS)

    if strategy_name is None:
        strategy_name = getattr(config, 'ACTIVE_STRATEGY', 'classic_levels')

    cfg = {}
    keys = [
        'MIN_TOUCHES', 'CLUSTER_PCT', 'NEAR_LEVEL_PCT', 'USE_TREND_FILTER',
        'USE_MULTI_TIMEFRAME', 'USE_TRAILING_STOP', 'USE_ADAPTIVE_SIZE',
        'USE_PYRAMIDING', 'USE_HEDGING',
        'MAX_AUTO_LEVERAGE', 'STOP_PCT_CALM', 'TAKE_PCT_CALM',
        'COOLDOWN_MINUTES',
        'TRAILING_START_PCT', 'TRAILING_STEP_PCT',
        'ADAPTIVE_ATR_LOW', 'ADAPTIVE_ATR_HIGH',
        'ADAPTIVE_SIZE_MIN_PCT', 'ADAPTIVE_SIZE_MAX_PCT',
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

    LOOKBACK_DAYS = config.LOOKBACK_DAYS
    MAX_LEVEL_AGE_DAYS = config.MAX_LEVEL_AGE_DAYS
    CLUSTER_PCT = cfg.get('CLUSTER_PCT', config.CLUSTER_PCT)
    MIN_TOUCHES = cfg.get('MIN_TOUCHES', config.MIN_TOUCHES)
    NEAR_LEVEL_PCT = config.NEAR_LEVEL_PCT
    LOOKBACK_CANDLES = config.LOOKBACK_CANDLES
    COMMISSION_PCT = config.COMMISSION_PCT
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

    # ==== TRAILING ====
    USE_TRAILING = bool(cfg.get('USE_TRAILING_STOP'))
    TRAIL_START_PCT = cfg.get('TRAILING_START_PCT') or 4.0
    TRAIL_STEP_PCT = cfg.get('TRAILING_STEP_PCT') or 1.0

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
    AUTO_MIN_SIZE_USD = getattr(config, 'AUTO_MIN_POSITION_USD', 10)
    AUTO_MAX_SIZE_USD = getattr(config, 'AUTO_MAX_POSITION_USD', 10_000_000)

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    log(f"🎯 Стратегия: {strategy_name}, Trailing={USE_TRAILING}")

    def calc_position_size(balance, atr_pct):
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

    def backtest_symbol(symbol):
        raw_daily = exchange.fetch_ohlcv(symbol, '1d', limit=LOOKBACK_DAYS)
        if not raw_daily or len(raw_daily) < 20:
            return None
        df_daily = pd.DataFrame(
            raw_daily, columns=['ts', 'open', 'high', 'low', 'close', 'volume']
        )
        df_daily['ts'] = pd.to_datetime(df_daily['ts'], unit='ms')

        if strategy_name == 'trendrider':
            tf = '1h'
            limit_m = backtest_days * 24 + 300
            warmup_len = 220
        else:
            tf = '15m'
            limit_m = backtest_days * 96 + 300
            warmup_len = max(LOOKBACK_CANDLES, 30)

        raw = exchange.fetch_ohlcv(symbol, tf, limit=limit_m)
        if not raw or len(raw) < warmup_len + 10:
            return None
        df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')

        ts_start = df['ts'].iloc[0]
        ts_end = df['ts'].iloc[-1]

        daily_in_window = df_daily[
            (df_daily['ts'] >= ts_start - pd.Timedelta(days=LOOKBACK_DAYS))
            & (df_daily['ts'] <= ts_end)
        ].reset_index(drop=True)

        from strategies.registry import get_strategy
        try:
            strat = get_strategy(strategy_name, None, lambda *a, **kw: None)
        except Exception:
            return None

        REFRESH_EVERY = 96 if strategy_name != 'trendrider' else 24

        current_levels = []
        current_trend = 'NEUTRAL'
        current_atr = None
        current_stop_pct = STOP_PCT_CALM
        current_take_pct = TAKE_PCT_CALM
        current_leverage = 1.0

        def rebuild_state(as_of_ts):
            window = daily_in_window[daily_in_window['ts'] < as_of_ts]
            window = window.tail(LOOKBACK_DAYS)
            lvls = _build_levels_from_window(window, CLUSTER_PCT, MIN_TOUCHES)
            tr = _calc_trend_from_window(window, ma_period=20)
            atr = _calc_atr_pct_from_window(window, lookback=20)
            stop_p, take_p = calc_stop_take(atr)
            lev = calc_leverage_atr(atr, MAX_LEVERAGE, USE_AUTO_LEVERAGE)
            return lvls, tr, atr, stop_p, take_p, lev

        warmup_end_ts = df['ts'].iloc[warmup_len - 1]
        current_levels, current_trend, current_atr, \
            current_stop_pct, current_take_pct, current_leverage = rebuild_state(warmup_end_ts)

        trades = []
        in_pos = False
        pos = None
        last_ts = None
        pending = None
        balance = START_BALANCE

        for i in range(warmup_len, len(df) - 1):
            c = df.iloc[i]
            ts = c['ts']

            if (i - warmup_len) % REFRESH_EVERY == 0:
                current_levels, current_trend, current_atr, \
                    current_stop_pct, current_take_pct, current_leverage = rebuild_state(ts)

            if pending and not in_pos:
                nxt = df.iloc[i]
                entry_price = nxt['open']
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

            if in_pos:
                nxt = df.iloc[i + 1]
                exit_price = None
                result = None
                exit_reason = None

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
                        'signal_type': pos.get('signal_type', '?'),
                    })

                    balance += pnl_usd
                    in_pos = False
                continue

            if last_ts is not None:
                dt_min = (ts - last_ts).total_seconds() / 60
                if dt_min < COOLDOWN_MINUTES:
                    continue

            signal = None
            try:
                if strategy_name == 'classic_levels':
                    signal = strat.evaluate_at(
                        df, i, current_levels, current_trend, current_atr
                    )
                elif strategy_name == 'trendrider':
                    signal = strat.evaluate_at(df, i)
                else:
                    return []
            except Exception:
                continue

            if signal is None:
                continue

            side = signal.direction
            sig_type = signal.meta.get('signal_type', 'SIG')

            if cfg.get('PINBAR_DISABLED', False) and sig_type == 'PINBAR':
                continue
            if cfg.get('BOUNCE_DISABLED', False) and sig_type == 'BOUNCE':
                continue

            pending = {'type': side, 'signal_type': sig_type}

        return trades

    def metrics(trades):
        if not trades:
            return None
        total = len(trades)
        wins = sum(1 for t in trades if t['result'] == 'TAKE')
        pnl_usd_total = sum(t['pnl_usd'] for t in trades)

        pnl_pct_from_deposit = pnl_usd_total / START_BALANCE * 100
        pnl_pct_avg = sum(t['pnl'] for t in trades) / total

        profit_usd = sum(t['pnl_usd'] for t in trades if t['pnl_usd'] > 0)
        loss_usd = abs(sum(t['pnl_usd'] for t in trades if t['pnl_usd'] < 0))
        pf = profit_usd / loss_usd if loss_usd > 0 else 99.99

        eq_usd = [0.0]
        for t in trades:
            eq_usd.append(eq_usd[-1] + t['pnl_usd'])
        peak = eq_usd[0]
        dd_usd = 0.0
        for e in eq_usd:
            if e > peak:
                peak = e
            dd_usd = max(dd_usd, peak - e)
        dd_pct = dd_usd / START_BALANCE * 100 if START_BALANCE > 0 else 0

        avg_lev = sum(t.get('leverage', 1.0) for t in trades) / total
        avg_dur = sum(t.get('duration_h', 0) for t in trades) / total

        return {
            'total': total,
            'wins': wins,
            'winrate': wins / total * 100,
            'pnl': pnl_pct_from_deposit,
            'pnl_avg_pct': pnl_pct_avg,
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

    results = []
    all_trades = []
    positive = 0
    negative = 0

    total_syms = len(symbols)
    for idx, sym in enumerate(symbols):
        if cancel_check and cancel_check():
            log("⏹ Отменено")
            break

        log(f"[{idx + 1}/{total_syms}] {sym}...")
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
        'strategy_name': strategy_name,
    }