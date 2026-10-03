"""
Автобот с адаптивным размером, стопом по ATR, пирамидингом, хеджем, MTF.
Стратегия вынесена в strategies/ — переключается через config.ACTIVE_STRATEGY.

ДОБАВЛЕНО:
  - Адаптивный Trailing по ATR (через trailing_manager.py).
  - Автоподбор монет под текущий депозит (_deposit_auto_scan_coins).
"""
import time
import json
import os
import re
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np

from bybit_client import get_ticker
from trader import Trader
import config

from coin_manager import CoinManager
from strategies.registry import get_strategy

try:
    from leverage_manager import calc_leverage, signal_strength
    LEVERAGE_AVAILABLE = True
except ImportError:
    LEVERAGE_AVAILABLE = False

try:
    from trailing_manager import TrailingManager
    TRAILING_AVAILABLE = True
except ImportError:
    TRAILING_AVAILABLE = False

try:
    from report_manager import ReportManager
    REPORT_AVAILABLE = True
except ImportError:
    REPORT_AVAILABLE = False

try:
    from signal_logger import log_signal, log_trade_result
    SIGNAL_LOG_AVAILABLE = True
except ImportError:
    SIGNAL_LOG_AVAILABLE = False


class AutoTrader:
    def __init__(self):
        self.trader = Trader()
        self.exchange = self.trader.exchange
        self.is_running = False
        self._stop_flag = False
        self.coin_manager = CoinManager()

        self.on_log = None
        self.on_signal = None
        self.on_balance = None
        self.on_positions = None
        self.on_status = None
        self.on_report = None

        self.daily_stats = self._load_daily_stats()
        self.last_position_size = 0

        self.consecutive_errors = 0
        self.max_consecutive_errors = getattr(config, 'AUTO_MAX_CONSECUTIVE_ERRORS', 3)

        self.history_file = 'trade_history.json'
        self.trade_history = self._load_history()

        self.log_file = 'bot.log'
        self.max_log_size = 5 * 1024 * 1024

        self._aml_shared_buffer = []
        self._aml_shared_buffer_file = 'aml_buffer.json'
        self._load_aml_buffer()

        self.strategy = get_strategy(
            getattr(config, 'ACTIVE_STRATEGY', 'classic_levels'),
            self.trader,
            self._log,
        )
        self._last_features_by_symbol = {}

        # ==== TRAILING ====
        self.trailing = None
        if TRAILING_AVAILABLE and getattr(config, 'USE_TRAILING_STOP', False):
            self.trailing = TrailingManager(self, self._log)
            print("📈 Trailing: ВКЛЮЧЁН (адаптивный по ATR)"
                  if getattr(config, 'USE_TRAILING_ATR', True)
                  else "📈 Trailing: ВКЛЮЧЁН")
        else:
            print("📈 Trailing: ОТКЛЮЧЁН")

        self.reporter = None
        if REPORT_AVAILABLE:
            self.reporter = ReportManager()
            self.report_sent_date = None

        if SIGNAL_LOG_AVAILABLE:
            print("📝 Логирование сигналов: ВКЛЮЧЕНО")
        else:
            print("📝 Логирование сигналов: ОТКЛЮЧЕНО")

        print(f"🎯 Стратегия: {self.strategy.display_name}")

    # ============================================================
    # СМЕНА СТРАТЕГИИ
    # ============================================================
    def set_strategy(self, name: str):
        if self.is_running:
            self._log("⚠ Нельзя менять стратегию на ходу. Останови бота.", "#ff9800")
            return False
        try:
            self.strategy = get_strategy(name, self.trader, self._log)
            config.ACTIVE_STRATEGY = name

            if name == 'adaptive_ml' and hasattr(self.strategy, 'buffer'):
                for item in self._aml_shared_buffer:
                    feat = item.get('features')
                    label = item.get('label', 0)
                    if feat is not None:
                        self.strategy.buffer.append((feat, label))
                if self.strategy.buffer:
                    self._log(
                        f"🧠 AML: подгружено {len(self.strategy.buffer)} сэмплов",
                        "#7C4DFF"
                    )
                    if len(self.strategy.buffer) >= self.strategy.update_interval:
                        self.strategy._partial_fit()

            self._log(f"🎯 Стратегия: {self.strategy.display_name}", "#7C4DFF")
            return True
        except Exception as e:
            self._log(f"❌ Ошибка смены стратегии: {e}", "#f44336")
            return False

    # ============================================================
    # АВТОСКАН (старый, по рынку)
    # ============================================================
    def _auto_scan_coins(self):
        if not getattr(config, 'SCANNER_AUTO_ENABLED', False):
            return
        # Если включён автоподбор под депозит — не запускаем рыночный автоскан
        if getattr(config, 'DEPOSIT_AUTO_SCAN_ENABLED', False):
            return

        hours = getattr(config, 'SCANNER_AUTO_HOURS', 24)

        try:
            state_file = 'auto_scan_state.json'
            last_scan = None
            if os.path.exists(state_file):
                with open(state_file, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                last_scan = d.get('last_scan')
        except Exception:
            last_scan = None

        if last_scan:
            try:
                last_dt = datetime.fromisoformat(last_scan)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - last_dt
                if delta < timedelta(hours=hours):
                    return
            except Exception:
                pass

        self._log(f"🔍 Автоскан монет (раз в {hours}ч)...", "#448AFF")

        try:
            from step7_coin_scanner import get_top_symbols

            def progress(msg):
                self._log(f"   {msg}", "#888")

            new_symbols = get_top_symbols(verbose=False, progress_callback=progress)
            if not new_symbols:
                self._log("⚠ Автоскан: ничего не найдено", "#ff9800")
                return

            old_set = set(config.AUTO_SYMBOLS)
            new_set = set(new_symbols)
            added = new_set - old_set
            removed = old_set - new_set

            config.AUTO_SYMBOLS = new_symbols
            self._save_symbols_to_config(new_symbols)

            try:
                with open('auto_scan_state.json', 'w', encoding='utf-8') as f:
                    json.dump({
                        'last_scan': datetime.now(timezone.utc).isoformat(),
                        'symbols': new_symbols,
                    }, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

            self._log(f"✅ Автоскан: {len(new_symbols)} монет", "#4caf50")
            if added:
                self._log(f"   + {', '.join(sorted(added))}", "#4caf50")
            if removed:
                self._log(f"   − {', '.join(sorted(removed))}", "#ff9800")

        except Exception as e:
            self._log(f"⚠ Автоскан: {str(e)[:80]}", "#ff9800")

    # ============================================================
    # АВТОПОДБОР ПОД ДЕПОЗИТ
    # ============================================================
    def _deposit_auto_scan_coins(self, free_balance):
        """
        Пересчитывает AUTO_SYMBOLS под текущий free_balance.
        Запускается раз в DEPOSIT_AUTO_SCAN_HOURS ИЛИ при изменении баланса > 20%.
        """
        if not getattr(config, 'DEPOSIT_AUTO_SCAN_ENABLED', False):
            return

        if free_balance <= 0:
            return

        hours = getattr(config, 'DEPOSIT_AUTO_SCAN_HOURS', 1)
        state_file = 'deposit_scan_state.json'

        try:
            last_scan = None
            last_balance = 0.0
            if os.path.exists(state_file):
                with open(state_file, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                last_scan = d.get('last_scan')
                last_balance = float(d.get('balance', 0) or 0)

            if last_scan:
                try:
                    last_dt = datetime.fromisoformat(last_scan)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    delta = datetime.now(timezone.utc) - last_dt

                    # Пересчёт если прошло N часов ИЛИ баланс изменился > 20%
                    balance_changed = False
                    if last_balance > 0:
                        diff_pct = abs(free_balance - last_balance) / last_balance * 100
                        if diff_pct > 20:
                            balance_changed = True

                    if delta < timedelta(hours=hours) and not balance_changed:
                        return
                except Exception:
                    pass

            self._log(
                f"💰 Автоподбор под депозит (${free_balance:.2f})...",
                "#448AFF"
            )

            from deposit_coin_filter import scan_for_deposit

            def progress(msg):
                self._log(f"   {msg}", "#888")

            new_symbols = scan_for_deposit(
                free_balance=free_balance,
                verbose=False,
                progress_callback=progress,
            )

            if not new_symbols:
                self._log("⚠ Автоподбор: монет не найдено", "#ff9800")
                # Обновим timestamp, чтобы не дёргать API каждую минуту
                with open(state_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'last_scan': datetime.now(timezone.utc).isoformat(),
                        'balance': free_balance,
                        'symbols': list(config.AUTO_SYMBOLS),
                    }, f, indent=2, ensure_ascii=False)
                return

            old_set = set(config.AUTO_SYMBOLS)
            new_set = set(new_symbols)

            if old_set == new_set:
                self._log("✅ Список монет актуален", "#4caf50")
                with open(state_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'last_scan': datetime.now(timezone.utc).isoformat(),
                        'balance': free_balance,
                        'symbols': new_symbols,
                    }, f, indent=2, ensure_ascii=False)
                return

            added = new_set - old_set
            removed = old_set - new_set

            config.AUTO_SYMBOLS = new_symbols
            self._save_symbols_to_config(new_symbols)

            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'last_scan': datetime.now(timezone.utc).isoformat(),
                    'balance': free_balance,
                    'symbols': new_symbols,
                }, f, indent=2, ensure_ascii=False)

            self._log(
                f"✅ Автоподбор под депозит: {len(new_symbols)} монет",
                "#4caf50"
            )
            if added:
                self._log(f"   + {', '.join(sorted(added))}", "#4caf50")
            if removed:
                self._log(f"   − {', '.join(sorted(removed))}", "#ff9800")

            if self.on_log:
                self.on_log(
                    f"💰 Список монет обновлён под депозит: {len(new_symbols)}",
                    "#4caf50"
                )
        except Exception as e:
            self._log(f"⚠ Автоподбор под депозит: {str(e)[:100]}", "#ff9800")

    # ============================================================
    # DAILY STATS
    # ============================================================
    def _load_daily_stats(self):
        if os.path.exists('auto_daily.json'):
            try:
                with open('auto_daily.json', 'r', encoding='utf-8') as f:
                    d = json.load(f)
                if d.get('date') == datetime.now(timezone.utc).strftime('%Y-%m-%d'):
                    return d
            except Exception:
                pass
        return {
            'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'trades': 0, 'pnl_pct': 0.0, 'stopped': False,
        }

    def _save_daily_stats(self):
        try:
            with open('auto_daily.json', 'w', encoding='utf-8') as f:
                json.dump(self.daily_stats, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _reset_if_new_day(self):
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        if self.daily_stats['date'] != today:
            if self.reporter:
                try:
                    self.reporter.save_daily_report()
                except Exception:
                    pass

            self.daily_stats = {
                'date': today, 'trades': 0, 'pnl_pct': 0.0, 'stopped': False,
            }
            self._save_daily_stats()
            self._log(f"🔄 Новый день: {today}", "#4caf50")

            self._log("⏸ Пауза 10 сек...", "#888")
            for _ in range(10):
                if self._stop_flag:
                    return
                time.sleep(1)

    # ============================================================
    # ИСТОРИЯ
    # ============================================================
    def _load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_history(self):
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.trade_history, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def add_to_history(self, trade):
        self.trade_history.append(trade)
        if len(self.trade_history) > 5000:
            self.trade_history = self.trade_history[-5000:]
        self._save_history()

    def get_history(self, limit=100):
        return list(reversed(self.trade_history[-limit:]))

    def get_stats(self, days=7):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        recent = [t for t in self.trade_history if t.get('exit_ts', '') >= cutoff_iso]

        if not recent:
            return {'period_days': days, 'total': 0, 'wins': 0, 'losses': 0,
                    'winrate': 0.0, 'pnl_pct': 0.0, 'pnl_usd': 0.0,
                    'best': 0.0, 'worst': 0.0, 'avg': 0.0}

        wins = sum(1 for t in recent if t.get('pnl_pct', 0) > 0)
        losses = sum(1 for t in recent if t.get('pnl_pct', 0) < 0)
        pnl_pct = sum(t.get('pnl_pct', 0) for t in recent)
        pnl_usd = sum(t.get('pnl_usd', 0) for t in recent)
        pnls = [t.get('pnl_pct', 0) for t in recent]

        return {
            'period_days': days, 'total': len(recent),
            'wins': wins, 'losses': losses,
            'winrate': wins / len(recent) * 100,
            'pnl_pct': pnl_pct, 'pnl_usd': pnl_usd,
            'best': max(pnls) if pnls else 0.0,
            'worst': min(pnls) if pnls else 0.0,
            'avg': pnl_pct / len(recent) if recent else 0.0,
        }

    # ============================================================
    # ЛОГИ
    # ============================================================
    def _log(self, msg, color=None):
        timestamp = datetime.now().strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}"
        print(line)
        if self.on_log:
            self.on_log(msg, color)
        try:
            self._write_log(line)
        except Exception:
            pass

    def _write_log(self, line):
        try:
            if os.path.exists(self.log_file) and os.path.getsize(self.log_file) > self.max_log_size:
                backup = self.log_file + '.old'
                if os.path.exists(backup):
                    os.remove(backup)
                os.rename(self.log_file, backup)

            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

    # ============================================================
    # РАЗМЕР ПОЗИЦИИ
    # ============================================================
    def _calc_position_size(self, free_balance, atr_pct=None):
        base_pct = getattr(config, 'AUTO_POSITION_PCT', 5.0)

        if getattr(config, 'USE_ADAPTIVE_SIZE', False) and atr_pct is not None:
            low = getattr(config, 'ADAPTIVE_ATR_LOW', 5.0)
            high = getattr(config, 'ADAPTIVE_ATR_HIGH', 12.0)
            min_pct = getattr(config, 'ADAPTIVE_SIZE_MIN_PCT', 3.0)
            max_pct = getattr(config, 'ADAPTIVE_SIZE_MAX_PCT', 8.0)

            if atr_pct <= low:
                pct = max_pct
            elif atr_pct >= high:
                pct = min_pct
            else:
                ratio = (atr_pct - low) / (high - low)
                pct = max_pct - ratio * (max_pct - min_pct)

            self._log(f"📊 Адаптив размер: ATR {atr_pct:.1f}% → {pct:.2f}%", "#888")
        else:
            pct = base_pct

        min_size = getattr(config, 'AUTO_MIN_POSITION_USD', 10)
        max_size = getattr(config, 'AUTO_MAX_POSITION_USD', 100_000)

        size_by_pct = free_balance * (pct / 100)
        size = max(min_size, min(max_size, size_by_pct))
        return size, size_by_pct, pct

    def _compute_features_for_aml(self, symbol):
        try:
            raw = self.exchange.fetch_ohlcv(symbol, config.TIMEFRAME_M15, limit=200)
            df = pd.DataFrame(raw, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            if len(df) < 60:
                return None

            c = df['close']
            f = {}

            for p in [1, 3, 5, 10, 20]:
                f[f'ret_{p}'] = c.pct_change(p).iloc[-1]

            for p in [5, 10, 20, 50]:
                sma = c.rolling(p).mean().iloc[-1]
                f[f'sma_{p}_ratio'] = (c.iloc[-1] / sma - 1) if sma else 0.0

            delta = c.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean().iloc[-1]
            loss = -delta.where(delta < 0, 0).rolling(14).mean().iloc[-1]
            f['rsi_14'] = 100 - 100 / (1 + gain / loss) if loss else 50.0

            ema12 = c.ewm(span=12).mean().iloc[-1]
            ema26 = c.ewm(span=26).mean().iloc[-1]
            f['macd'] = ema12 - ema26
            f['macd_sig'] = float(c.ewm(span=12).mean().sub(c.ewm(span=26).mean()).ewm(span=9).mean().iloc[-1])

            hl = df['high'] - df['low']
            hc = (df['high'] - c.shift()).abs()
            lc = (df['low'] - c.shift()).abs()
            tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
            f['atr_14'] = tr.rolling(14).mean().iloc[-1] / c.iloc[-1]

            f['vol_20'] = c.pct_change().rolling(20).std().iloc[-1]

            v = df['volume']
            f['vol_ratio'] = (v.iloc[-1] / v.rolling(20).mean().iloc[-1]) if v.rolling(20).mean().iloc[-1] else 1.0

            order = [
                'ret_1','ret_3','ret_5','ret_10','ret_20',
                'sma_5_ratio','sma_10_ratio','sma_20_ratio','sma_50_ratio',
                'rsi_14','macd','macd_sig','atr_14','vol_20','vol_ratio',
            ]
            vals = [float(f.get(k, 0.0)) for k in order]
            vals = [0.0 if v != v else v for v in vals]
            return vals
        except Exception:
            return None

    # ============================================================
    # ПРОВЕРКА ЗАКРЫТЫХ ПОЗИЦИЙ
    # ============================================================
    def check_closed_positions(self):
        try:
            open_syms = list(self.trader.state['open_positions'].keys())
            if not open_syms:
                return

            try:
                positions = self.exchange.fetch_positions()
            except Exception as e:
                self._log(f"⚠ fetch_positions: {str(e)[:80]}", "#ff9800")
                return

            open_now = set()
            for p in positions:
                try:
                    if abs(float(p.get('contracts', 0) or 0)) > 0:
                        sym = p.get('symbol')
                        if sym:
                            open_now.add(sym)
                except Exception:
                    continue

            for symbol in list(self.trader.state['open_positions'].keys()):
                if symbol not in open_now:
                    pos = self.trader.state['open_positions'][symbol]
                    try:
                        current = get_ticker(self.exchange, symbol)
                        pnl_pct = self.trader._calc_pnl_pct(pos, current)
                    except Exception:
                        current = pos.get('entry', 0)
                        pnl_pct = 0.0

                    pnl_usd = pos.get('usd_size', 0) * pnl_pct / 100
                    exit_ts = datetime.now(timezone.utc).isoformat()

                    duration_h = 0
                    try:
                        open_dt = datetime.fromisoformat(
                            pos.get('open_ts', '').replace('Z', '+00:00')
                        )
                        exit_dt = datetime.now(timezone.utc)
                        duration_h = (exit_dt - open_dt).total_seconds() / 3600
                    except Exception:
                        pass

                    trade_record = {
                        'symbol': symbol, 'side': pos['side'],
                        'entry': pos['entry'], 'exit': current,
                        'usd_size': pos.get('usd_size', 0),
                        'pnl_pct': round(pnl_pct, 2),
                        'pnl_usd': round(pnl_usd, 2),
                        'open_ts': pos.get('open_ts', ''),
                        'exit_ts': exit_ts,
                        'reason': 'closed',
                        'signal_type': pos.get('signal_type', 'unknown'),
                        'touches': pos.get('touches'),
                        'atr_pct': pos.get('atr_pct'),
                        'trend': pos.get('trend'),
                        'distance_to_level_pct': pos.get('distance_to_level_pct'),
                        'strategy': pos.get('strategy', '?'),
                    }

                    self.add_to_history(trade_record)

                    try:
                        trade_for_strategy = dict(trade_record)
                        trade_for_strategy['features'] = self._last_features_by_symbol.pop(symbol, None)
                        self.strategy.on_trade_closed(trade_for_strategy)
                        self._feed_aml_buffer(trade_for_strategy)
                    except Exception as e:
                        self._log(f"⚠ on_trade_closed: {str(e)[:80]}", "#ff9800")

                    if SIGNAL_LOG_AVAILABLE and pos.get('open_ts'):
                        try:
                            log_trade_result(
                                symbol=symbol,
                                entry_ts=pos.get('open_ts'),
                                exit_ts=exit_ts,
                                pnl_pct=round(pnl_pct, 2),
                                pnl_usd=round(pnl_usd, 2),
                                duration_h=round(duration_h, 2),
                                result='TAKE' if pnl_pct > 0 else 'STOP',
                                reason='closed',
                            )
                        except Exception as e:
                            self._log(f"⚠ log_trade_result: {str(e)[:60]}", "#ff9800")

                    self.daily_stats['pnl_pct'] += pnl_pct
                    self._save_daily_stats()

                    self._log(f"🏁 {symbol} закрыта. P&L: {pnl_pct:+.2f}%",
                              "#4caf50" if pnl_pct > 0 else "#f44336")

                    if self.trailing:
                        self.trailing.clear(symbol)

                    del self.trader.state['open_positions'][symbol]
                    self.trader._save_state()
        except Exception as e:
            self._log(f"⚠ check_closed: {str(e)[:80]}", "#ff9800")

    # ============================================================
    # ДНЕВНОЙ ОТЧЁТ
    # ============================================================
    def _maybe_send_daily_report(self):
        if not self.reporter or not getattr(config, 'DAILY_REPORT_ENABLED', True):
            return

        now = datetime.now(timezone.utc)
        target_h = getattr(config, 'DAILY_REPORT_HOUR', 23)
        target_m = getattr(config, 'DAILY_REPORT_MINUTE', 0)
        today = now.strftime('%Y-%m-%d')

        if self.report_sent_date == today:
            return

        if now.hour == target_h and now.minute >= target_m:
            report = self.reporter.save_daily_report()
            text = self.reporter.format_report_text(report)
            self._log("📊 ДНЕВНОЙ ОТЧЁТ:", "#1565c0")
            for line in text.split('\n'):
                self._log(f"   {line}", "#888")
            if self.on_report:
                self.on_report(text)
            self.report_sent_date = today

    # ============================================================
    # ПИРАМИДИНГ / ХЕДЖ
    # ============================================================
    def _check_pyramiding(self):
        if not getattr(config, 'USE_PYRAMIDING', False):
            return
        for symbol, pos in list(self.trader.state['open_positions'].items()):
            if not pos.get('adds'):
                pos['adds'] = []
            if len(pos['adds']) >= getattr(config, 'PYRAMID_MAX_ADD', 2):
                continue
            try:
                ok, msg = self.trader.add_to_position(symbol)
                if ok:
                    self._log(f"🎲 {msg}", "#4caf50")
            except AttributeError:
                pass
            except Exception as e:
                self._log(f"⚠ Pyramid {symbol}: {str(e)[:60]}", "#ff9800")

    def _check_hedging(self):
        if not getattr(config, 'USE_HEDGING', False):
            return
        for symbol, pos in list(self.trader.state['open_positions'].items()):
            if pos.get('hedge'):
                continue
            try:
                ok, msg = self.trader.hedge_position(symbol)
                if ok:
                    self._log(f"🛡 {msg}", "#ff9800")
            except AttributeError:
                pass
            except Exception as e:
                self._log(f"⚠ Hedge {symbol}: {str(e)[:60]}", "#ff9800")

    # ============================================================
    # СТАРТ / СТОП
    # ============================================================
    def start(self):
        self.is_running = True
        self._stop_flag = False
        self.consecutive_errors = 0

        pct = config.AUTO_POSITION_PCT
        self._log("🤖 Автобот запущен", "#4caf50")
        self._log(f"🎯 Стратегия: {self.strategy.display_name}", "#7C4DFF")
        self._log(f"Монет: {len(config.AUTO_SYMBOLS)}", "#888")
        self._log(f"Размер: {pct}% (адаптивный: {config.USE_ADAPTIVE_SIZE})", "#888")
        self._log(f"Плечо: до {config.MAX_AUTO_LEVERAGE}x", "#888")
        self._log(f"MTF: {config.USE_MULTI_TIMEFRAME}", "#888")
        self._log(f"Trailing: {config.USE_TRAILING_STOP} "
                  f"(ATR-режим: {getattr(config, 'USE_TRAILING_ATR', False)})", "#888")
        self._log(f"Адаптивный стоп: {config.USE_ADAPTIVE_STOP}", "#888")
        self._log(f"Пирамидинг: {config.USE_PYRAMIDING}", "#888")
        self._log(f"Хеджирование: {config.USE_HEDGING}", "#888")
        self._log(
            f"Автоподбор под депозит: {getattr(config, 'DEPOSIT_AUTO_SCAN_ENABLED', False)}",
            "#888"
        )

    def stop(self):
        self._stop_flag = True
        self.is_running = False
        self._log("⏹ Автобот остановлен", "#f44336")

    # ============================================================
    # ЛОГИРОВАНИЕ СИГНАЛА
    # ============================================================
    def _log_signal_safe(self, symbol, sig, price, level_price, touches,
                         atr_pct, trend, distance_pct, opened, reason):
        if not SIGNAL_LOG_AVAILABLE:
            return
        try:
            log_signal({
                'symbol': symbol,
                'side': sig.direction,
                'signal_type': sig.reason or sig.meta.get('signal_type', 'SIG'),
                'price': price,
                'level_price': level_price,
                'touches': touches,
                'atr_pct': atr_pct,
                'trend': trend,
                'distance_to_level_pct': distance_pct,
                'opened': opened,
                'reason': reason,
            })
        except Exception:
            pass

    def _load_aml_buffer(self):
        if os.path.exists(self._aml_shared_buffer_file):
            try:
                with open(self._aml_shared_buffer_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._aml_shared_buffer = data[-5000:] if isinstance(data, list) else []
            except Exception:
                self._aml_shared_buffer = []

    def _save_aml_buffer(self):
        try:
            with open(self._aml_shared_buffer_file, 'w', encoding='utf-8') as f:
                json.dump(self._aml_shared_buffer[-5000:], f)
        except Exception:
            pass

    def _feed_aml_buffer(self, trade):
        feat = trade.get('features')
        if feat is None:
            return
        label = 1 if trade.get('pnl_pct', 0) > 0 else 0
        self._aml_shared_buffer.append({'features': feat, 'label': label})
        self._save_aml_buffer()

    # ============================================================
    # ОСНОВНОЙ ЦИКЛ
    # ============================================================
    def check_cycle(self):
        if self._stop_flag:
            return

        self._reset_if_new_day()
        self._maybe_send_daily_report()

        if self.daily_stats.get('stopped'):
            return

        if self.daily_stats['pnl_pct'] <= -config.AUTO_DAILY_STOP_PCT:
            self.daily_stats['stopped'] = True
            self._save_daily_stats()
            self._log(f"🛑 ДНЕВНОЙ СТОП!", "#f44336")
            return

        if self.daily_stats['trades'] >= config.AUTO_MAX_TRADES_PER_DAY:
            return

        if getattr(config, 'AUTO_MANAGE_COINS', True):
            self._auto_manage_coins()

        # Рыночный автоскан (отключён, если включён автоподбор по депозиту)
        self._auto_scan_coins()

        self.check_closed_positions()

        if self.trailing:
            try:
                self.trailing.update_all()
            except Exception as e:
                self._log(f"⚠ Trailing: {str(e)[:60]}", "#ff9800")

        self._check_pyramiding()
        self._check_hedging()

        # ==== БАЛАНС ====
        try:
            result = self.exchange.private_get_v5_account_wallet_balance({
                'accountType': 'UNIFIED',
                'coin': 'USDT',
            })
            if result.get('retCode') != 0:
                raise Exception(
                    f"Bybit {result.get('retCode')}: "
                    f"{result.get('retMsg', '')[:80]}"
                )

            accounts = result.get('result', {}).get('list', [])
            if accounts:
                acc = accounts[0]
                free = float(acc.get('totalAvailableBalance', 0) or 0)
                total = float(acc.get('totalEquity', 0) or 0)
            else:
                free = total = 0.0
            self.consecutive_errors = 0
        except Exception as e:
            self.consecutive_errors += 1
            self._log(f"Ошибка баланса: {str(e)[:80]}", "#f44336")
            if self.consecutive_errors >= self.max_consecutive_errors:
                self.stop()
            return

        # ==== АВТОПОДБОР ПОД ДЕПОЗИТ (после получения free) ====
        self._deposit_auto_scan_coins(free)

        if total < config.AUTO_MIN_FREE_BALANCE:
            return

        if self.on_balance:
            self.on_balance({'total': total, 'free': free, 'used': total - free})

        signals_found = 0
        opened = 0

        for symbol in config.AUTO_SYMBOLS:
            if self._stop_flag:
                return
            if symbol in self.trader.state['open_positions']:
                continue
            if len(self.trader.state['open_positions']) >= config.MAX_POSITIONS_TOTAL:
                break

            try:
                sig = self.strategy.check_symbol(symbol, free)
            except Exception as e:
                self._log(f"Ошибка {symbol}: {str(e)[:80]}", "#f44336")
                continue

            if sig is not None and 'features' not in (sig.meta or {}):
                try:
                    sig.meta['features'] = self._compute_features_for_aml(symbol)
                except Exception:
                    sig.meta['features'] = None

            if not sig:
                continue

            signals_found += 1

            sig_type = sig.meta.get('signal_type', sig.reason or 'SIG')
            level_price = sig.meta.get('level_price', 0)
            touches = sig.meta.get('touches', 0)
            atr_pct = sig.meta.get('atr_pct')
            trend = sig.meta.get('trend', '?')
            signal_price = sig.meta.get('price', 0)
            distance_pct = sig.meta.get('distance_to_level_pct', 0)

            if sig.size_usd is not None:
                size = sig.size_usd
            else:
                size, _size_by_pct, _used_pct = self._calc_position_size(free, atr_pct)

            if sig.leverage is not None:
                lev = sig.leverage
                lev_info = f"плечо {lev}x (strategy)"
            elif LEVERAGE_AVAILABLE and config.USE_AUTO_LEVERAGE and touches:
                strength = signal_strength(touches)
                lev, lev_reason = calc_leverage(atr_pct, strength, config.MAX_AUTO_LEVERAGE)
                lev_info = f"плечо {lev}x ({lev_reason})"
            else:
                lev = config.DEFAULT_LEVERAGE
                lev_info = f"плечо {lev}x"

            if level_price:
                self._log(
                    f"🔔 {sig.direction} {symbol} (ур. {level_price:.6f}, x{touches}, {sig_type}) "
                    f"— {lev_info}",
                    "#1565c0"
                )
            else:
                self._log(
                    f"🔔 {sig.direction} {symbol} ({sig_type}, conf={sig.confidence:.2f}) "
                    f"— {lev_info}",
                    "#1565c0"
                )

            if self.on_signal:
                try:
                    self.on_signal(symbol, sig.direction, {'price': level_price})
                except Exception:
                    pass

            can_open = True
            skip_reason = ""

            if len(self.trader.state['open_positions']) >= config.MAX_POSITIONS_TOTAL:
                can_open = False
                skip_reason = "max_positions"
            elif self.daily_stats['trades'] >= config.AUTO_MAX_TRADES_PER_DAY:
                can_open = False
                skip_reason = "max_trades_per_day"

            if not can_open:
                self._log(f"❌ {skip_reason}", "#f44336")
                self._log_signal_safe(
                    symbol, sig, signal_price, level_price, touches,
                    atr_pct, trend, distance_pct,
                    opened=False, reason=skip_reason,
                )
                continue

            try:
                old_max = config.MAX_POSITION_USD
                config.MAX_POSITION_USD = size

                ok, msg, pos = self.trader.open_position(
                    symbol, sig.direction,
                    stop_pct=sig.stop_pct,
                    take_pct=sig.take_pct,
                    size_usd=size,
                    atr_pct=atr_pct,
                    leverage=lev,
                )

                config.MAX_POSITION_USD = old_max

                if ok:
                    opened += 1
                    self.daily_stats['trades'] += 1
                    self._save_daily_stats()
                    self._log(f"✅ {msg} (${size:.2f}, {lev}x)", "#4caf50")

                    if symbol in self.trader.state['open_positions']:
                        p = self.trader.state['open_positions'][symbol]
                        p['signal_type'] = sig_type
                        p['touches'] = touches
                        p['atr_pct'] = atr_pct
                        p['trend'] = trend
                        p['distance_to_level_pct'] = distance_pct
                        p['strategy'] = self.strategy.name
                        p['confidence'] = sig.confidence
                        self.trader._save_state()

                    if 'features' in sig.meta:
                        self._last_features_by_symbol[symbol] = sig.meta['features']

                    self._log_signal_safe(
                        symbol, sig, signal_price, level_price, touches,
                        atr_pct, trend, distance_pct,
                        opened=True, reason='opened',
                    )
                else:
                    self._log(f"❌ {msg}", "#f44336")
                    self._log_signal_safe(
                        symbol, sig, signal_price, level_price, touches,
                        atr_pct, trend, distance_pct,
                        opened=False, reason=f'open_failed: {msg[:60]}',
                    )
            except Exception as e:
                self._log(f"❌ {str(e)[:80]}", "#f44336")

        if self.on_positions:
            try:
                self.on_positions(self.trader.get_positions_status())
            except Exception:
                pass

        if self.on_status:
            self.on_status({
                'trades_today': self.daily_stats['trades'],
                'pnl_today': self.daily_stats['pnl_pct'],
                'open_positions': len(self.trader.state['open_positions']),
                'free_balance': free,
            })

    # ============================================================
    # АВТОУПРАВЛЕНИЕ МОНЕТАМИ
    # ============================================================
    def _auto_manage_coins(self):
        try:
            hours = getattr(config, 'COIN_ANALYSIS_HOURS', 6)
            if not self.coin_manager.can_analyze(hours=hours):
                return
            current = list(config.AUTO_SYMBOLS)
            new_symbols, changes = self.coin_manager.analyze_and_update(
                current,
                min_trades=getattr(config, 'COIN_MIN_TRADES', 5),
                min_pnl_pct=getattr(config, 'COIN_MIN_PNL_PCT', -3.0),
                consecutive_losses=getattr(config, 'COIN_CONSECUTIVE_LOSSES', 2),
            )
            if changes:
                for c in changes:
                    self._log(f"🚫 {c['symbol']}: {c['reason']}", "#ff9800")
                config.AUTO_SYMBOLS = new_symbols
                self._save_symbols_to_config(new_symbols)
            self.coin_manager.mark_scan_done()
        except Exception as e:
            self._log(f"⚠ auto_manage: {str(e)[:80]}", "#ff9800")

    def _save_symbols_to_config(self, symbols):
        try:
            with open('config.py', 'r', encoding='utf-8') as f:
                content = f.read()
            block = "AUTO_SYMBOLS = [\n"
            for c in symbols:
                block += f"    '{c}',\n"
            block += "]"
            new = re.sub(r'^AUTO_SYMBOLS\s*=\s*\[[^\]]*\]', block, content,
                         flags=re.MULTILINE | re.DOTALL)
            with open('config.py', 'w', encoding='utf-8') as f:
                f.write(new)
        except Exception:
            pass


if __name__ == '__main__':
    bot = AutoTrader()
    bot.start()
    print("\nCtrl+C для остановки\n")
    try:
        while True:
            bot.check_cycle()
            time.sleep(config.AUTO_CHECK_INTERVAL_SEC)
    except KeyboardInterrupt:
        bot.stop()