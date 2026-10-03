"""
Фоновые потоки (QThread).

ВАЖНО: все тяжёлые операции (сеть, бэктест) выполняются ЗДЕСЬ,
чтобы GUI не подвисал. Результаты приходят через сигналы.
"""
from PyQt6.QtCore import QThread, pyqtSignal


# ============================================================
# СКАНЕР МОНЕТ
# ============================================================
class ScannerWorker(QThread):
    log_message = pyqtSignal(str, str)
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str)

    def __init__(self, top_n=10, parent=None):
        super().__init__(parent)
        self.top_n = top_n

    def run(self):
        try:
            from step7_coin_scanner import get_top_symbols
        except ImportError as e:
            self.finished_err.emit(f"step7_coin_scanner недоступен: {e}")
            return

        try:
            self.log_message.emit("🔄 Сканирую Bybit...", "#4DA3FF")

            def progress(msg):
                self.log_message.emit(f"   {msg}", "#8B92A0")

            symbols = get_top_symbols(
                n=self.top_n,
                verbose=False,
                progress_callback=progress,
            )
            if not symbols:
                self.finished_err.emit("Ничего не найдено по фильтрам")
                return
            self.finished_ok.emit(symbols)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {str(e)[:150]}")


# ============================================================
# БЭКТЕСТ
# ============================================================
class BacktestWorker(QThread):
    log_message = pyqtSignal(str, str)
    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)

    def __init__(self, symbols, days, override_config=None, parent=None):
        super().__init__(parent)
        self.symbols = list(symbols)
        self.days = days
        self.override_config = override_config or {}
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _cancel_check(self):
        return self._cancel

    def run(self):
        try:
            from backtest_runner import run_backtest
        except ImportError as e:
            self.finished_err.emit(f"backtest_runner недоступен: {e}")
            return

        try:
            strategy_name = self.override_config.get('STRATEGY_NAME')

            self.log_message.emit(
                f"📊 Бэктест: {len(self.symbols)} монет, {self.days} дней, "
                f"стратегия: {strategy_name or 'из config'}",
                "#4DA3FF"
            )

            def progress_cb(msg):
                self.log_message.emit(f"   {msg}", "#8B92A0")

            def status_cb(info):
                self.progress.emit(info['current'], info['total'], info['symbol'])

            result = run_backtest(
                self.symbols, self.days,
                progress_callback=progress_cb,
                cancel_check=self._cancel_check,
                status_callback=status_cb,
                override_config=self.override_config,
                strategy_name=strategy_name,
            )

            if self._cancel:
                self.finished_err.emit("Отменено пользователем")
                return

            self.finished_ok.emit(result)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {str(e)[:150]}")


# ============================================================
# A/B СРАВНЕНИЕ
# ============================================================
class CompareWorker(QThread):
    log_message = pyqtSignal(str, str)
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str)

    def __init__(self, symbols, configs, days, strategy_name=None, parent=None):
        super().__init__(parent)
        self.symbols = list(symbols)
        self.configs = configs
        self.days = days
        self.strategy_name = strategy_name

    def run(self):
        try:
            from backtest_compare import compare_configurations
        except ImportError as e:
            self.finished_err.emit(f"backtest_compare недоступен: {e}")
            return

        try:
            self.log_message.emit(
                f"🔬 Сравнение: {len(self.configs)} конфигов, "
                f"{len(self.symbols)} монет, {self.days} дней, "
                f"стратегия: {self.strategy_name or 'из config'}",
                "#7C5CFF"
            )

            def progress(msg):
                self.log_message.emit(f"   {msg}", "#8B92A0")

            results = compare_configurations(
                symbols=self.symbols,
                configs=self.configs,
                backtest_days=self.days,
                progress_callback=progress,
                strategy_name=self.strategy_name,
            )
            self.finished_ok.emit(results)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {str(e)[:150]}")


