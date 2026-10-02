"""
advisor.py — Автосоветник по улучшению стратегии.

Анализирует signals_log.json + trade_history.json и выдаёт
конкретные рекомендации: какие параметры изменить в config.py.

Работает:
  - как CLI: python advisor.py
  - как модуль: from advisor import get_advice
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone


SIGNALS_FILE = "signals_log.json"
HISTORY_FILE = "trade_history.json"
MIN_TRADES_FOR_ADVICE = 10  # Минимум сделок для уверенного совета
MIN_TRADES_PER_GROUP = 3    # Минимум в группе


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _collect_trades():
    """Объединяет signals + history в единый список сделок."""
    signals = _load(SIGNALS_FILE)
    history = _load(HISTORY_FILE)

    merged = []
    for h in history:
        merged.append({
            "ts": h.get("open_ts"),
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

    for s in signals:
        if not s.get("result"):
            continue
        merged.append({
            "ts": s.get("ts"),
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

    # Уникальные по (symbol, ts)
    seen = set()
    unique = []
    for t in merged:
        key = (t["symbol"], t["ts"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)

    return unique


def _group(items, key_fn):
    groups = defaultdict(list)
    for it in items:
        try:
            k = key_fn(it)
            if k is not None:
                groups[k].append(it)
        except Exception:
            continue
    return groups


def _stats(group):
    total = len(group)
    if total == 0:
        return None
    wins = sum(1 for t in group if (t.get("pnl_pct") or 0) > 0)
    pnl_pct = sum(t.get("pnl_pct") or 0 for t in group)
    pnl_usd = sum(t.get("pnl_usd") or 0 for t in group)
    profits = sum((t.get("pnl_usd") or 0) for t in group if (t.get("pnl_usd") or 0) > 0)
    losses = abs(sum((t.get("pnl_usd") or 0) for t in group if (t.get("pnl_usd") or 0) < 0))
    pf = profits / losses if losses > 0 else (99.99 if profits > 0 else 0)
    return {
        "total": total,
        "wins": wins,
        "winrate": wins / total * 100,
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "avg_pct": pnl_pct / total,
        "pf": pf,
    }


def _touches_bucket(t):
    n = t.get("touches") or 0
    if n <= 4:
        return "x4"
    elif n <= 6:
        return "x5-6"
    elif n <= 10:
        return "x7-10"
    else:
        return "x11+"


def _atr_bucket(t):
    a = t.get("atr_pct") or 0
    if a <= 0:
        return None
    if a < 6:
        return "atr_lt6"
    elif a < 8:
        return "atr_6_8"
    elif a < 10:
        return "atr_8_10"
    elif a < 12:
        return "atr_10_12"
    else:
        return "atr_gt12"


def get_advice():
    """
    Возвращает список рекомендаций:
    [
        {
            'priority': 'high' | 'medium' | 'info',
            'title': str,
            'message': str,
            'action': str | None (например "MIN_TOUCHES=4"),
        }, ...
    ]
    """
    advice = []
    trades = _collect_trades()

    if len(trades) < MIN_TRADES_FOR_ADVICE:
        advice.append({
            "priority": "info",
            "title": "Мало данных",
            "message": (
                f"Накоплено {len(trades)} сделок, нужно минимум "
                f"{MIN_TRADES_FOR_ADVICE} для уверенных советов."
            ),
            "action": "Продолжай торговлю, советник обновит рекомендации.",
        })
        return advice

    # ===== Анализ по типам сигналов =====
    by_signal = _group(trades, lambda t: t.get("signal_type"))
    stats_signal = {k: _stats(v) for k, v in by_signal.items() if len(v) >= MIN_TRADES_PER_GROUP}

    # Находим лучший и худший тип
    if len(stats_signal) >= 2:
        sorted_signal = sorted(stats_signal.items(), key=lambda x: -x[1]["pf"])
        best = sorted_signal[0]
        worst = sorted_signal[-1]

        if worst[1]["pf"] < 1.0 and best[1]["pf"] >= 1.5:
            advice.append({
                "priority": "high",
                "title": f"Отключить убыточный сигнал: {worst[0]}",
                "message": (
                    f"Сигнал «{worst[0]}» даёт PF={worst[1]['pf']:.2f} "
                    f"({worst[1]['total']} сделок, winrate {worst[1]['winrate']:.0f}%). "
                    f"Сигнал «{best[0]}» даёт PF={best[1]['pf']:.2f}."
                ),
                "action": f"USE_BOUNCE_SIGNAL = False" if worst[0] == "BOUNCE" else "PINBAR_DISABLED",
            })

    # ===== Анализ по касаниям =====
    by_touch = _group(trades, _touches_bucket)
    stats_touch = {k: _stats(v) for k, v in by_touch.items() if len(v) >= MIN_TRADES_PER_GROUP}

    if "x11+" in stats_touch and stats_touch["x11+"]["pf"] < 1.0:
        s = stats_touch["x11+"]
        advice.append({
            "priority": "high",
            "title": "Отсечь уровни с 11+ касаниями",
            "message": (
                f"Уровни с 11+ касаниями дают PF={s['pf']:.2f} и "
                f"{s['winrate']:.0f}% winrate за {s['total']} сделок. "
                f"Такие «старые» уровни, вероятно, уже пробиты рынком."
            ),
            "action": "Добавить MAX_TOUCHES = 10 в config.py + фильтр в auto_trader._check_signal",
        })

    if "x4" in stats_touch and stats_touch["x4"]["pf"] >= 2.0:
        s = stats_touch["x4"]
        advice.append({
            "priority": "medium",
            "title": "Уровни с x4 работают лучше всех",
            "message": (
                f"x4-уровни: PF={s['pf']:.2f}, winrate {s['winrate']:.0f}%, "
                f"{s['total']} сделок. Возможно, свежие уровни надёжнее."
            ),
            "action": "Оставить MIN_TOUCHES = 4, не увеличивать",
        })

    # ===== Анализ по ATR =====
    by_atr = _group(trades, _atr_bucket)
    stats_atr = {k: _stats(v) for k, v in by_atr.items() if len(v) >= MIN_TRADES_PER_GROUP}

    if "atr_gt12" in stats_atr and stats_atr["atr_gt12"]["pf"] < 1.0:
        s = stats_atr["atr_gt12"]
        advice.append({
            "priority": "high",
            "title": "Убрать монеты с ATR > 12%",
            "message": (
                f"ATR>12%: PF={s['pf']:.2f}, winrate {s['winrate']:.0f}%. "
                f"Слишком высокая волатильность — стопы выбивает шумом."
            ),
            "action": "SCANNER_MAX_ATR_PCT = 12.0 в config.py",
        })

    if "atr_6_8" in stats_atr and stats_atr["atr_6_8"]["pf"] >= 2.0:
        s = stats_atr["atr_6_8"]
        advice.append({
            "priority": "medium",
            "title": "ATR 6-8% — сладкая зона",
            "message": (
                f"ATR 6-8%: PF={s['pf']:.2f}, winrate {s['winrate']:.0f}%, "
                f"{s['total']} сделок. Здесь лучший баланс движения и предсказуемости."
            ),
            "action": "Оставить SCANNER_MIN_ATR_PCT = 6.0",
        })

    # ===== Топ-3 монеты по PF =====
    by_symbol = _group(trades, lambda t: t.get("symbol"))
    stats_symbol = {k: _stats(v) for k, v in by_symbol.items() if len(v) >= MIN_TRADES_PER_GROUP}

    if stats_symbol:
        sorted_symbols = sorted(stats_symbol.items(), key=lambda x: -x[1]["pf"])
        best_3 = sorted_symbols[:3]
        worst_3 = sorted_symbols[-3:] if len(sorted_symbols) >= 4 else []

        if worst_3 and worst_3[-1][1]["pf"] < 1.0:
            worst_sym = worst_3[-1]
            advice.append({
                "priority": "medium",
                "title": f"Плохая монета: {worst_sym[0]}",
                "message": (
                    f"{worst_sym[0]}: PF={worst_sym[1]['pf']:.2f}, "
                    f"winrate {worst_sym[1]['winrate']:.0f}%, "
                    f"{worst_sym[1]['total']} сделок."
                ),
                "action": f"Добавить в SCANNER_BLACKLIST",
            })

        if best_3 and best_3[0][1]["pf"] >= 2.0:
            best_sym = best_3[0]
            advice.append({
                "priority": "info",
                "title": f"Лучшая монета: {best_sym[0]}",
                "message": (
                    f"{best_sym[0]}: PF={best_sym[1]['pf']:.2f}, "
                    f"winrate {best_sym[1]['winrate']:.0f}%, "
                    f"{best_sym[1]['total']} сделок. Стоит оставить."
                ),
                "action": None,
            })

    # ===== Общий PF =====
    overall = _stats(trades)
    if overall:
        if overall["pf"] < 1.0:
            advice.append({
                "priority": "high",
                "title": "Стратегия убыточна!",
                "message": (
                    f"Общий PF={overall['pf']:.2f}, P&L={overall['pnl_pct']:+.2f}%, "
                    f"winrate {overall['winrate']:.0f}% за {overall['total']} сделок. "
                    f"Нужны серьёзные изменения."
                ),
                "action": "Проверь: стопы, тейки, фильтры, тип сигналов. Запусти A/B-тест.",
            })
        elif overall["pf"] >= 2.0:
            advice.append({
                "priority": "info",
                "title": "Стратегия работает хорошо",
                "message": (
                    f"Общий PF={overall['pf']:.2f}, P&L={overall['pnl_pct']:+.2f}%, "
                    f"winrate {overall['winrate']:.0f}% за {overall['total']} сделок. "
                    f"Можно постепенно увеличивать размер позиций."
                ),
                "action": None,
            })

    # ===== Часы / дни =====
    def _hour(t):
        try:
            dt = datetime.fromisoformat(str(t.get("ts")).replace("Z", "+00:00"))
            return dt.hour
        except Exception:
            return None

    by_hour = _group(trades, _hour)
    stats_hour = {k: _stats(v) for k, v in by_hour.items() if len(v) >= MIN_TRADES_PER_GROUP}

    if stats_hour:
        sorted_hours = sorted(stats_hour.items(), key=lambda x: -x[1]["pf"])
        if sorted_hours[0][1]["pf"] >= 2.5:
            best_hour = sorted_hours[0]
            advice.append({
                "priority": "info",
                "title": f"Лучший час: {best_hour[0]}:00 UTC",
                "message": (
                    f"В {best_hour[0]}:00 UTC PF={best_hour[1]['pf']:.2f}, "
                    f"{best_hour[1]['total']} сделок. "
                    f"Можно рассмотреть фильтр по времени."
                ),
                "action": None,
            })

    return advice


def format_advice(advice):
    """Форматирует рекомендации в текст для вывода."""
    if not advice:
        return "Советов пока нет — нужно больше данных."

    lines = []
    priority_emoji = {"high": "🚨", "medium": "⚠️", "info": "💡"}

    for a in advice:
        emoji = priority_emoji.get(a["priority"], "•")
        lines.append(f"{emoji} {a['title']}")
        lines.append(f"   {a['message']}")
        if a.get("action"):
            lines.append(f"   → {a['action']}")
        lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 70)
    print("🧠 АВТОСОВЕТНИК")
    print("=" * 70)
    print()

    advice = get_advice()
    print(format_advice(advice))

    print("=" * 70)
    print("💡 Совет обновляется по мере накопления сделок.")
    print("   Запускай после каждых 10-20 новых сделок.")


if __name__ == "__main__":
    main()