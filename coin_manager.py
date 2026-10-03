"""
Управление списком монет.
Автоматически добавляет/убирает на основе статистики и бэктеста.

ИСПРАВЛЕНИЯ:
  - _load_history и _load_state защищены от невалидного JSON
  - analyze_and_update: защита от дублей в excluded (не добавляет одну монету дважды)
  - Корректная обработка "последних N сделок" для consecutive_losses
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
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {
            'last_scan': None,
            'last_analysis': None,
            'excluded': [],
            'history': [],
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
                    data = json.load(f)
                return data if isinstance(data, list) else []
            except Exception:
                pass
        return []

    def _log_change(self, action, symbol, reason):
        """Логирует изменение списка монет."""
        entry = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'action': action,
            'symbol': symbol,
            'reason': reason,
        }
        self.state['history'].append(entry)
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
            'last_trades': [],
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
                continue

            if s['pnl_pct'] < min_pnl_pct:
                to_remove.append((symbol, f"P&L {s['pnl_pct']:+.2f}% < {min_pnl_pct}% за {trades} сделок"))
                continue

            last = s['last_trades'][-consecutive_losses:]
            if len(last) >= consecutive_losses and all(p < 0 for p in last):
                to_remove.append((symbol, f"{consecutive_losses} убытка подряд"))

        new_symbols = [s for s in current_symbols if s not in [r[0] for r in to_remove]]
        changes = []

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        for symbol, reason in to_remove:
            change = self._log_change('remove', symbol, reason)
            changes.append(change)

            # Проверяем, нет ли уже активного исключения для этой монеты
            already_excluded = any(
                e.get('symbol') == symbol and e.get('until', '') > now_iso
                for e in self.state['excluded']
            )
            if not already_excluded:
                self.state['excluded'].append({
                    'symbol': symbol,
                    'until': (now + timedelta(days=7)).isoformat(),
                    'reason': reason,
                })

        # Убираем старые исключения
        self.state['excluded'] = [e for e in self.state['excluded'] if e.get('until', '') > now_iso]

        self.state['last_analysis'] = now_iso
        self._save_state()

        return new_symbols, changes

    def is_excluded(self, symbol):
        """Проверяет, в чёрном списке ли монета."""
        now_iso = datetime.now(timezone.utc).isoformat()
        for e in self.state['excluded']:
            if e.get('symbol') == symbol and e.get('until', '') > now_iso:
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