# ============================================================
# СИНХРОНИЗАЦИЯ (с импортом позиций с биржи)
# ============================================================
class SyncWorker(QThread):
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)

    def __init__(self, bot, parent=None):
        super().__init__(parent)
        self.bot = bot

    def run(self):
        result = {
            'balance': None, 'equity': None, 'positions': [],
            'imported': None, 'error': None,
        }
        try:
            from bybit_client import check_connection, get_equity

            try:
                bal = check_connection(self.bot.trader.exchange)
                result['balance'] = bal
            except Exception as e:
                result['error'] = f"balance: {str(e)[:100]}"

            try:
                eq = get_equity(self.bot.trader.exchange)
                result['equity'] = eq
            except Exception:
                pass

            removed = []
            added = []
            try:
                real_positions = self.bot.trader.exchange.fetch_positions()
                real_open = [
                    p for p in real_positions
                    if abs(float(p.get('contracts', 0) or 0)) > 0
                ]

                real_syms = {}
                for p in real_open:
                    sym = p.get('symbol')
                    if sym:
                        real_syms[sym] = p

                state_syms = set(self.bot.trader.state['open_positions'].keys())
                for sym in (state_syms - set(real_syms.keys())):
                    del self.bot.trader.state['open_positions'][sym]
                    removed.append(sym)

                for sym, p in real_syms.items():
                    if sym in self.bot.trader.state['open_positions']:
                        continue

                    try:
                        entry = float(p.get('entryPrice') or 0)
                        size = abs(float(p.get('contracts') or 0))
                        side_raw = (p.get('side') or '').lower()
                        side = 'LONG' if side_raw in ('buy', 'long') else 'SHORT'
                        leverage = float(p.get('leverage') or 1)
                        usd_size = entry * size

                        info = p.get('info', {}) or {}
                        stop = 0.0
                        take = 0.0
                        try:
                            if info.get('stopLoss'):
                                stop = float(info['stopLoss'])
                            if info.get('takeProfit'):
                                take = float(info['takeProfit'])
                        except Exception:
                            pass

                        if not stop:
                            stop = entry * (1 - 0.025) if side == 'LONG' \
                                else entry * (1 + 0.025)
                        if not take:
                            take = entry * (1 + 0.05) if side == 'LONG' \
                                else entry * (1 - 0.05)

                        stop_pct = abs(entry - stop) / entry * 100 if entry else 2.5
                        take_pct = abs(take - entry) / entry * 100 if entry else 5.0

                        self.bot.trader.state['open_positions'][sym] = {
                            'symbol': sym,
                            'side': side,
                            'entry': entry,
                            'amount': size,
                            'usd_size': usd_size,
                            'stop': stop,
                            'take': take,
                            'open_ts': '',
                            'order_id': '',
                            'stop_pct': stop_pct,
                            'take_pct': take_pct,
                            'stop_set': True,
                            'position_idx': int(info.get('positionIdx', 0) or 0),
                            'position_mode': 'one_way',
                            'leverage': leverage,
                            'adds': [],
                            'hedge': None,
                            'signal_type': 'imported',
                            'strategy': 'imported',
                        }
                        added.append(sym)
                    except Exception as e:
                        if not result['error']:
                            result['error'] = f"import {sym}: {str(e)[:80]}"

                if removed or added:
                    self.bot.trader._save_state()
                    result['imported'] = {'removed': removed, 'added': added}
            except Exception as e:
                if not result['error']:
                    result['error'] = f"positions: {str(e)[:100]}"

            try:
                positions = self.bot.trader.get_positions_status()
                result['positions'] = positions or []
            except Exception as e:
                if not result['error']:
                    result['error'] = f"status: {str(e)[:80]}"

            self.finished_ok.emit(result)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {str(e)[:150]}")


# ============================================================
# РУЧНОЕ ОТКРЫТИЕ
# ============================================================
class ManualOpenWorker(QThread):
    finished_ok = pyqtSignal(str, dict)
    finished_err = pyqtSignal(str)

    def __init__(self, bot, symbol, side, size_usd=None, parent=None):
        super().__init__(parent)
        self.bot = bot
        self.symbol = symbol
        self.side = side
        self.size_usd = size_usd

    def run(self):
        try:
            ok, msg, pos = self.bot.trader.open_position(
                self.symbol, self.side, size_usd=self.size_usd
            )
            if ok:
                self.finished_ok.emit(msg, pos or {})
            else:
                self.finished_err.emit(msg)
        except Exception as e:
            self.finished_err.emit(f"{type(e).__name__}: {str(e)[:150]}")