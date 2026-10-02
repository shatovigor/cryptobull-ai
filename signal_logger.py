"""
signal_logger.py — Логирование всех сигналов (сработавших и нет).

Каждый сигнал сохраняется в signals_log.json:
  - ts, symbol, side, signal_type
  - level_price, touches, atr_pct, trend
  - distance_to_level_pct
  - opened (True/False), reason (если не открыт)
  - результат сделки (заполняется post-factum)

Использование:
    from signal_logger import log_signal, log_trade_result, load_signals
    log_signal({...})
"""
import os
import json
from datetime import datetime, timezone
from threading import Lock


SIGNALS_FILE = "signals_log.json"
LOCK = Lock()
MAX_SIGNALS = 5000


def _load_raw():
    if not os.path.exists(SIGNALS_FILE):
        return []
    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_raw(data):
    try:
        with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    except Exception:
        pass


def log_signal(signal: dict):
    """
    Пишет сигнал в signals_log.json.

    Обязательные поля:
        symbol, side, signal_type, price
    Опциональные:
        level_price, touches, atr_pct, trend, distance_to_level_pct,
        opened (bool), reason (str), position_id (str)
    """
    with LOCK:
        data = _load_raw()

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": signal.get("symbol"),
            "side": signal.get("side"),
            "signal_type": signal.get("signal_type"),  # 'PINBAR' / 'BOUNCE'
            "price": signal.get("price"),
            "level_price": signal.get("level_price"),
            "touches": signal.get("touches"),
            "atr_pct": signal.get("atr_pct"),
            "trend": signal.get("trend"),
            "distance_to_level_pct": signal.get("distance_to_level_pct"),
            "opened": bool(signal.get("opened", False)),
            "reason": signal.get("reason", ""),
            "position_id": signal.get("position_id", ""),
            "result": None,
            "pnl_pct": None,
            "pnl_usd": None,
            "duration_h": None,
        }

        data.append(entry)

        if len(data) > MAX_SIGNALS:
            data = data[-MAX_SIGNALS:]

        _save_raw(data)
        return entry


def log_trade_result(symbol, entry_ts, exit_ts, pnl_pct, pnl_usd,
                     duration_h, result="TAKE", reason="closed"):
    """
    Обновляет результат сделки в последнем подходящем сигнале.
    Ищет сигнал по symbol и entry_ts (с допуском ±5 мин).
    """
    from datetime import datetime as _dt

    with LOCK:
        data = _load_raw()
        try:
            target = _dt.fromisoformat(entry_ts.replace("Z", "+00:00"))
        except Exception:
            return False

        updated = False
        # Ищем в обратном порядке — от свежих к старым
        for i in range(len(data) - 1, -1, -1):
            sig = data[i]
            if sig.get("symbol") != symbol:
                continue
            if not sig.get("opened"):
                continue
            try:
                sig_ts = _dt.fromisoformat(sig["ts"].replace("Z", "+00:00"))
            except Exception:
                continue
            diff_sec = abs((target - sig_ts).total_seconds())
            if diff_sec > 300:
                continue

            sig["result"] = result
            sig["pnl_pct"] = pnl_pct
            sig["pnl_usd"] = pnl_usd
            sig["duration_h"] = duration_h
            sig["reason"] = reason
            updated = True
            break

        if updated:
            _save_raw(data)
        return updated


def load_signals():
    """Возвращает список сигналов."""
    return _load_raw()


def clear_signals():
    """Очищает лог."""
    _save_raw([])


def stats():
    """Быстрая статистика: сколько сигналов, сколько открыто, сколько закрыто."""
    data = _load_raw()
    total = len(data)
    opened = sum(1 for s in data if s.get("opened"))
    closed = sum(1 for s in data if s.get("result"))
    return {
        "total": total,
        "opened": opened,
        "closed": closed,
        "not_opened": total - opened,
    }


if __name__ == "__main__":
    s = stats()
    print(f"Всего сигналов: {s['total']}")
    print(f"Открыто: {s['opened']}")
    print(f"Закрыто: {s['closed']}")
    print(f"Не открыто (фильтры): {s['not_opened']}")