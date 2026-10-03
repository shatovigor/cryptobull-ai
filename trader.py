"""
Торговый модуль. Открывает и закрывает позиции.
Поддерживает адаптивный стоп по ATR.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone

from bybit_client import (
    make_exchange, set_leverage, get_ticker, get_min_amount,
    set_trading_stop, get_position_mode, get_position_idx,
)
import config


class Trader:
    def __init__(self):
        self.exchange = make_exchange()
        self.state = self._load_state()
        self.position_mode = get_position_mode(self.exchange)
        print(f"📊 Режим позиции: {self.position_mode}")

    def _load_state(self):
        if os.path.exists(config.STATE_FILE):
            try:
                with open(config.STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'open_positions': {}, 'daily_stats': {}}

    def _save_state(self):
        try:
            with open(config.STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, default=str, ensure_ascii=False)
        except Exception:
            pass

    def _today(self):
        return datetime.now(timezone.utc).strftime('%Y-%m-%d')

    def _today_stats(self):
        d = self._today()
        if d not in self.state['daily_stats']:
            self.state['daily_stats'][d] = {'trades': 0, 'pnl': 0.0}
        return self.state['daily_stats'][d]

    def can_open_trade(self, symbol, allow_duplicate=False):
        if not allow_duplicate and symbol in self.state['open_positions']:
            return False, "позиция уже открыта"

        if len(self.state['open_positions']) >= config.MAX_POSITIONS_TOTAL:
            return False, f"уже {len(self.state['open_positions'])} позиций"

        stats = self._today_stats()
        if stats['pnl'] <= -config.DAILY_LOSS_LIMIT_PCT:
            return False, f"дневной убыток {stats['pnl']:.2f}%"

        if stats['trades'] >= config.MAX_TRADES_PER_DAY:
            return False, f"сделок за день: {stats['trades']}"

        return True, "ok"

    def _open_order(self, symbol, side, amount, position_idx):
        order_side = 'buy' if side == 'LONG' else 'sell'
        client_id = f"cba-{uuid.uuid4().hex[:16]}"

        if side == 'LONG':
            idx_candidates = [position_idx, 0, 1, 2]
        else:
            idx_candidates = [position_idx, 0, 2, 1]

        seen = set()
        idx_candidates = [x for x in idx_candidates if not (x in seen or seen.add(x))]

        last_error = None

        for idx in idx_candidates:
            try:
                order = self.exchange.create_order(
                    symbol=symbol, type='market', side=order_side,
                    amount=amount,
                    params={
                        'reduceOnly': False,
                        'positionIdx': idx,
                        'orderLinkId': client_id,
                    },
                )
                return order, idx, None
            except Exception as e:
                err = str(e)
                last_error = e

                if 'orderlinkid' in err.lower() and (
                    'duplicate' in err.lower() or 'already' in err.lower()
                ):
                    try:
                        existing = self.exchange.fetch_order(
                            None, symbol, {'orderLinkId': client_id}
                        )
                        return existing, idx, None
                    except Exception:
                        pass

                if '10001' in err or 'position idx' in err.lower():
                    time.sleep(0.3)
                    continue
                return None, None, e

        return None, None, last_error

    def open_position(self, symbol, side, entry_hint=None, stop_pct=None, take_pct=None,
                      size_usd=None, allow_duplicate=False, atr_pct=None, leverage=None):
        can, reason = self.can_open_trade(symbol, allow_duplicate=allow_duplicate)
        if not can:
            return False, f"Нельзя: {reason}", None

        _lev = leverage if leverage is not None else config.LEVERAGE
        try:
            set_leverage(self.exchange, symbol, _lev)
        except Exception as e:
            return False, f"Плечо: {e}", None

        try:
            price = get_ticker(self.exchange, symbol)
        except Exception as e:
            return False, f"Цена: {e}", None

        position_usd = size_usd if size_usd else config.MAX_POSITION_USD
        amount = position_usd / price

        info = get_min_amount(self.exchange, symbol)
        if info and amount < info['min_amount']:
            return False, f"Мало: {amount:.6f} < {info['min_amount']}", None

        try:
            amount = float(self.exchange.amount_to_precision(symbol, amount))
        except Exception:
            amount = round(amount, 6)

        # ==== АДАПТИВНЫЙ СТОП ПО ATR ====
        if stop_pct is None and take_pct is None:
            if getattr(config, 'USE_ADAPTIVE_STOP', False) and atr_pct is not None:
                stop_pct = atr_pct * getattr(config, 'ADAPTIVE_STOP_ATR_MULT', 0.6)
                take_pct = atr_pct * getattr(config, 'ADAPTIVE_TAKE_ATR_MULT', 1.2)

                stop_pct = max(
                    getattr(config, 'ADAPTIVE_STOP_MIN_PCT', 1.5),
                    min(getattr(config, 'ADAPTIVE_STOP_MAX_PCT', 8.0), stop_pct)
                )
                take_pct = max(
                    getattr(config, 'ADAPTIVE_TAKE_MIN_PCT', 3.0),
                    min(getattr(config, 'ADAPTIVE_TAKE_MAX_PCT', 16.0), take_pct)
                )
                print(f"   📐 ATR {atr_pct:.2f}% → SL {stop_pct:.2f}% / TP {take_pct:.2f}%")
            else:
                stop_pct = config.STOP_PCT_CALM
                take_pct = config.TAKE_PCT_CALM
        elif stop_pct is None:
            stop_pct = config.STOP_PCT_CALM
        elif take_pct is None:
            take_pct = config.TAKE_PCT_CALM

        position_idx = get_position_idx(self.position_mode, side)

        order, used_idx, err = self._open_order(symbol, side, amount, position_idx)
        if order is None:
            return False, f"Открытие: {err}", None

        if used_idx in (1, 2):
            self.position_mode = 'hedge'
        else:
            self.position_mode = 'one_way'

        try:
            time.sleep(1)
            order_info = self.exchange.fetch_order(order['id'], symbol)
            filled_price = order_info.get('average') or price
        except Exception:
            filled_price = price

        if side == 'LONG':
            stop_price = filled_price * (1 - stop_pct / 100)
            take_price = filled_price * (1 + take_pct / 100)
        else:
            stop_price = filled_price * (1 + stop_pct / 100)
            take_price = filled_price * (1 - take_pct / 100)

        try:
            precision = info['price_precision'] if info else 6
            if isinstance(precision, int):
                stop_price = round(stop_price, precision)
                take_price = round(take_price, precision)
        except Exception:
            pass

        time.sleep(1)
        stop_ok, stop_msg = set_trading_stop(
            self.exchange, symbol, stop_price, take_price,
            mode=self.position_mode, side=side
        )

        position = {
            'symbol': symbol,
            'side': side,
            'entry': filled_price,
            'amount': amount,
            'usd_size': position_usd,
            'stop': stop_price,
            'take': take_price,
            'open_ts': datetime.now(timezone.utc).isoformat(),
            'order_id': order.get('id'),
            'stop_pct': stop_pct,
            'take_pct': take_pct,
            'stop_set': stop_ok,
            'position_idx': used_idx,
            'position_mode': self.position_mode,
            'leverage': _lev,
            'adds': [],
            'hedge': None,
        }

        self.state['open_positions'][symbol] = position
        self._save_state()

        return True, f"Открыта {side} {symbol} @ {filled_price} (SL {stop_pct:.2f}% / TP {take_pct:.2f}%)", position

    def close_position(self, symbol, reason="manual"):
        if symbol not in self.state['open_positions']:
            return False, "Позиции нет"

        pos = self.state['open_positions'][symbol]

        try:
            positions = self.exchange.fetch_positions()
            has = any(
                abs(float(p.get('contracts', 0) or 0)) > 0
                and p.get('symbol') == symbol
                for p in positions
            )
            if not has:
                del self.state['open_positions'][symbol]
                self._save_state()
                self._clear_trailing(symbol)
                return True, "Уже закрыта"
        except Exception:
            pass

        position_idx = pos.get('position_idx', 0)

        try:
            close_side = 'sell' if pos['side'] == 'LONG' else 'buy'
            order = self.exchange.create_order(
                symbol=symbol, type='market', side=close_side,
                amount=pos['amount'],
                params={'reduceOnly': True, 'positionIdx': position_idx},
            )
        except Exception as e:
            return False, f"Закрытие: {e}"

        try:
            time.sleep(1)
            order_info = self.exchange.fetch_order(order['id'], symbol)
            exit_price = order_info.get('average') or get_ticker(self.exchange, symbol)
        except Exception:
            exit_price = get_ticker(self.exchange, symbol)

        pnl_pct = self._calc_pnl_pct(pos, exit_price)
        self._today_stats()['pnl'] += pnl_pct
        del self.state['open_positions'][symbol]
        self._save_state()
        self._clear_trailing(symbol)

        return True, f"Закрыта @ {exit_price} (P&L {pnl_pct:+.2f}%)"

    def _clear_trailing(self, symbol):
        try:
            ts_file = 'trailing_state.json'
            if not os.path.exists(ts_file):
                return
            with open(ts_file, 'r', encoding='utf-8') as f:
                st = json.load(f)
            if symbol in st:
                del st[symbol]
                with open(ts_file, 'w', encoding='utf-8') as f:
                    json.dump(st, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _calc_pnl_pct(self, pos, exit_price):
        if pos['side'] == 'LONG':
            gross = (exit_price - pos['entry']) / pos['entry'] * 100
        else:
            gross = (pos['entry'] - exit_price) / pos['entry'] * 100

        lev = float(pos.get('leverage', 1.0) or 1.0)
        gross_with_lev = gross * lev

        costs = 2 * (config.COMMISSION_PCT + config.SLIPPAGE_PCT) * lev
        return gross_with_lev - costs

    def close_all(self):
        results = []
        for symbol in list(self.state['open_positions'].keys()):
            ok, msg = self.close_position(symbol, reason="close_all")
            results.append(f"{symbol}: {msg}")
        return results

    def get_positions_status(self):
        result = []
        for symbol, pos in self.state['open_positions'].items():
            try:
                current = get_ticker(self.exchange, symbol)
                pnl_pct = self._calc_pnl_pct(pos, current)
                result.append({
                    'symbol': symbol,
                    'side': pos['side'],
                    'entry': pos['entry'],
                    'current': current,
                    'pnl_pct': pnl_pct,
                    'stop': pos['stop'],
                    'take': pos['take'],
                    'usd_size': pos['usd_size'],
                    'leverage': pos.get('leverage', config.LEVERAGE),
                    'adds_count': len(pos.get('adds', [])),
                    'has_hedge': pos.get('hedge') is not None,
                })
            except Exception:
                pass
        return result

    def add_to_position(self, symbol):
        if symbol not in self.state['open_positions']:
            return False, "позиции нет"

        pos = self.state['open_positions'][symbol]

        try:
            current = get_ticker(self.exchange, symbol)
            pnl_pct = self._calc_pnl_pct(pos, current)
        except Exception as e:
            return False, f"цена: {e}"

        if pnl_pct < getattr(config, 'PYRAMID_START_PCT', 2.0):
            return False, f"мало профита ({pnl_pct:+.2f}%)"

        adds = pos.get('adds', [])
        if len(adds) >= getattr(config, 'PYRAMID_MAX_ADD', 2):
            return False, "лимит добавлений"

        add_size = pos.get('usd_size', config.MAX_POSITION_USD)

        ok, msg, new_pos = self.open_position(
            symbol, pos['side'],
            size_usd=add_size,
            stop_pct=pos.get('stop_pct'),
            take_pct=pos.get('take_pct'),
            allow_duplicate=True,
        )

        if not ok:
            return False, msg

        adds.append({
            'entry': new_pos['entry'],
            'amount': new_pos['amount'],
            'ts': new_pos['open_ts'],
        })
        pos['adds'] = adds

        total_amount = pos['amount'] + new_pos['amount']
        avg_entry = (
            pos['entry'] * pos['amount'] + new_pos['entry'] * new_pos['amount']
        ) / total_amount
        pos['entry'] = avg_entry
        pos['amount'] = total_amount

        self.state['open_positions'][symbol] = pos
        self._save_state()

        return True, f"Пирамида +${add_size:.2f} @ {new_pos['entry']:.6f}"

    def hedge_position(self, symbol):
        if symbol not in self.state['open_positions']:
            return False, "позиции нет"

        if self.position_mode != 'hedge':
            return False, "режим не HEDGE"

        pos = self.state['open_positions'][symbol]
        if pos.get('hedge'):
            return False, "уже захеджировано"

        try:
            current = get_ticker(self.exchange, symbol)
            pnl_pct = self._calc_pnl_pct(pos, current)
        except Exception as e:
            return False, f"цена: {e}"

        trigger = getattr(config, 'HEDGE_TRIGGER_PCT', -2.5)
        if pnl_pct > trigger:
            return False, f"убыток мал ({pnl_pct:+.2f}%)"

        hedge_side = 'SHORT' if pos['side'] == 'LONG' else 'LONG'
        ratio = getattr(config, 'HEDGE_SIZE_RATIO', 0.5)
        hedge_size = pos['usd_size'] * ratio

        ok, msg, new_pos = self.open_position(
            symbol, hedge_side,
            size_usd=hedge_size,
            stop_pct=pos.get('stop_pct'),
            take_pct=pos.get('take_pct'),
            allow_duplicate=True,
        )

        if not ok:
            return False, msg

        pos['hedge'] = {
            'side': hedge_side,
            'entry': new_pos['entry'],
            'amount': new_pos['amount'],
            'ts': new_pos['open_ts'],
        }
        self.state['open_positions'][symbol] = pos
        self._save_state()

        return True, f"Хедж {hedge_side} ${hedge_size:.2f}"


if __name__ == '__main__':
    t = Trader()
    print(f"Режим: {t.position_mode}")
    print(f"Позиций: {len(t.state['open_positions'])}")
    for sym, pos in t.state['open_positions'].items():
        print(f"  {sym}: {pos['side']} @ {pos['entry']}")