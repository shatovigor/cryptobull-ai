"""
Обёртка над ccxt для Bybit.
С кэшем balance/equity и retry для API-запросов.
"""
import os
import time
import ccxt
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ==== КЭШ ====
_balance_cache = {'data': None, 'ts': 0}
_equity_cache = {'data': None, 'ts': 0}
CACHE_TTL = 30  # секунд


def _fetch_with_retry(func, *args, max_attempts=3, delay=2, **kwargs):
    """
    Retry для API-запросов.
    При rate limit (10006) — пауза растёт: 2с, 4с, 6с.
    """
    last_error = None
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            err = str(e).lower()

            # Rate limit — увеличиваем паузу
            if '10006' in err or 'too many' in err:
                wait = delay * (attempt + 1)
                time.sleep(wait)
                continue

            # Другие ошибки — retry с обычной паузой
            if attempt < max_attempts - 1:
                time.sleep(delay)
                continue
            raise

    raise last_error


def make_exchange(api_key=None, api_secret=None, testnet=None):
    """Создаёт подключение к Bybit."""
    if api_key is None:
        api_key = os.getenv('BYBIT_API_KEY')
    if api_secret is None:
        api_secret = os.getenv('BYBIT_API_SECRET')
    if testnet is None:
        testnet = os.getenv('BYBIT_TESTNET', 'False').lower() == 'true'

    if not api_key or not api_secret:
        raise ValueError("BYBIT_API_KEY или BYBIT_API_SECRET не заданы")

    urls = None
    if testnet:
        urls = {
            'api': {
                'public': 'https://api-testnet.bybit.com',
                'private': 'https://api-testnet.bybit.com',
            }
        }

    return ccxt.bybit({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
        **({'urls': urls} if urls else {}),
    })


def check_connection(exchange, use_cache=True):
    """Баланс USDT с кэшем 30 сек."""
    global _balance_cache
    now = time.time()

    if use_cache and _balance_cache['data'] and (now - _balance_cache['ts']) < CACHE_TTL:
        return _balance_cache['data']

    balance = _fetch_with_retry(exchange.fetch_balance)
    usdt = balance.get('USDT', {})
    result = {
        'total': usdt.get('total', 0),
        'free': usdt.get('free', 0),
        'used': usdt.get('used', 0),
    }
    _balance_cache = {'data': result, 'ts': now}
    return result


def get_equity(exchange, use_cache=True):
    """Equity аккаунта с кэшем."""
    global _equity_cache
    now = time.time()

    if use_cache and _equity_cache['data'] and (now - _equity_cache['ts']) < CACHE_TTL:
        return _equity_cache['data']

    try:
        result = _fetch_with_retry(
            exchange.private_get_v5_account_wallet_balance,
            {'accountType': 'UNIFIED'}
        )
        if result.get('retCode') != 0:
            return None

        accounts = result.get('result', {}).get('list', [])
        if not accounts:
            return None

        acc = accounts[0]
        data = {
            'equity': float(acc.get('totalEquity', 0)),
            'wallet_balance': float(acc.get('totalWalletBalance', 0)),
            'unrealized_pnl': float(acc.get('totalPerpUPL', 0)),
            'margin_used': float(acc.get('totalInitialMargin', 0)),
            'available': float(acc.get('totalAvailableBalance', 0)),
        }
        _equity_cache = {'data': data, 'ts': now}
        return data
    except Exception as e:
        print(f"Equity error: {e}")
        return None


def clear_cache():
    """Сбросить кэш баланса и equity."""
    global _balance_cache, _equity_cache
    _balance_cache = {'data': None, 'ts': 0}
    _equity_cache = {'data': None, 'ts': 0}


def test_api_keys(api_key, api_secret, testnet=False):
    """Проверка ключей без кэша."""
    try:
        ex = make_exchange(api_key, api_secret, testnet)
        bal = check_connection(ex, use_cache=False)
        return True, f"✅ Подключение OK. Баланс: ${bal['total']:.2f}"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)[:100]}"


def get_clean_symbol(symbol):
    """XRP/USDT:USDT → XRPUSDT"""
    return symbol.split(':')[0].replace('/', '')


def get_position_mode(exchange):
    """Определяет режим позиции: 'hedge' или 'one_way'."""
    try:
        result = _fetch_with_retry(
            exchange.private_get_v5_position_list,
            {'category': 'linear', 'settleCoin': 'USDT', 'limit': 10}
        )
        if result.get('retCode') != 0:
            return 'one_way'

        positions = result.get('result', {}).get('list', [])
        for p in positions:
            if abs(float(p.get('size', 0) or 0)) > 0:
                idx = p.get('positionIdx')
                if idx in (1, 2):
                    return 'hedge'
                return 'one_way'
        return 'one_way'
    except Exception:
        return 'one_way'


