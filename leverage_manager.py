"""
Автоподбор кредитного плеча.
Основано на волатильности (ATR%) и силе сигнала.
"""


def calc_leverage(atr_pct, signal_strength=1.0, max_leverage=5.0, base_leverage=1.0):
    """
    Определяет оптимальное плечо.

    ИСПРАВЛЕНИЕ: защита от atr_pct=None или <=0.
    """
    if atr_pct is None or atr_pct <= 0:
        return max(1.0, min(base_leverage, max_leverage)), "ATR неизвестен"

    if atr_pct < 5:
        base = 5.0
        reason = f"низкая волатильность (ATR {atr_pct:.1f}%)"
    elif atr_pct < 8:
        base = 4.0
        reason = f"умеренная волатильность (ATR {atr_pct:.1f}%)"
    elif atr_pct < 12:
        base = 3.0
        reason = f"высокая волатильность (ATR {atr_pct:.1f}%)"
    elif atr_pct < 20:
        base = 2.0
        reason = f"очень высокая волатильность (ATR {atr_pct:.1f}%)"
    else:
        base = 1.0
        reason = f"экстремальная волатильность (ATR {atr_pct:.1f}%)"

    leveraged = base * signal_strength

    final = min(leveraged, max_leverage)
    final = max(final, 1.0)

    final = round(final * 2) / 2

    return final, reason


def signal_strength(level_touches):
    """
    Сила сигнала по количеству касаний уровня.

    3-5 касаний  → 0.75
    6-10 касаний → 1.0
    11-20 касаний → 1.25
    20+ касаний  → 1.5
    """
    if level_touches < 6:
        return 0.75
    elif level_touches < 11:
        return 1.0
    elif level_touches < 21:
        return 1.25
    else:
        return 1.5


# ============================================
# ПРИМЕРЫ
# ============================================
if __name__ == '__main__':
    print("=== Таблица плеча по волатильности ===\n")
    print(f"{'ATR%':>6} {'Касаний':>8} {'Плечо':>7} {'Причина':<40}")
    print("-" * 70)

    tests = [
        (3.5, 5),
        (6.5, 8),
        (9.0, 12),
        (11.0, 25),
        (15.0, 5),
        (18.0, 15),
        (25.0, 10),
    ]

    for atr, touches in tests:
        strength = signal_strength(touches)
        lev, reason = calc_leverage(atr, strength, max_leverage=3.0)
        print(f"{atr:>6.1f} {touches:>8} {lev:>7.2f}x {reason:<40}")