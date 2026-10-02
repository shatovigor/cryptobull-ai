"""
Trailing Stop Manager.
Двигает стоп-лосс вслед за ценой, фиксируя прибыль.
"""
import json
import os
from datetime import datetime, timezone

import config


class TrailingManager:
    def __init__(self, trader, log_func=None):
        self.trader = trader
        self.log = log_func or print
        self.state_file = 'trailing_state.json'
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}  # symbol -> {'best_price': ..., 'last_stop': ...}

    def _save_state(self):
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def update_all(self):
        """Обновляет trailing stop для всех открытых позиций.
           Вызывается каждые 60 секунд."""
        if not getattr(config, 'USE_TRAILING_STOP', True):
            return

        # self.trader — это AutoTrader (передаётся в __init__). У него есть .state, .exchange, .position_mode
        open_positions = self.trader.state.get('open_positions', {})
        if not open_positions:
            return

        for symbol, pos in list(open_positions.items()):
            try:
                self._update_position(symbol, pos)
            except Exception as e:
                self.log(f"⚠ Trailing {symbol}: {str(e)[:60]}", "#ff9800")

    def _update_position(self, symbol, pos):
        """Обновляет trailing stop для одной позиции."""
        from bybit_client import get_ticker

        # Текущая цена
        try:
            current = get_ticker(self.trader.exchange, symbol)
        except Exception:
            return

        entry = pos['entry']
        side = pos['side']
        current_stop = pos['stop']

        # Текущий P&L%
        if side == 'LONG':
            pnl_pct = (current - entry) / entry * 100
        else:
            pnl_pct = (entry - current) / entry * 100

        # Если ещё не достигли порога — не трогаем
        start_pct = getattr(config, 'TRAILING_START_PCT', 1.0)
        if pnl_pct < start_pct:
            return

        # Состояние trailing для этой позиции
        if symbol not in self.state:
            self.state[symbol] = {
                'best_price': current,
                'last_stop': current_stop,
                'started_at': datetime.now(timezone.utc).isoformat(),
            }

        trail = self.state[symbol]

        # Обновляем "лучшую" цену (для SHORT — минимальная, для LONG — максимальная)
        if side == 'LONG':
            if current > trail['best_price']:
                trail['best_price'] = current
        else:
            if current < trail['best_price']:
                trail['best_price'] = current

        # Рассчитываем новый стоп
        step_pct = getattr(config, 'TRAILING_STEP_PCT', 0.5)

        if side == 'LONG':
            # Стоп двигается ВВЕРХ
            new_stop = trail['best_price'] * (1 - step_pct / 100)
            # Не двигаем вниз
            if new_stop <= current_stop:
                return
        else:
            # Стоп двигается ВНИЗ
            new_stop = trail['best_price'] * (1 + step_pct / 100)
            # Не двигаем вверх
            if new_stop >= current_stop:
                return

        # Округляем
        try:
            from bybit_client import get_min_amount
            info = get_min_amount(self.trader.exchange, symbol)
            precision = info['price_precision'] if info else 6
            if isinstance(precision, int):
                new_stop = round(new_stop, precision)
            else:
                new_stop = float(self.trader.exchange.price_to_precision(symbol, new_stop))
        except Exception:
            pass

        # Устанавливаем новый стоп на бирже
        ok, msg = self._set_new_stop(symbol, pos, new_stop)

        if ok:
            # Сохраняем в state позиции
            pos['stop'] = new_stop
            self.trader.state['open_positions'][symbol] = pos
            self.trader._save_state()

            trail['last_stop'] = new_stop
            self._save_state()

            self.log(
                f"📈 Trailing {symbol}: стоп → {new_stop:.6f} "
                f"(лучшая цена {trail['best_price']:.6f}, P&L {pnl_pct:+.2f}%)",
                "#4caf50"
            )

    def _set_new_stop(self, symbol, pos, new_stop):
        """Устанавливает новый стоп через Bybit API."""
        try:
            from bybit_client import get_clean_symbol, get_position_idx

            clean = get_clean_symbol(symbol)
            mode = self.trader.position_mode
            idx = pos.get('position_idx', get_position_idx(mode, pos['side']))

            params = {
                'category': 'linear',
                'symbol': clean,
                'tpslMode': 'Full',
                'slTriggerBy': 'LastPrice',
                'stopLoss': str(new_stop),
                'positionIdx': idx,
            }

            # Не трогаем takeProfit — оставляем как есть
            # (Bybit требует оба поля? Проверим)

            result = self.trader.exchange.private_post_v5_position_trading_stop(params)

            if result.get('retCode') == 0:
                return True, "OK"
            return False, result.get('retMsg', 'unknown')
        except Exception as e:
            return False, str(e)[:80]

    def clear(self, symbol):
        """Удаляет состояние trailing для символа (когда позиция закрыта)."""
        if symbol in self.state:
            del self.state[symbol]
            self._save_state()


if __name__ == '__main__':
    print("TrailingManager — модуль для trailing stop")
    print("Используется из auto_trader.py")