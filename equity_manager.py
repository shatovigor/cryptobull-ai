"""
Менеджер equity — кривая прибыли, статистика.

ИСПРАВЛЕНИЯ:
  - Защита от start == 0 при расчёте total_growth_pct
  - Защита от пустых equities в get_stats
"""
import json
import os
from datetime import datetime, timezone, timedelta


class EquityManager:
    def __init__(self, equity_file='equity_history.json'):
        self.equity_file = equity_file
        self.points = self._load()

    def _load(self):
        if os.path.exists(self.equity_file):
            try:
                with open(self.equity_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data if isinstance(data, list) else []
            except Exception:
                pass
        return []

    def _save(self):
        try:
            with open(self.equity_file, 'w', encoding='utf-8') as f:
                json.dump(self.points, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def add_point(self, balance, positions_pnl=0.0):
        equity = balance + positions_pnl
        point = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'equity': round(equity, 2),
            'balance': round(balance, 2),
            'positions_pnl': round(positions_pnl, 2),
        }
        if self.points:
            try:
                last_ts = datetime.fromisoformat(self.points[-1]['ts'])
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                delta = (datetime.now(timezone.utc) - last_ts).total_seconds()
                if delta < 300:
                    self.points[-1] = point
                    self._save()
                    return
            except Exception:
                pass

        self.points.append(point)
        if len(self.points) > 5000:
            self.points = self.points[-5000:]
        self._save()

    def get_points(self, days=30):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = []
        for p in self.points:
            try:
                ts = datetime.fromisoformat(p['ts'])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    result.append(p)
            except Exception:
                continue
        return result

    def get_stats(self):
        """ИСПРАВЛЕНИЕ: защита от пустого списка и start == 0."""
        if not self.points:
            return {
                'start': 0, 'current': 0, 'peak': 0,
                'max_dd': 0, 'total_growth': 0, 'total_growth_pct': 0,
            }

        equities = [p['equity'] for p in self.points]
        if not equities:
            return {
                'start': 0, 'current': 0, 'peak': 0,
                'max_dd': 0, 'total_growth': 0, 'total_growth_pct': 0,
            }

        start = equities[0]
        current = equities[-1]
        peak = max(equities)

        dd = 0
        max_dd = 0
        peak_running = equities[0]
        for e in equities:
            if e > peak_running:
                peak_running = e
            dd = peak_running - e
            max_dd = max(max_dd, dd)

        growth_pct = (current - start) / start * 100 if start > 0 else 0.0

        return {
            'start': start,
            'current': current,
            'peak': peak,
            'max_dd': max_dd,
            'total_growth': current - start,
            'total_growth_pct': growth_pct,
        }

    def get_streaks(self, history_file='trade_history.json'):
        if not os.path.exists(history_file):
            return {'current': 0, 'type': 'нет', 'max_win': 0, 'max_loss': 0}
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                trades = json.load(f)
        except Exception:
            return {'current': 0, 'type': 'нет', 'max_win': 0, 'max_loss': 0}

        if not trades:
            return {'current': 0, 'type': 'нет', 'max_win': 0, 'max_loss': 0}

        current = 0
        current_type = None
        max_win = 0
        max_loss = 0

        for t in trades:
            win = t.get('pnl_usd', 0) > 0
            if current_type is None:
                current_type = win
                current = 1
            elif current_type == win:
                current += 1
            else:
                if current_type:
                    max_win = max(max_win, current)
                else:
                    max_loss = max(max_loss, current)
                current_type = win
                current = 1

        if current_type:
            max_win = max(max_win, current)
        else:
            max_loss = max(max_loss, current)

        return {
            'current': current,
            'type': '✅ побед' if current_type else '❌ убытков',
            'max_win': max_win,
            'max_loss': max_loss,
        }


if __name__ == '__main__':
    em = EquityManager()
    print(f"Точек: {len(em.points)}")
    s = em.get_stats()
    print(f"Старт: ${s['start']:.2f}, Сейчас: ${s['current']:.2f}")
    print(f"Рост: {s['total_growth_pct']:+.2f}%")