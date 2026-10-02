"""
Менеджер отчётов и календаря.
Дневной отчёт, календарь прибыли, тепловая карта.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict


class ReportManager:
    def __init__(self, history_file='trade_history.json', equity_file='equity_history.json'):
        self.history_file = history_file
        self.equity_file = equity_file
        self.report_file = 'daily_reports.json'
        self.reports = self._load_reports()

    def _load_reports(self):
        if os.path.exists(self.report_file):
            try:
                with open(self.report_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_reports(self):
        try:
            with open(self.report_file, 'w', encoding='utf-8') as f:
                json.dump(self.reports, f, indent=2, ensure_ascii=False, default=str)
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

    def get_daily_report(self, date_str=None):
        """Возвращает отчёт за конкретный день."""
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        trades = self._load_history()
        day_trades = [t for t in trades if t.get('exit_ts', '').startswith(date_str)]

        if not day_trades:
            return {
                'date': date_str,
                'total': 0, 'wins': 0, 'losses': 0,
                'pnl_pct': 0, 'pnl_usd': 0,
                'best_trade': None, 'worst_trade': None,
            }

        wins = [t for t in day_trades if t.get('pnl_usd', 0) > 0]
        losses = [t for t in day_trades if t.get('pnl_usd', 0) <= 0]
        best = max(day_trades, key=lambda t: t.get('pnl_usd', 0))
        worst = min(day_trades, key=lambda t: t.get('pnl_usd', 0))

        return {
            'date': date_str,
            'total': len(day_trades),
            'wins': len(wins),
            'losses': len(losses),
            'winrate': len(wins) / len(day_trades) * 100,
            'pnl_pct': sum(t.get('pnl_pct', 0) for t in day_trades),
            'pnl_usd': sum(t.get('pnl_usd', 0) for t in day_trades),
            'best_trade': {
                'symbol': best.get('symbol'),
                'pnl_usd': best.get('pnl_usd', 0),
                'pnl_pct': best.get('pnl_pct', 0),
            },
            'worst_trade': {
                'symbol': worst.get('symbol'),
                'pnl_usd': worst.get('pnl_usd', 0),
                'pnl_pct': worst.get('pnl_pct', 0),
            },
        }

    def save_daily_report(self):
        """Сохраняет отчёт за сегодня в файл."""
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        report = self.get_daily_report(today)
        self.reports[today] = report
        self._save_reports()
        return report

    def format_report_text(self, report):
        """Красиво форматирует отчёт."""
        if report['total'] == 0:
            return f"📊 ОТЧЁТ ЗА {report['date']}\n\nСделок не было"

        text = f"📊 ОТЧЁТ ЗА {report['date']}\n\n"
        text += f"Сделок: {report['total']}\n"
        text += f"Прибыльных: {report['wins']} ({report['winrate']:.1f}%)\n"
        text += f"Убыточных: {report['losses']}\n"
        text += f"P&L: {report['pnl_pct']:+.2f}% (${report['pnl_usd']:+.2f})\n"

        if report.get('best_trade'):
            bt = report['best_trade']
            text += f"\n🏆 Лучшая: {bt['symbol']} ${bt['pnl_usd']:+.2f} ({bt['pnl_pct']:+.2f}%)"

        if report.get('worst_trade'):
            wt = report['worst_trade']
            text += f"\n❌ Худшая: {wt['symbol']} ${wt['pnl_usd']:+.2f} ({wt['pnl_pct']:+.2f}%)"

        return text

    def get_calendar(self, days=30):
        """Возвращает данные календаря — P&L по дням."""
        trades = self._load_history()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        by_day = defaultdict(lambda: {'trades': 0, 'pnl_pct': 0, 'pnl_usd': 0, 'wins': 0})

        for t in trades:
            try:
                ts = datetime.fromisoformat(str(t.get('exit_ts', '')).replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
                day = ts.strftime('%Y-%m-%d')
                by_day[day]['trades'] += 1
                by_day[day]['pnl_pct'] += t.get('pnl_pct', 0)
                by_day[day]['pnl_usd'] += t.get('pnl_usd', 0)
                if t.get('pnl_usd', 0) > 0:
                    by_day[day]['wins'] += 1
            except Exception:
                continue

        return dict(by_day)

    def get_heatmap(self):
        """Тепловая карта — P&L по монетам."""
        trades = self._load_history()
        by_symbol = defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0,
            'pnl_pct': 0, 'pnl_usd': 0,
        })

        for t in trades:
            sym = t.get('symbol', '?')
            by_symbol[sym]['trades'] += 1
            pnl_usd = t.get('pnl_usd', 0)
            by_symbol[sym]['pnl_usd'] += pnl_usd
            by_symbol[sym]['pnl_pct'] += t.get('pnl_pct', 0)
            if pnl_usd > 0:
                by_symbol[sym]['wins'] += 1
            else:
                by_symbol[sym]['losses'] += 1

        # Сортируем по P&L (убыточные сверху)
        return dict(sorted(by_symbol.items(), key=lambda x: x[1]['pnl_usd']))


if __name__ == '__main__':
    rm = ReportManager()
    report = rm.get_daily_report()
    print(rm.format_report_text(report))
    print()
    print("=== Календарь ===")
    cal = rm.get_calendar(7)
    for day, data in sorted(cal.items()):
        print(f"  {day}: ${data['pnl_usd']:+.2f} ({data['trades']} сделок)")
    print()
    print("=== Тепловая карта ===")
    hm = rm.get_heatmap()
    for sym, data in hm.items():
        print(f"  {sym}: ${data['pnl_usd']:+.2f} ({data['trades']} сделок)")