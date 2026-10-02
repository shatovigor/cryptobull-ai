"""
A/B сравнение конфигураций в бэктесте.
Принимает список configs от GUI.
"""
import config
from backtest_runner import run_backtest


def compare_configurations(symbols, configs, backtest_days=14, progress_callback=None):
    """configs — список словарей вида:
        [{'name': 'MTF only', 'config': {'USE_MULTI_TIMEFRAME': True}}, ...]
    """
    def log(msg):
        if progress_callback:
            progress_callback(msg)

    results = []

    for entry in configs:
        name = entry.get('name', '?')
        override = entry.get('config', {})

        log(f"═══ {name} ═══")
        if override:
            log(f"  Настройки: {', '.join(f'{k}={v}' for k, v in override.items())}")

        try:
            result = run_backtest(
                symbols=symbols,
                backtest_days=backtest_days,
                progress_callback=None,
                override_config=override,
            )
            summary = result.get('summary') or {}

            results.append({
                'name': name,
                'config': override,
                'summary': summary,
                'trades_count': summary.get('total', 0),
                'winrate': summary.get('winrate', 0),
                'pnl': summary.get('pnl', 0),
                'pnl_usd': summary.get('pnl_usd', 0),
                'pf': summary.get('pf', 0),
                'dd': summary.get('dd', 0),
                'avg': summary.get('avg', 0),
                'trades_list': result.get('trades_list', []),
            })
            log(f"  Сделок: {summary.get('total', 0)}, "
                f"P&L: {summary.get('pnl', 0):+.2f}%, "
                f"PF: {summary.get('pf', 0):.2f}")
        except Exception as e:
            log(f"  ❌ Ошибка: {str(e)[:80]}")
            results.append({
                'name': name,
                'config': override,
                'summary': None,
                'error': str(e)[:80],
            })

    return results


def build_entry_ab_configs(base_config=None):
    """
    Строит список конфигураций для A/B-теста ПАРАМЕТРОВ ВХОДА.
    Возвращает список:
      [{'name': 'База', 'config': {}},
       {'name': 'MIN_TOUCHES=3', 'config': {'MIN_TOUCHES': 3}}, ...]
    """
    configs = [{'name': 'База (текущие настройки)', 'config': {}}]

    # ===== Варианты MIN_TOUCHES =====
    for mt in [3, 5, 6, 8]:
        configs.append({
            'name': f'MIN_TOUCHES = {mt}',
            'config': {'MIN_TOUCHES': mt},
        })

    # ===== Варианты NEAR_LEVEL_PCT =====
    for near in [0.3, 0.5, 1.2, 1.5]:
        configs.append({
            'name': f'NEAR = {near}%',
            'config': {'NEAR_LEVEL_PCT': near},
        })

    # ===== Варианты CLUSTER_PCT =====
    for cl in [0.3, 0.4, 1.0, 1.5]:
        configs.append({
            'name': f'CLUSTER = {cl}%',
            'config': {'CLUSTER_PCT': cl},
        })

    # ===== Только PINBAR =====
    configs.append({
        'name': 'Только PINBAR',
        'config': {'USE_BOUNCE_SIGNAL': False},
    })

    # ===== Только BOUNCE =====
    configs.append({
        'name': 'Только BOUNCE',
        'config': {'USE_BOUNCE_SIGNAL': True, 'PINBAR_DISABLED': True},
    })

    # ===== Без тренд-фильтра =====
    configs.append({
        'name': 'Без TREND-фильтра',
        'config': {'USE_TREND_FILTER': False},
    })

    # ===== + MTF =====
    configs.append({
        'name': '+ MTF фильтр',
        'config': {'USE_MULTI_TIMEFRAME': True},
    })

    return configs


# Обратная совместимость со старым API
def compare_functions(symbols=None, backtest_days=10, progress_callback=None):
    if symbols is None:
        symbols = list(config.AUTO_SYMBOLS)

    base_off = {
        'USE_MULTI_TIMEFRAME': False,
        'USE_TRAILING_STOP': False,
        'USE_ADAPTIVE_SIZE': False,
    }
    configs = [
        {'name': 'База', 'config': base_off},
        {'name': '+ MTF', 'config': {**base_off, 'USE_MULTI_TIMEFRAME': True}},
        {'name': '+ Trailing', 'config': {**base_off, 'USE_TRAILING_STOP': True}},
        {'name': '+ Адаптив', 'config': {**base_off, 'USE_ADAPTIVE_SIZE': True}},
        {'name': '+ Всё', 'config': {
            'USE_MULTI_TIMEFRAME': True,
            'USE_TRAILING_STOP': True,
            'USE_ADAPTIVE_SIZE': True,
        }},
    ]
    return compare_configurations(symbols, configs, backtest_days, progress_callback)


if __name__ == '__main__':
    print("A/B СРАВНЕНИЕ ФУНКЦИЙ")
    print("=" * 60)

    def cli_log(msg):
        print(msg)

    results = compare_functions(
        symbols=config.AUTO_SYMBOLS[:5],
        backtest_days=10,
        progress_callback=cli_log,
    )

    print()
    print("=" * 60)
    print("ИТОГИ:")
    print(f"{'Конфигурация':<25} {'Сделок':>8} {'Winrate':>10} {'P&L':>10} {'PF':>6}")
    print("-" * 60)
    for r in results:
        if r.get('error'):
            print(f"{r['name']:<25} ОШИБКА")
        else:
            print(f"{r['name']:<25} "
                  f"{r['trades_count']:>8} "
                  f"{r['winrate']:>9.1f}% "
                  f"{r['pnl']:>+9.2f}% "
                  f"{r['pf']:>6.2f}")