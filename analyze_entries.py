"""
analyze_entries.py — Анализ накопленных сигналов и сделок.

Группирует по: типу сигнала, числу касаний, ATR при входе, тренду,
расстоянию до уровня, дню недели, часу дня.

Показывает: winrate, P&L, PF, средний P&L, лучшие/худшие группы.

Использование:
    python analyze_entries.py
    python analyze_entries.py --min-trades 5
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone


SIGNALS_FILE = "signals_log.json"
HISTORY_FILE = "trade_history.json"


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _fmt_pct(v):
    return f"{v:+.2f}%"


def _group_stats(items, key_fn, min_trades=1):
    """
    Группирует items по key_fn(item), считает статистику.
    Возвращает список dict с полями: name, total, wins, winrate, pnl_pct, pnl_usd, pf
    """
    groups = defaultdict(list)
    for it in items:
        try:
            key = key_fn(it)
        except Exception:
            continue
        if key is None:
            continue
        groups[key].append(it)

    result = []
    for name, group in groups.items():
        if len(group) < min_trades:
            continue
        total = len(group)
        wins = sum(1 for t in group if (t.get("pnl_pct") or 0) > 0)
        pnl_pct = sum(t.get("pnl_pct") or 0 for t in group)
        pnl_usd = sum(t.get("pnl_usd") or 0 for t in group)

        profits = sum((t.get("pnl_usd") or 0) for t in group if (t.get("pnl_usd") or 0) > 0)
        losses = abs(sum((t.get("pnl_usd") or 0) for t in group if (t.get("pnl_usd") or 0) < 0))
        pf = profits / losses if losses > 0 else (99.99 if profits > 0 else 0)

        result.append({
            "name": name,
            "total": total,
            "wins": wins,
            "winrate": wins / total * 100 if total else 0,
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "avg_pct": pnl_pct / total if total else 0,
            "pf": pf,
        })

    # Сортируем по PF (лучшие сверху)
    result.sort(key=lambda x: (-x["pf"], -x["pnl_pct"]))
    return result


def _print_table(title, groups, top_n=10, min_trades=3):
    if not groups:
        print(f"\n═══ {title} ═══")
        print("  Нет данных")
        return

    print(f"\n═══ {title} ═══")
    print(f"  {'Группа':<28} {'Сделок':>7} {'Winrate':>9} {'P&L':>10} {'Сред':>8} {'PF':>6}")
    print("  " + "─" * 72)
    for g in groups[:top_n]:
        if g["total"] < min_trades:
            continue
        print(f"  {str(g['name'])[:26]:<28} "
              f"{g['total']:>7} "
              f"{g['winrate']:>8.1f}% "
              f"{_fmt_pct(g['pnl_pct']):>10} "
              f"{_fmt_pct(g['avg_pct']):>8} "
              f"{g['pf']:>6.2f}")


def _bucket_touches(t):
    """Группирует касания в бакеты: 4, 5-6, 7-10, 11+."""
    n = t.get("touches") or 0
    if n <= 4:
        return "x4"
    elif n <= 6:
        return "x5-6"
    elif n <= 10:
        return "x7-10"
    else:
        return "x11+"


def _bucket_atr(t):
    """Группирует ATR в бакеты: <6, 6-8, 8-10, 10-12, 12+."""
    a = t.get("atr_pct") or 0
    if a <= 0:
        return None
    if a < 6:
        return "ATR <6%"
    elif a < 8:
        return "ATR 6-8%"
    elif a < 10:
        return "ATR 8-10%"
    elif a < 12:
        return "ATR 10-12%"
    else:
        return "ATR 12%+"


def _bucket_distance(t):
    """Группирует расстояние до уровня."""
    d = t.get("distance_to_level_pct")
    if d is None:
        return None
    if d < 0.2:
        return "dist <0.2%"
    elif d < 0.5:
        return "dist 0.2-0.5%"
    elif d < 0.8:
        return "dist 0.5-0.8%"
    else:
        return "dist 0.8%+"


def _hour_of_day(t):
    try:
        ts = t.get("ts") or t.get("entry_ts")
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.hour
    except Exception:
        return None


def _day_of_week(t):
    try:
        ts = t.get("ts") or t.get("entry_ts")
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][dt.weekday()]
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-trades", type=int, default=2,
                        help="Минимум сделок в группе для показа")
    parser.add_argument("--source", choices=["signals", "history", "both"],
                        default="both")
    args = parser.parse_args()

    min_t = args.min_trades

    print("=" * 78)
    print("📊 АНАЛИЗ ВХОДОВ В СДЕЛКИ")
    print("=" * 78)

    # Загружаем данные
    signals = _load(SIGNALS_FILE) if args.source in ("signals", "both") else []
    history = _load(HISTORY_FILE) if args.source in ("history", "both") else []

    # Объединяем: signals (только закрытые) + history
    merged = []

    # Из history берём как есть
    for h in history:
        merged.append({
            "ts": h.get("exit_ts") or h.get("open_ts"),
            "entry_ts": h.get("open_ts"),
            "symbol": h.get("symbol"),
            "side": h.get("side"),
            "signal_type": h.get("signal_type", "unknown"),
            "touches": h.get("touches"),
            "atr_pct": h.get("atr_pct"),
            "trend": h.get("trend"),
            "distance_to_level_pct": h.get("distance_to_level_pct"),
            "pnl_pct": h.get("pnl_pct"),
            "pnl_usd": h.get("pnl_usd"),
        })

    # Из signals берём только закрытые (у которых есть result)
    for s in signals:
        if not s.get("result"):
            continue
        merged.append({
            "ts": s.get("ts"),
            "entry_ts": s.get("ts"),
            "symbol": s.get("symbol"),
            "side": s.get("side"),
            "signal_type": s.get("signal_type"),
            "touches": s.get("touches"),
            "atr_pct": s.get("atr_pct"),
            "trend": s.get("trend"),
            "distance_to_level_pct": s.get("distance_to_level_pct"),
            "pnl_pct": s.get("pnl_pct"),
            "pnl_usd": s.get("pnl_usd"),
        })

    # Дубликаты убираем по (symbol, entry_ts)
    seen = set()
    unique = []
    for t in merged:
        key = (t["symbol"], t["entry_ts"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)

    merged = unique

    if not merged:
        print("\n⚠ Нет данных для анализа.")
        print("  Сделки появятся после первых закрытых сделок бота.")
        print("  Запусти бота и подожди несколько дней.")
        return

    print(f"\n📥 Сделок для анализа: {len(merged)}")

    # ===== Группировки =====
    _print_table("ПО ТИПУ СИГНАЛА",
                 _group_stats(merged, lambda t: t.get("signal_type"), min_t),
                 min_trades=min_t)

    _print_table("ПО ЧИСЛУ КАСАНИЙ",
                 _group_stats(merged, _bucket_touches, min_t),
                 min_trades=min_t)

    _print_table("ПО ATR ПРИ ВХОДЕ",
                 _group_stats(merged, _bucket_atr, min_t),
                 min_trades=min_t)

    _print_table("ПО ТРЕНДУ",
                 _group_stats(merged, lambda t: t.get("trend"), min_t),
                 min_trades=min_t)

    _print_table("ПО РАССТОЯНИЮ ДО УРОВНЯ",
                 _group_stats(merged, _bucket_distance, min_t),
                 min_trades=min_t)

    _print_table("ПО ЧАСУ ДНЯ",
                 _group_stats(merged, _hour_of_day, min_t),
                 min_trades=min_t)

    _print_table("ПО ДНЮ НЕДЕЛИ",
                 _group_stats(merged, _day_of_week, min_t),
                 min_trades=min_t)

    _print_table("ПО НАПРАВЛЕНИЮ",
                 _group_stats(merged, lambda t: t.get("side"), min_t),
                 min_trades=min_t)

    # ===== Итоги =====
    print("\n" + "=" * 78)
    print("📌 ЧТО ДЕЛАТЬ С ЭТИМИ ДАННЫМИ")
    print("=" * 78)
    print("  1. Группы с PF > 2 — оставить и усилить")
    print("  2. Группы с PF < 1 — отфильтровать или исключить")
    print("  3. Группы с малым числом сделок — копить данные дальше")
    print()
    print("  💡 Для автосоветов запусти: python advisor.py")


if __name__ == "__main__":
    main()