"""
Trailing Stop Manager.

Двигает стоп-лосс вслед за ценой, фиксируя прибыль.
Сохраняет существующий takeProfit при сдвиге стопа.

АДАПТИВНЫЙ РЕЖИМ (USE_TRAILING_ATR=True):
  - шаг и старт зависят от ATR% конкретной монеты.
  - Для волатильных монет — широкий шаг, чтобы не выбивало шумом.
  - Для спокойных — узкий шаг, чтобы фиксировать прибыль.
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
        return {}

    def _save_state(self):
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def update_all(self):
        if not getattr(config, 'USE_TRAILING_STOP', True):
            return

        open_positions = self.trader.state.get('open_positions', {})
        if not open_positions:
            return

        for symbol, pos in list(open_positions.items()):
            try:
                self._update_position(symbol, pos)
            except Exception as e:
                self.log(f"⚠ Trailing {symbol}: {str(e)[:60]}", "#ff9800")

    def _compute_step_and_start(self, pos):
        """
        Возвращает (step_pct, start_pct) для позиции.
        Если USE_TRAILING_ATR=True и есть atr_pct — использует ATR.
        Иначе — фиксированные значения из config.
        """
        use_atr = getattr(config, 'USE_TRAILING_ATR', True)
        atr_pct = pos.get('atr_pct')

        base_start = getattr(config, 'TRAILING_START_PCT', 4.0)
        base_step = getattr(config, 'TRAILING_STEP_PCT', 1.0)

        if use_atr and atr_pct and atr_pct > 0:
            step_pct = atr_pct * getattr(config, 'TRAILING_ATR_STEP_MULT', 0.4)
            start_pct = atr_pct * getattr(config, 'TRAILING_ATR_START_MULT', 1.0)

            step_min = getattr(config, 'TRAILING_ATR_MIN_PCT', 0.5)
            step_max = getattr(config, 'TRAILING_ATR_MAX_PCT', 5.0)
            step_pct = max(step_min, min(step_max, step_pct))

            # Старт не меньше базового
            start_pct = max(base_start, start_pct)
        else:
            step_pct = base_step
            start_pct = base_start

        return step_pct, start_pct

    def _update_position(self, symbol, pos):
        from bybit_client import get_ticker

        try:
            current = get_ticker(self.trader.exchange, symbol)
        except Exception:
            return

        entry = pos['entry']
        side = pos['side']
        current_stop = pos['stop']

        if side == 'LONG':
            pnl_pct = (current - entry) / entry * 100
        else:
            pnl_pct = (entry - current) / entry * 100

        # ==== АДАПТИВНЫЙ ШАГ И СТАРТ ====
        step_pct, start_pct = self._compute_step_and_start(pos)

        if pnl_pct < start_pct:
            return

        if symbol not in self.state:
            self.state[symbol] = {
                'best_price': current,
                'last_stop': current_stop,
                'started_at': datetime.now(timezone.utc).isoformat(),
                'step_pct': step_pct,
            }

        trail = self.state[symbol]
        trail['step_pct'] = step_pct

        # Обновляем "лучшую" цену
        if side == 'LONG':
            if current > trail['best_price']:
                trail['best_price'] = current
        else:
            if current < trail['best_price']:
                trail['best_price'] = current

        # Новый стоп
        if side == 'LONG':
            new_stop = trail['best_price'] * (1 - step_pct / 100)
            if new_stop <= current_stop:
                return
        else:
            new_stop = trail['best_price'] * (1 + step_pct / 100)
            if new_stop >= current_stop:
                return

        # Округляем до точности монеты
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

        ok, msg = self._set_new_stop(symbol, pos, new_stop)

        if ok:
            pos['stop'] = new_stop
            self.trader.state['open_positions'][symbol] = pos
            self.trader._save_state()

            trail['last_stop'] = new_stop
            self._save_state()

            self.log(
                f"📈 Trailing {symbol}: стоп → {new_stop:.6f} "
                f"(best {trail['best_price']:.6f}, "
                f"шаг {step_pct:.2f}%, P&L {pnl_pct:+.2f}%)",
                "#4caf50"
            )

    def _set_new_stop(self, symbol, pos, new_stop):
        try:
            from bybit_client import get_clean_symbol, get_position_idx

            clean = get_clean_symbol(symbol)
            mode = self.trader.position_mode
            idx = pos.get('position_idx', get_position_idx(mode, pos['side']))

            existing_tp = pos.get('take')
            if existing_tp is None:
                return False, "нет takeProfit"

            params = {
                'category': 'linear',
                'symbol': clean,
                'tpslMode': 'Full',
                'slTriggerBy': 'LastPrice',
                'tpTriggerBy': 'LastPrice',
                'stopLoss': str(new_stop),
                'takeProfit': str(existing_tp),
                'positionIdx': idx,
            }

            result = self.trader.exchange.private_post_v5_position_trading_stop(params)

            if result.get('retCode') == 0:
                return True, "OK"
            return False, result.get('retMsg', 'unknown')
        except Exception as e:
            return False, str(e)[:80]

    def clear(self, symbol):
        if symbol in self.state:
            del self.state[symbol]
            self._save_state()


if __name__ == '__main__':
    print("TrailingManager — адаптивный по ATR")
    print("Формула: step = ATR% × TRAILING_ATR_STEP_MULT")
    print("          start = ATR% × TRAILING_ATR_START_MULT")