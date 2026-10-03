"""Ручной импорт позиций с Bybit в bot_state.json."""
import json
import os

# 1. Что на бирже
from bybit_client import make_exchange
ex = make_exchange()
positions = ex.fetch_positions()
real_open = [
    p for p in positions
    if abs(float(p.get('contracts', 0) or 0)) > 0
]

print("=" * 60)
print("На бирже открыто:", len(real_open))
for p in real_open:
    print(f"  {p.get('symbol')}: "
          f"side={p.get('side')} "
          f"entry={p.get('entryPrice')} "
          f"size={p.get('contracts')} "
          f"lev={p.get('leverage')} "
          f"pnl={p.get('unrealizedPnl')}")
print()

# 2. Текущий state
if os.path.exists('bot_state.json'):
    with open('bot_state.json', encoding='utf-8') as f:
        state = json.load(f)
else:
    state = {'open_positions': {}, 'daily_stats': {}}

print("В state до импорта:", len(state.get('open_positions', {})))
print()

# 3. Импорт
added = []
for p in real_open:
    sym = p.get('symbol')
    if not sym:
        continue
    if sym in state['open_positions']:
        continue

    entry = float(p.get('entryPrice') or 0)
    size = abs(float(p.get('contracts') or 0))
    side_raw = (p.get('side') or '').lower()
    side = 'LONG' if side_raw in ('buy', 'long') else 'SHORT'
    leverage = float(p.get('leverage') or 1)

    info = p.get('info', {}) or {}
    stop = float(info.get('stopLoss') or 0) or entry * (1 - 0.025 if side == 'LONG' else 1 + 0.025)
    take = float(info.get('takeProfit') or 0) or entry * (1 + 0.05 if side == 'LONG' else 1 - 0.05)

    state['open_positions'][sym] = {
        'symbol': sym,
        'side': side,
        'entry': entry,
        'amount': size,
        'usd_size': entry * size,
        'stop': stop,
        'take': take,
        'open_ts': '',
        'order_id': '',
        'stop_pct': abs(entry - stop) / entry * 100 if entry else 2.5,
        'take_pct': abs(take - entry) / entry * 100 if entry else 5.0,
        'stop_set': True,
        'position_idx': int(info.get('positionIdx', 0) or 0),
        'position_mode': 'one_way',
        'leverage': leverage,
        'adds': [],
        'hedge': None,
        'signal_type': 'imported',
        'strategy': 'imported',
    }
    added.append(sym)

if added:
    with open('bot_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    print(f"Импортировано: {added}")
else:
    print("Импортировать нечего")

print()
print("В state после импорта:", len(state.get('open_positions', {})))
for sym, p in state['open_positions'].items():
    print(f"  {sym}: {p['side']} entry={p['entry']} size={p['amount']}")