def get_position_idx(mode, side):
    """positionIdx для ордера."""
    if mode == 'hedge':
        return 1 if side == 'LONG' else 2
    return 0


def set_leverage(exchange, symbol, leverage):
    """Устанавливает плечо для пары."""
    try:
        clean_symbol = symbol.split(':')[0].replace('/', '')

        # Способ 1: прямой API Bybit v5
        try:
            result = _fetch_with_retry(
                exchange.private_post_v5_position_set_leverage,
                {
                    'category': 'linear',
                    'symbol': clean_symbol,
                    'buyLeverage': str(leverage),
                    'sellLeverage': str(leverage),
                }
            )
            if result.get('retCode') == 0:
                return True
            ret_msg = result.get('retMsg', '')
            if 'not modified' in ret_msg.lower() or '110043' in str(result.get('retCode')):
                return True
            last_error = Exception(f"Bybit: {ret_msg}")
        except Exception as e:
            last_error = e

        # Способ 2: ccxt
        try:
            exchange.set_leverage(leverage, clean_symbol, params={'category': 'linear'})
            return True
        except Exception as e:
            err = str(e).lower()
            if 'not modified' in err or '110043' in err:
                return True
            last_error = e

        if last_error:
            raise last_error
        return True
    except Exception as e:
        err = str(e).lower()
        if 'not modified' in err or '110043' in err:
            return True
        raise


def set_trading_stop(exchange, symbol, stop_price, take_price, mode='one_way', side='LONG'):
    """Устанавливает стоп и тейк через Bybit v5."""
    try:
        clean_symbol = get_clean_symbol(symbol)
        position_idx = get_position_idx(mode, side)

        params = {
            'category': 'linear',
            'symbol': clean_symbol,
            'tpslMode': 'Full',
            'tpTriggerBy': 'LastPrice',
            'slTriggerBy': 'LastPrice',
            'stopLoss': str(stop_price),
            'takeProfit': str(take_price),
            'positionIdx': position_idx,
        }

        result = _fetch_with_retry(
            exchange.private_post_v5_position_trading_stop,
            params
        )
        if result.get('retCode') == 0:
            return True, "✅ SL/TP установлены"
        return False, f"Bybit: {result.get('retMsg', 'unknown')}"
    except Exception as e:
        return False, str(e)[:100]


def get_ticker(exchange, symbol):
    """Текущая цена."""
    t = _fetch_with_retry(exchange.fetch_ticker, symbol)
    return t['last']


def get_min_amount(exchange, symbol):
    """Минимальный размер позиции."""
    markets = exchange.load_markets()
    if symbol not in markets:
        return None
    m = markets[symbol]
    return {
        'min_amount': m.get('limits', {}).get('amount', {}).get('min', 0),
        'min_cost': m.get('limits', {}).get('cost', {}).get('min', 0),
        'amount_precision': m.get('precision', {}).get('amount', 6),
        'price_precision': m.get('precision', {}).get('price', 6),
    }


def get_closed_pnl(exchange, days=1):
    """Закрытые сделки за N дней."""
    from datetime import timedelta
    try:
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        result = _fetch_with_retry(
            exchange.private_get_v5_position_closed_pnl,
            {'category': 'linear', 'startTime': start_time, 'limit': 100}
        )
        if result.get('retCode') != 0:
            return []
        return result.get('result', {}).get('list', [])
    except Exception:
        return []


if __name__ == '__main__':
    print("=" * 50)
    print("ТЕСТ BYBIT CLIENT")
    print("=" * 50)
    ex = make_exchange()

    print("\n1. Баланс (первый раз — без кэша)")
    t0 = time.time()
    bal = check_connection(ex)
    t1 = time.time()
    print(f"   Баланс: ${bal['total']:.2f}")
    print(f"   Время: {(t1-t0)*1000:.0f} мс")

    print("\n2. Баланс (второй раз — из кэша)")
    t0 = time.time()
    bal2 = check_connection(ex)
    t1 = time.time()
    print(f"   Баланс: ${bal2['total']:.2f}")
    print(f"   Время: {(t1-t0)*1000:.0f} мс (должно быть <5 мс)")

    print("\n3. Equity")
    eq = get_equity(ex)
    if eq:
        print(f"   Equity: ${eq['equity']:.2f}")
        print(f"   P&L: ${eq['unrealized_pnl']:+.2f}")

    print("\n4. Режим позиции")
    mode = get_position_mode(ex)
    print(f"   Режим: {mode.upper()}")

    print("\n✅ Всё работает")