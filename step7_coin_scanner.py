"""
Автоподбор монет для торговли.
Все фильтры читаются из config.py — их можно менять из GUI.

ИСПРАВЛЕНИЕ: top_n передаётся параметром, а не через мутацию config,
чтобы избежать race condition при параллельном доступе.
"""
import ccxt
import pandas as pd
import numpy as np
import time

import config


def _get_param(name, default):
    return getattr(config, name, default)


def get_all_swap_symbols(exchange):
    markets = exchange.load_markets()
    symbols = []
    for sym, m in markets.items():
        if (m.get('swap') and m.get('linear')
            and m.get('quote') == 'USDT'
            and m.get('active')):
            symbols.append(sym)
    return symbols


def get_atr_pct(exchange, symbol, days=20):
    try:
        raw = exchange.fetch_ohlcv(symbol, '1d', limit=days)
        if len(raw) < days:
            return None
        df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        ranges = (df['high'] - df['low']) / df['close'] * 100
        return ranges.mean()
    except Exception:
        return None


def get_3day_move_pct(exchange, symbol):
    try:
        raw = exchange.fetch_ohlcv(symbol, '1d', limit=4)
        if len(raw) < 4:
            return None
        df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        high_3d = df['high'].tail(3).max()
        low_3d = df['low'].tail(3).min()
        mid = df['close'].iloc[-1]
        return (high_3d - low_3d) / mid * 100
    except Exception:
        return None


def scan_coins(verbose=True, progress_callback=None, top_n=None):
    """
    Сканирует Bybit и возвращает DataFrame с найденными монетами.
    top_n: если задан — используется вместо config.SCANNER_TOP_N
    """
    MAX_PRICE = _get_param('SCANNER_MAX_PRICE', 5.0)
    MIN_VOLUME_USD = _get_param('SCANNER_MIN_VOLUME_USD', 15_000_000)
    MIN_ATR_PCT = _get_param('SCANNER_MIN_ATR_PCT', 6.0)
    MAX_ATR_PCT = _get_param('SCANNER_MAX_ATR_PCT', 11.0)
    MIN_CHANGE_PCT = _get_param('SCANNER_MIN_CHANGE_PCT', 2.0)
    MAX_CHANGE_PCT = _get_param('SCANNER_MAX_CHANGE_PCT', 15.0)
    MIN_DAILY_CANDLES = _get_param('SCANNER_MIN_DAILY_CANDLES', 90)
    MAX_3DAY_MOVE_PCT = _get_param('SCANNER_MAX_3DAY_MOVE_PCT', 20.0)
    BLACKLIST = _get_param('SCANNER_BLACKLIST', [])

    if top_n is None:
        top_n = _get_param('SCANNER_TOP_N', 10)

    def log(msg):
        if verbose:
            print(msg)
        if progress_callback:
            progress_callback(msg)

    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    })

    log("Загружаю рынки Bybit...")
    symbols = get_all_swap_symbols(exchange)
    symbols = [s for s in symbols if s not in BLACKLIST]

    log(f"Фьючерсных пар (без чёрного списка): {len(symbols)}")
    log("Загружаю тикеры...")
    tickers = exchange.fetch_tickers()

    candidates = []
    for sym in symbols:
        try:
            t = tickers.get(sym)
            if not t:
                continue
            price = t.get('last')
            change = t.get('percentage')
            volume_usd = t.get('quoteVolume')

            if price is None or change is None or volume_usd is None:
                continue
            if price > MAX_PRICE:
                continue
            if volume_usd < MIN_VOLUME_USD:
                continue
            if abs(change) < MIN_CHANGE_PCT or abs(change) > MAX_CHANGE_PCT:
                continue

            candidates.append({
                'symbol': sym, 'price': price,
                'change_24h': change, 'volume_usd': volume_usd,
            })
        except Exception:
            continue

    log(f"Прошло первичный фильтр: {len(candidates)}")
    log("Считаю ATR и историю...")

    results = []
    for i, c in enumerate(candidates):
        if progress_callback and (i + 1) % 5 == 0:
            progress_callback(f"  ... {i+1}/{len(candidates)}")

        try:
            daily = exchange.fetch_ohlcv(c['symbol'], '1d', limit=MIN_DAILY_CANDLES)
            if len(daily) < MIN_DAILY_CANDLES:
                continue
        except Exception:
            continue

        atr = get_atr_pct(exchange, c['symbol'])
        if atr is None or atr < MIN_ATR_PCT or atr > MAX_ATR_PCT:
            continue

        move_3d = get_3day_move_pct(exchange, c['symbol'])
        if move_3d is None or move_3d > MAX_3DAY_MOVE_PCT:
            continue

        c['atr_pct'] = atr
        c['move_3d_pct'] = move_3d
        results.append(c)
        time.sleep(0.3)

    df = pd.DataFrame(results)
    if df.empty:
        return df
    df = df.sort_values('atr_pct', ascending=False)
    return df.head(top_n)


def print_results(df):
    if df.empty:
        print("Ничего не найдено.")
        return
    print()
    print(f"{'Монета':<24} {'Цена':>12} {'24ч %':>8} {'ATR%':>6} {'3д дв.':>8} {'Объём $':>15}")
    print("-" * 82)
    for _, row in df.iterrows():
        print(f"{row['symbol']:<24} {row['price']:>12.6f} "
              f"{row['change_24h']:>+7.2f}% {row['atr_pct']:>6.2f} "
              f"{row['move_3d_pct']:>7.1f}% {row['volume_usd']:>15,.0f}")


def get_top_symbols(n=None, verbose=False, progress_callback=None):
    """
    Возвращает список тикеров — топ N монет.
    ИСПРАВЛЕНИЕ: не мутирует config.SCANNER_TOP_N.
    """
    df = scan_coins(verbose=verbose, progress_callback=progress_callback, top_n=n)
    return [] if df.empty else df['symbol'].tolist()


if __name__ == '__main__':
    print("=" * 60)
    print("АВТОПОДБОР МОНЕТ")
    print(f"  Цена:         < ${config.SCANNER_MAX_PRICE}")
    print(f"  Объём 24ч:    > ${config.SCANNER_MIN_VOLUME_USD:,}")
    print(f"  ATR%:         {config.SCANNER_MIN_ATR_PCT} .. {config.SCANNER_MAX_ATR_PCT}")
    print(f"  Изменение:    ±{config.SCANNER_MIN_CHANGE_PCT} .. ±{config.SCANNER_MAX_CHANGE_PCT}%")
    print(f"  История:      > {config.SCANNER_MIN_DAILY_CANDLES} дней")
    print(f"  Движение 3д:  < {config.SCANNER_MAX_3DAY_MOVE_PCT}%")
    print(f"  Топ:          {config.SCANNER_TOP_N}")
    print("=" * 60)

    df = scan_coins()
    print_results(df)