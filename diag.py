# diag.py
import json, os
import config

print("=" * 60)
print("ДИАГНОСТИКА")
print("=" * 60)

print("\n1. config.AUTO_SYMBOLS:")
for s in config.AUTO_SYMBOLS:
    print(f"   {s}")

print(f"\n2. bot_state.json существует: {os.path.exists('bot_state.json')}")
if os.path.exists('bot_state.json'):
    with open('bot_state.json') as f:
        st = json.load(f)
    print(f"   Открытых позиций в state: {len(st.get('open_positions', {}))}")
    for sym, p in st.get('open_positions', {}).items():
        print(f"   • {sym}: {p.get('side')} entry={p.get('entry')}")

print(f"\n3. .env существует: {os.path.exists('.env')}")
from dotenv import load_dotenv
load_dotenv(override=True)
key = os.getenv('BYBIT_API_KEY', '')
print(f"   API key: {key[:6]}...{key[-4:] if key else 'НЕТ'}")

print("\n4. Реальные позиции на Bybit:")
try:
    from bybit_client import make_exchange
    ex = make_exchange()
    positions = ex.fetch_positions()
    opened = [p for p in positions if abs(float(p.get('contracts', 0) or 0)) > 0]
    if not opened:
        print("   Позиций нет")
    for p in opened:
        print(f"   • {p.get('symbol')}: {p.get('side')} "
              f"entry={p.get('entryPrice')} size={p.get('contracts')} "
              f"pnl={p.get('unrealizedPnl')} lev={p.get('leverage')}")
except Exception as e:
    print(f"   ❌ Ошибка: {e}")

print("\n" + "=" * 60)