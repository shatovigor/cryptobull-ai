"""
Автоподбор монет под размер депозита.

Логика:
  1. Берём free balance аккаунта.
  2. Считаем размер одной позиции: free × AUTO_POSITION_PCT / 100.
  3. Отсеиваем монеты, где этот размер < минимального notional Bybit.
  4. Проверяем ATR% (волатильность).
  5. Проверяем объём 24ч (ликвидность).
  6. Возвращаем список подходящих монет.

Используется в auto_trader._deposit_auto_scan_coins().
"""

import ccxt
import pandas as pd
import time

import config


def _get_param(name, default):
    return getattr(config, name, default)


def _fetch_24h_volume(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker.get('quoteVolume') or 0)
    except Exception:
        return 0.0


def _calc_atr_pct(exchange, symbol, days=20):
    try:
        raw = exchange.fetch_ohlcv(symbol, '1d', limit=days)
        if len(raw) < days:
            return None
        df = pd.DataFrame(raw, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        atr_pct = ((df['h'] - df['l']) / df['c'] * 100).mean()
        return float(atr_pct)
    except Exception:
        return None


def scan_for_deposit(free_balance, verbose=False, progress_callback=None):
    """
    Возвращает список монет, подходящих под текущий free balance.
    """
    def log(msg):
        if verbose:
            print(msg)
        if progress_callback:
            progress_callback(msg)

    if free_balance <= 0:
        log(f"⚠ free_balance = {free_balance} — пропуск")
        return []

    # Кандидаты
    if _get_param('DEPOSIT_USE_AUTOSCAN', False):
        try:
            from step7_coin_scanner import get_top_symbols
            candidates = get_top_symbols(
                n=30, verbose=False, progress_callback=progress_callback
            )
            log(f"Сканер вернул {len(candidates)} кандидатов")
        except Exception as e:
            log(f"⚠ Сканер упал: {e}")
            candidates = list(_get_param('DEPOSIT_STATIC_CANDIDATES', []))
    else:
        candidates = list(_get_param('DEPOSIT_STATIC_CANDIDATES', []))

    if not candidates:
        log("⚠ Нет кандидатов")
        return []

    # Чёрный список
    blacklist = set(_get_param('SCANNER_BLACKLIST', []))
    candidates = [c for c in candidates if c not in blacklist]

    # Размер позиции
    pct = _get_param('AUTO_POSITION_PCT', 5.0)
    min_pos_pct = _get_param('DEPOSIT_MIN_POSITION_PCT', 0.5)

    position_size = free_balance * (pct / 100)
    position_size = max(position_size, free_balance * min_pos_pct / 100)

    log(f"💰 Депозит: ${free_balance:.2f}, размер позиции: ${position_size:.2f}")

    # Проверка min notional
    min_notional = _get_param('DEPOSIT_MIN_NOTIONAL_USD', 5.0)
    if position_size < min_notional:
        log(
            f"⚠ Размер позиции ${position_size:.2f} < min notional "
            f"${min_notional:.2f}"
        )
        return []

    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    })

    try:
        exchange.load_markets()
    except Exception as e:
        log(f"⚠ Не удалось загрузить рынки: {e}")
        return []

    min_atr = _get_param('DEPOSIT_MIN_ATR_PCT', 5.0)
    max_atr = _get_param('DEPOSIT_MAX_ATR_PCT', 9.0)
    min_volume = _get_param('DEPOSIT_MIN_VOLUME_USD', 20_000_000)

    suitable = []

    for i, sym in enumerate(candidates):
        if progress_callback and (i + 1) % 3 == 0:
            progress_callback(f"  проверка {i+1}/{len(candidates)}...")

        try:
            if sym not in exchange.markets:
                continue

            m = exchange.markets[sym]

            min_amt = m.get('limits', {}).get('amount', {}).get('min', 0)
            if not min_amt:
                continue

            volume = _fetch_24h_volume(exchange, sym)
            if volume < min_volume:
                continue

            atr = _calc_atr_pct(exchange, sym)
            if atr is None or atr < min_atr or atr > max_atr:
                continue

            ticker = exchange.fetch_ticker(sym)
            price = float(ticker.get('last') or 0)
            if price <= 0:
                continue

            min_cost = min_amt * price
            if min_cost > position_size:
                continue

            suitable.append({
                'symbol': sym,
                'price': price,
                'atr_pct': atr,
                'volume_usd': volume,
                'min_cost': min_cost,
                'min_amt': min_amt,
            })

            time.sleep(0.2)
        except Exception:
            continue

    # Сортируем: ближе к ATR 7% — выше
    def score(x):
        return abs(x['atr_pct'] - 7.0)

    suitable.sort(key=score)

    max_positions = _get_param('DEPOSIT_MAX_POSITIONS', 5)
    result = [x['symbol'] for x in suitable[:max_positions]]

    log(f"✅ Подходящих монет: {len(result)}")
    for x in suitable[:max_positions]:
        log(
            f"   {x['symbol']}: ATR {x['atr_pct']:.1f}%, "
            f"объём ${x['volume_usd']/1e6:.1f}M, "
            f"мин. ${x['min_cost']:.2f}"
        )

    return result


if __name__ == '__main__':
    print("=" * 60)
    print("АВТОПОДБОР МОНЕТ ПОД ДЕПОЗИТ")
    print("=" * 60)

    result = scan_for_deposit(free_balance=540.0, verbose=True)
    print()
    print(f"РЕЗУЛЬТАТ ({len(result)}):")
    for s in result:
        print(f"  {s}")