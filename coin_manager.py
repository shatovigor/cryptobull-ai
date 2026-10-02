"""
Управление списком монет.
Автоматически добавляет/убирает на основе статистики и бэктеста.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import config


class CoinManager:
    def __init__(self, history_file='trade_history.json'):
        self.history_file = history_file
        self.management_file = 'coin_management.json'
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.management_file):
            try:
                with open(self.management_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            'last_scan': None,          # последнее автосканирование
            'last_analysis': None,      # последний анализ
            'excluded': [],             # монеты, которые убрали (чтобы не добавлять снова)
            'history': [],              # история изменений
        }

    def _save_state(self):
        try:
            with open(self.management_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False, default=str)
        except Exception:
            pass

    def _load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _log_change(self, action, symbol, reason):
        """Логирует изменение списка монет."""
        entry = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'action': action,   # 'add' или 'remove'
            'symbol': symbol,
            'reason': reason,
        }
        self.state['history'].append(entry)
        # Ограничим историю 1000 записей
        if len(self.state['history']) > 1000:
            self.state['history'] = self.state['history'][-1000:]
        self._save_state()
        return entry

    def get_stats_by_symbol(self, days=14):
        """Статистика по каждой монете за N дней."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        trades = self._load_history()
        recent = [t for t in trades if t.get('exit_ts', '') >= cutoff_iso]

        by_symbol = defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0,
            'pnl_pct': 0.0, 'pnl_usd': 0.0,
            'last_trades': [],  # последние N сделок для анализа
        })

        for t in recent:
            s = t.get('symbol')
            if not s:
                continue
            by_symbol[s]['trades'] += 1
            pnl = t.get('pnl_pct', 0)
            by_symbol[s]['pnl_pct'] += pnl
            by_symbol[s]['pnl_usd'] += t.get('pnl_usd', 0)
            if pnl > 0:
                by_symbol[s]['wins'] += 1
            else:
                by_symbol[s]['losses'] += 1
            by_symbol[s]['last_trades'].append(pnl)

        return dict(by_symbol)

    def analyze_and_update(self, current_symbols, min_trades=5, min_pnl_pct=-3.0,
                           consecutive_losses=2):
        """
        Анализирует торговлю и убирает плохие монеты.
        Возвращает (new_symbols, changes) — новый список и изменения.
        """
        stats = self.get_stats_by_symbol(days=14)
        to_remove = []

        for symbol in current_symbols:
            if symbol not in stats:
                continue

            s = stats[symbol]
            trades = s['trades']

            if trades < min_trades:
                continue  # мало данных

            # Проверка 1: общий P&L < min_pnl_pct
            if s['pnl_pct'] < min_pnl_pct:
                to_remove.append((symbol, f"P&L {s['pnl_pct']:+.2f}% < {min_pnl_pct}% за {trades} сделок"))
                continue

            # Проверка 2: N убытков подряд (последние сделки)
            last = s['last_trades'][-consecutive_losses:]
            if len(last) >= consecutive_losses and all(p < 0 for p in last):
                to_remove.append((symbol, f"{consecutive_losses} убытка подряд"))

        # Применяем удаления
        new_symbols = [s for s in current_symbols if s not in [r[0] for r in to_remove]]
        changes = []

        for symbol, reason in to_remove:
            change = self._log_change('remove', symbol, reason)
            changes.append(change)
            # Добавляем в чёрный список на 7 дней
            self.state['excluded'].append({
                'symbol': symbol,
                'until': (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                'reason': reason,
            })

        # Убираем старые исключения
        now_iso = datetime.now(timezone.utc).isoformat()
        self.state['excluded'] = [e for e in self.state['excluded'] if e['until'] > now_iso]

        self.state['last_analysis'] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        return new_symbols, changes

    def is_excluded(self, symbol):
        """Проверяет, в чёрном списке ли монета."""
        now_iso = datetime.now(timezone.utc).isoformat()
        for e in self.state['excluded']:
            if e['symbol'] == symbol and e['until'] > now_iso:
                return True
        return False

    def filter_candidates(self, candidates):
        """Убирает из списка кандидатов те, что в чёрном списке."""
        return [c for c in candidates if not self.is_excluded(c)]

    def get_history(self, limit=50):
        """История изменений списка монет."""
        return list(reversed(self.state['history'][-limit:]))

    def can_scan(self, hours=6):
        """Пора ли запускать автосканирование?"""
        last = self.state.get('last_scan')
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - last_dt
            return delta >= timedelta(hours=hours)
        except Exception:
            return True

    def mark_scan_done(self):
        """Отмечает, что сканирование выполнено."""
        self.state['last_scan'] = datetime.now(timezone.utc).isoformat()
        self._save_state()

    def can_analyze(self, hours=6):
        """Пора ли анализировать?"""
        last = self.state.get('last_analysis')
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - last_dt
            return delta >= timedelta(hours=hours)
        except Exception:
            return True


if __name__ == '__main__':
    cm = CoinManager()
    print(f"Исключённых монет: {len(cm.state['excluded'])}")
    print(f"История изменений: {len(cm.state['history'])}")
    print(f"Можно сканировать: {cm.can_scan()}")
    print(f"Можно анализировать: {cm.can_analyze()}")