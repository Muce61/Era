import pandas as pd
import pandas_ta as ta
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import logging
from strategy.momentum import MomentumStrategy
from risk.manager import RiskManager
from config.settings import Config

from strategy.smart_exit import SmartExitModule
from strategy.quality_filter import QualityFilterModule

from risk.trend_reversal_detector import TrendReversalDetector

class RealBacktestEngine:
    def __init__(self, initial_balance=100): # User requested 100u
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.peak_balance = initial_balance # Track peak balance for drawdown calc
        self.positions = {} # {symbol: {entry_price, quantity, stop_loss, ...}}
        self.paper_positions = {} # Virtual positions for circuit breaker recovery
        self.trades = []
        self.pending_signals = []  # List of pending signals for realistic entry
        self.strategy = MomentumStrategy()
        self.risk_manager = RiskManager()
        self.config = Config()
        
        # Initialize New Modules
        self.smart_exit = SmartExitModule()
        self.quality_filter = QualityFilterModule()
        self.trend_detector = TrendReversalDetector(state_file="logs/backtest_trend_state.json")
        
        # Override config for backtest if needed
        self.config.MAX_OPEN_POSITIONS = 10 # Match live config
        self.config.LEVERAGE = 50 # Match live config (was 20)
        self.risk_manager.config.LEVERAGE = 50
        self.config.TRADE_MARGIN_PERCENT = 0.1 # Match live config
        self.risk_manager.config.TRADE_MARGIN_PERCENT = 0.1
        
        # Quality Filters (NEW)
        # self.MIN_24H_VOLUME_USD = 10_000_000  # REMOVED: Unused. Logic uses QualityFilterModule (50M).
        self.TOP_N_COINS = 200  # Only trade top 200 coins by volume
        
        # DYNAMIC UNIVERSE STATE
        self.active_universe = set() # Set of symbols in current Top 200
        self.coin_volume_ranking = {} # Map of symbol -> rank (Dynamic)
        self.last_universe_update = None # Date of last update
        
        # Load Leverage Limits Snapshot
        self.leverage_limits = {}
        try:
            import json
            snapshot_path = Path("backtest/leverage_snapshot.json")
            if snapshot_path.exists():
                with open(snapshot_path, 'r') as f:
                    self.leverage_limits = json.load(f)
                print(f"✅ Loaded leverage limits for {len(self.leverage_limits)} symbols into backtest.")
            else:
                print("Warning: Leverage snapshot not found. Using defaults.")
        except Exception as e:
            print(f"Warning: Failed to load leverage snapshot: {e}")
        
    def load_data(self):
        """
        Load all CSVs from /Users/muce/1m_data/new_backtest_data_1year_1m/ into a dictionary of DataFrames.
        Performs resampling from 1m to 15m granularity for strategy consistency.
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        print(f"Loading data from {data_dir}...")
        print("Applying 1m -> 15m resampling...")
        
        # Check if directory exists
        if not data_dir.exists():
            print(f"WARNING: Data directory {data_dir} does not exist!")
            return

        for file_path in data_dir.glob("*.csv"):
            symbol = file_path.stem # e.g. BTCUSDT
            try:
                df = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                
                # Resample 1m to 15m
                agg_dict = {
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }
                
                # Handle potential missing columns or different case
                available_cols = df.columns.tolist()
                final_agg = {}
                for col, func in agg_dict.items():
                    if col in available_cols:
                        final_agg[col] = func
                    elif col.capitalize() in available_cols: # Try Title case
                        final_agg[col.capitalize()] = func
                        
                if not final_agg:
                    print(f"Skipping {symbol}: No OHLCV columns found")
                    continue
                    
                df_15m = df.resample('15min').agg(final_agg).dropna()
                
                # Normalize column names to lowercase
                df_15m.columns = [c.lower() for c in df_15m.columns]
                
                self.data_feed[symbol] = df_15m
            except Exception as e:
                print(f"Error loading {symbol}: {e}")
            
        print(f"Loaded {len(self.data_feed)} symbols (Resampled to 15m).")
        
    def run(self, days=None, start_date=None, end_date=None):
        if not hasattr(self, 'data_feed') or not self.data_feed:
            self.load_data()
            
        # 1. Align Timestamps
        all_timestamps = set()
        for df in self.data_feed.values():
            all_timestamps.update(df.index)
            
        sorted_timestamps = sorted(list(all_timestamps))
        
        # Filter by Date Range
        if start_date:
            start_ts = pd.Timestamp(start_date)
            if start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize('UTC')
            sorted_timestamps = [t for t in sorted_timestamps if t >= start_ts]
            
        if end_date:
            end_ts = pd.Timestamp(end_date)
            if end_ts.tzinfo is None:
                end_ts = end_ts.tz_localize('UTC')
            sorted_timestamps = [t for t in sorted_timestamps if t <= end_ts]
            
        # Filter for last N days if requested (overrides start_date if both present, or used in conjunction?)
        # Let's make 'days' mutually exclusive or secondary to explicit dates.
        # If start_date is NOT provided but days IS provided:
        if days and not start_date:
            end_time = sorted_timestamps[-1]
            start_time = end_time - timedelta(days=days)
            sorted_timestamps = [t for t in sorted_timestamps if t >= start_time]
            print(f"Filtered to last {days} days: {len(sorted_timestamps)} candles")
        
        if not sorted_timestamps:
            print("No data found for the specified date range.")
            return

        print(f"Backtesting over {len(sorted_timestamps)} timestamps...")
        print(f"Start: {sorted_timestamps[0]}, End: {sorted_timestamps[-1]}")
        
        # 2. Iterate through time
        # Calculate frequency dynamically
        if len(sorted_timestamps) > 1:
            diff = (sorted_timestamps[1] - sorted_timestamps[0]).total_seconds()
            lookback_24h = int(86400 / diff)
            print(f"Detected Timeframe: {int(diff/60)}m | 24h Lookback: {lookback_24h} candles")
        else:
            lookback_24h = 96 # Fallback to 15m default
        
        # If we filtered by days, we might need to load more history for indicators
        # But for simplicity, we just start from the filtered start index
        # In a real engine, we'd keep previous data for lookback. 
        # Here, we assume data_feed has full history, so we can just look back.
        
        # Find index of first timestamp in our filtered list
        # Actually, we are iterating by index of sorted_timestamps. 
        # If we sliced sorted_timestamps, we need to be careful about lookups in data_feed.
        # data_feed has full history, so looking up by timestamp is fine.
        
        start_index = 0 
        # But we need to ensure we have enough history BEFORE the first timestamp for indicators
        # The strategy checks history using df.loc[:current_time]. 
        # So as long as data_feed has data before sorted_timestamps[0], we are good.
        
        for i in range(start_index, len(sorted_timestamps)):
            current_time = sorted_timestamps[i]

            should_scan_market = True
            if not self.config.ALLOW_DEVELOPING_SIGNALS and diff < 900:
                should_scan_market = (current_time.minute + 1) % 15 == 0
                
            # 1. Execute pending signals at their next candle open.
            remaining_signals = []
            for signal in self.pending_signals[:]:
                if signal['entry_time'] == current_time:
                    symbol = signal['symbol']
                    entry_price = signal['entry_price']
                    metrics = signal['metrics']
                    
                    self._open_position(
                        symbol,
                        entry_price,
                        current_time,
                        signal.get('history_slice'),
                        metrics,
                        is_paper_trade=signal.get('is_paper_trade', False)
                    )
                elif signal['entry_time'] > current_time:
                    remaining_signals.append(signal)

            self.pending_signals = remaining_signals
            
            # 2. Manage Existing Positions
            self._manage_positions(current_time)
            
            # 3. Check for New Entries (only if slots available)
            if should_scan_market and len(self.positions) < self.config.MAX_OPEN_POSITIONS:
                self._scan_market(current_time)
                
            if i % 100 == 0:
                print(f"Processing {current_time}... Balance: ${self.balance:.2f}")
                
        self._generate_report(days)
        
    def _manage_positions(self, current_time):
        # Create a list of keys to iterate safely while modifying dict
        # Manage Real Positions
        for symbol in list(self.positions.keys()):

            self._manage_single_position(symbol, current_time, is_paper=False)
            
        # Manage Paper Positions
        for symbol in list(self.paper_positions.keys()):
            self._manage_single_position(symbol, current_time, is_paper=True)

    def _manage_single_position(self, symbol, current_time, is_paper=False):
        if is_paper:
            pos = self.paper_positions[symbol]
        else:
            pos = self.positions[symbol]
            
        # Get current price
        if symbol not in self.data_feed:
            return
            
        df = self.data_feed[symbol]
        if current_time not in df.index:
            return
            
        current_candle = df.loc[current_time]
        open_price = current_candle['open']
        current_price = current_candle['close']
        high_price = current_candle['high']
        low_price = current_candle['low']

        leverage = pos.get('leverage', self.config.LEVERAGE)
        liquidation_price = pos['entry_price'] * (1 - (1 / leverage) + 0.005)

        # 1. Gap-through liquidation. If a candle opens beyond liquidation, a stop
        # order cannot be assumed to have protected the position.
        if open_price <= liquidation_price:
            self._close_position(symbol, open_price, current_time, 'LIQUIDATION')
            return

        # 2. Hard stop. STOP_MARKET is not guaranteed at the stop price on gaps.
        if low_price <= pos['stop_loss']:
            exit_price = open_price if open_price <= pos['stop_loss'] else pos['stop_loss']
            self._close_position(symbol, exit_price, current_time, 'Stop Loss')
            return

        # 3. Smart break-even / trailing. Use the previous known high so one
        # OHLC candle cannot both activate and trigger a new trailing stop.
        smart_stop, smart_reason = self.smart_exit.get_current_exit_stop(pos)
        if smart_stop is not None and low_price <= smart_stop:
            exit_price = open_price if open_price <= smart_stop else smart_stop
            self._close_position(symbol, exit_price, current_time, smart_reason)
            return

        # 4. Time stop exits at observed close, matching a polling/market exit.
        holding_time = (current_time - pos['entry_time']).total_seconds() / 3600
        roe = ((current_price - pos['entry_price']) / pos['entry_price']) * leverage
        if holding_time >= self.smart_exit.time_stop_hours and roe < 0:
            self._close_position(symbol, current_price, current_time, f"Time Stop ({self.smart_exit.time_stop_hours}h)")
            return

        # Only update the trailing high after exit checks for this candle.
        if high_price > pos['highest_price']:
            pos['highest_price'] = high_price
    
    def _update_rolling_universe(self, current_time):
        """
        Dynamically update the Top 200 coin universe based on PREVIOUS 24h volume.
        Eliminates Look-Ahead Bias.
        """
        # print(f"[{current_time}] 🔄 Updating Rolling Universe (Top {self.TOP_N_COINS})...")
        volume_stats = {}
        start_time = current_time - timedelta(hours=24)
        
        for symbol, df in self.data_feed.items():
            # Slice last 24h
            # Efficient slicing on DatetimeIndex
            # We use slicing with variables which works if index is sorted
            
            # Check if symbol has data in this window
            try:
                # df.loc[start:end] includes endpoints
                # We typically rely on 15m candles. 
                # Optimization: Check if last timestamp < start_time (coin dead) or first > current (not listed yet)
                if df.index[-1] < start_time or df.index[0] > current_time:
                    continue
                
                slice_24h = df.loc[start_time:current_time]
                
                if slice_24h.empty:
                    continue
                    
                # Calculate metric: Sum of (Close * Volume)
                # This is approx 24h USD volume
                vol_usd = (slice_24h['close'] * slice_24h['volume']).sum()
                
                if vol_usd > 0:
                    volume_stats[symbol] = vol_usd
            except Exception as e:
                continue
                
        # Sort Top N
        sorted_coins = sorted(volume_stats.items(), key=lambda x: x[1], reverse=True)
        top_candidates = [coin for coin, vol in sorted_coins[:self.TOP_N_COINS]]
        
        self.active_universe = set(top_candidates)
        
        # Update Ranking Map for Dynamic Leverage
        self.coin_volume_ranking = {coin: rank+1 for rank, (coin, vol) in enumerate(sorted_coins)}
        
        self.last_universe_update = current_time.date()
        self.last_universe_update = current_time.date()
        print(f"[{current_time}] ✅ Universe Updated: {len(self.active_universe)} coins active.")

    # def _rank_coins_by_volume(self): 
    # REMOVED due to Look-Ahead Bias
    #     pass
        
    def _scan_market(self, current_time):
        candidates = []
        # 1. Circuit Breaker Check
        is_paused = False
        if self.trend_detector.should_pause_trading(self.balance, self.peak_balance):
            # Check if we can recover
            if not self.trend_detector.check_recovery():
                is_paused = True
                # print(f"[{current_time}] 🛑 Trading Paused: Circuit Breaker Active (Paper Trading Mode)")
        
        # 2. Market Regime Filter (BTC Trend)
        # DISABLED PER USER REQUEST (2025-12-07) - Backtest showed removing this yields 7x profit
        btc_trend_ok = True
        '''
        btc_key = 'BTCUSDTUSDT' if 'BTCUSDTUSDT' in self.data_feed else 'BTCUSDT'
        
        if btc_key in self.data_feed:
            btc_df = self.data_feed[btc_key]
            # Get BTC data up to current time
            btc_slice = btc_df.loc[:current_time]
            if len(btc_slice) > 200:
                btc_close = btc_slice['close'].iloc[-1]
                btc_ema200 = ta.ema(btc_slice['close'], length=200).iloc[-1]
                if btc_close < btc_ema200:
                    btc_trend_ok = False
                    # print(f"[{current_time}] 🐻 Market Bearish (BTC < EMA200). Skipping Longs.")
        '''
        
        if not btc_trend_ok:
            return # Skip all trades if Market is Bearish
            
        # DYNAMIC UNIVERSE: Update if needed (Daily at 00:00 UTC)
        # Check if we need effective update
        # If timestamp is 00:00 -> Update
        # Or if it's the very first run (self.last_universe_update is None)
        # Note: current_time is Timestamp object
        if self.last_universe_update is None or current_time.date() > self.last_universe_update:
             self._update_rolling_universe(current_time)
            
        # Scan all symbols
        for symbol, df in self.data_feed.items():
            # Skip if not in Rolling Universe (Top 200)
            if symbol not in self.active_universe:
                continue
                
            # Skip if already in position (Real or Paper)
            if symbol in self.positions or symbol in self.paper_positions:
                continue
            
            # Check for data existence...
            if current_time not in df.index:
                continue

            row_loc = df.index.get_loc(current_time)
            
            if len(df.index) > 1:
                candle_seconds = (df.index[1] - df.index[0]).total_seconds()
            else:
                continue

            lookback_24h = max(1, int(86400 / candle_seconds))
            if row_loc < lookback_24h:
                continue
            
            current_close = df.iloc[row_loc]['close']
            prev_close = df.iloc[row_loc - lookback_24h]['close']
            
            if prev_close == 0:
                continue
                
            change_pct = (current_close - prev_close) / prev_close * 100
                
            # QUALITY FILTER 1: Volume Check
            volume_24h_slice = df.iloc[row_loc - lookback_24h + 1 : row_loc + 1]
            volume_24h_usd = (volume_24h_slice['close'] * volume_24h_slice['volume']).sum()
            
            # === QUALITY FILTER MODULE CHECK ===
            is_good, reason = self.quality_filter.check_quality(symbol, volume_24h_slice, volume_24h_usd)
            if not is_good:
                continue
            
            # QUALITY FILTER 2: Top 200 Ranking Check
            # Handled by loop condition (symbol in active_universe)
            
            # Filter by 24h change threshold
            if self.config.CHANGE_THRESHOLD_MIN <= change_pct <= self.config.CHANGE_THRESHOLD_MAX:
                candidates.append({
                    'symbol': symbol,
                    'change': change_pct,
                    'df': df,
                    'row_loc': row_loc,
                    'volume_24h': volume_24h_usd
                    })
                    

                
        # Sort by Change % (Top Gainers)
        candidates.sort(key=lambda x: x['change'], reverse=True)
        
        # Take top N
        top_candidates = candidates[:self.config.TOP_GAINER_COUNT]
        
        # Check Strategy for these candidates
        for cand in top_candidates:
            symbol = cand['symbol']
            df = cand['df']
            row_loc = cand['row_loc']
            
            # Get recent history for strategy (50 candles)
            # FIX: We need 15m candles for strategy, but df is 1m resolution (in MinuteFreq mode)
            # We must resample on the fly to simulate "looking at 15m chart while trading 1m"
            
            # 1. Determine if we need resampling
            time_diff = (df.index[1] - df.index[0]).total_seconds()
            is_1m_data = time_diff < 300 # Assume < 5min means 1m data
            
            # ONLY resample if Config says so (e.g. 15m) AND data is 1m
            # If Config is 1m, we want RAW 1m data (No Resampling)
            if is_1m_data and self.config.TIMEFRAME != '1m':
                # Take last ~1000 minutes to ensure we have enough 15m candles (need 50 15m = 750m)
                # Slice logic: Get data up to current row_loc inclusive
                lookback_mins = 1500 # Safe margin
                start_resample_loc = max(0, row_loc - lookback_mins)
                
                # Create slice copy
                df_slice_1m = df.iloc[start_resample_loc : row_loc + 1].copy()
                
                # Resample to 15m
                agg_dict = {
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }
                
                # We want the last bin to represent the "developing" candle if incomplete
                # standard resample aligns to 15m boundaries (00, 15, 30, 45)
                # This perfectly mimics developing candle logic
                history_df = df_slice_1m.resample('15min').agg(agg_dict).dropna()
                
                # Check if we have enough 15m history
                if len(history_df) < 50:
                    continue
                    
                # Take last 50 for strategy
                history_slice = history_df.tail(50)
            else:
                # Already 15m data (Standard Backtest)
                # FIX (Indicator Warmup): Live bot uses 300 candles. Backtest used 50.
                # ADX/EMA needs sufficient warmup. Raising to 300 (start >= 0).
                start_loc = max(0, row_loc - 300)
                history_slice = df.iloc[start_loc : row_loc + 1]
            
            signal = self.strategy.check_signal(symbol, history_slice)
            if signal and 'reason' in signal:
                 # Limit debug prints to once per day or specifically 00:00
                 if current_time.hour == 0 and current_time.minute == 0:
                     print(f"[{current_time}] {symbol} Rejected: {signal['reason']}")
            
            # MATCH MAIN.PY LOGIC: Handle new rejection format
            if signal and signal.get('side') == 'LONG':
                # FIX P0: Entry price should be NEXT K-line's open, not current close
                # In real trading, we see the signal after current K-line closes,
                # so we can only enter at next K-line's open price
                
                # Check if next K-line exists
                if row_loc + 1 >= len(df):
                    continue  # No next K-line, skip this signal
                
                next_open_price = df.iloc[row_loc + 1]['open']
                next_time = df.iloc[row_loc + 1].name  # Timestamp of next K-line
                
                # Store signal for execution at next time step
                # We'll open the position at the BEGINNING of the next iteration
                # For now, mark this as a pending signal
                # APP pending signal
                self.pending_signals.append({
                    'symbol': symbol,
                    'entry_price': next_open_price,
                    'entry_time': next_time,
                    'metrics': signal.get('metrics', {}),
                    'history_slice': history_slice.copy(),
                    'is_paper_trade': is_paused # Pass the paused status to the signal
                })
                
                # Check if we have filled all slots
                # Current positions + Pending signals
                if len(self.positions) + len(self.pending_signals) >= self.config.MAX_OPEN_POSITIONS:
                    break

    def _open_position(self, symbol, price, timestamp, history_slice, metrics=None, is_paper_trade=False):
        # DYNAMIC LEVERAGE: Tier-based leverage assignment
        # Top 50 coins: 50x
        # Top 51-200 coins: 20x
        # Others (shouldn't reach here due to filter, but fallback): 10x
        
        coin_rank = self.coin_volume_ranking.get(symbol, 999)
        
        if coin_rank <= 50:
            leverage = 50  # Mainstream coins
        elif coin_rank <= 200:
            leverage = 20  # Mid-tier coins
        else:
            leverage = 10  # Small coins (fallback)
            
        # Limit by Exchange Max Leverage (from Snapshot)
        # Note: 'symbol' in backtest is usually 'BTCUSDT', but map might have 'BTC/USDT:USDT'
        # We need to try matching
        max_lev = 20 # Default safe fallback
        
        # Try direct match
        if symbol in self.leverage_limits:
            max_lev = self.leverage_limits[symbol]
        else:
            # Try formatting
            alt_key = f"{symbol}/USDT:USDT" # Standard CCXT format
            if alt_key in self.leverage_limits:
                max_lev = self.leverage_limits[alt_key]
            else:
                # Try simple key without suffix
                # Snapshot keys: 'BTC/USDT:USDT'
                # Backtest keys: 'BTCUSDT' (from filename)
                # Need to map 'BTCUSDT' -> 'BTC/USDT:USDT'
                # Let's iterate if needed or build a map, but simpler:
                # Basic mapping: BTCUSDT -> BTC/USDT:USDT is unlikely to match string perfectly 
                # because base currency length varies. 1000FLOKIUSDT -> 1000FLOKI
                # Let's just default to 20 if not found, or trust the strategy if it's a major pair.
                
                # Check if it's a known big coin (Top 50 usually safe for 50x except outliers)
                if coin_rank <= 50: 
                     max_lev = 50 # Assume okay if not in map
        
        if max_lev:
            leverage = min(leverage, max_lev)
        
        # Update risk manager leverage for this trade
        self.risk_manager.config.LEVERAGE = leverage
        
        # OPT 2: ATR-based dynamic stop-loss (Using Shared Risk Manager)
        # Verify we have enough history
        stop_loss = 0
        if history_slice is not None and len(history_slice) >= 14:
             stop_loss = self.risk_manager.calculate_stop_loss(history_slice, price, side='LONG')
        else:
             # Fallback
             stop_loss = price * 0.986 # 1.4% Fixed
             
        # P1 FIX: Add slippage (0.05% - more realistic for small orders on liquid pairs)
        slippage = 0.0005  # 0.05% (reduced from 0.1%)
        entry_price_with_slippage = price * (1 + slippage)
        
        # Recalculate Stop Loss based on Slippage Entry? 
        # Live Bot calculates SL based on 'price' (Close of candle).
        # We should keep SL level absolute.
        # But wait, stop_loss from manager is a PRICE level.
        # If entry slips up, risk increases slightly.
        # Position sizing handles the risk based on (entry - sl). -> That comes next.

        
        # Use risk manager for size
        # For paper trade, use hypothetical balance (e.g. current balance)
        quantity = self.risk_manager.calculate_position_size(self.balance, entry_price_with_slippage, stop_loss)
        
        # Check margin usage
        margin_used = (entry_price_with_slippage * quantity) / leverage
        
        if quantity <= 0:
            return

        # Deduct Fee (0.05% Taker) - ONLY FOR REAL TRADES
        if not is_paper_trade:
            notional = price * quantity
            fee = notional * 0.0005
            self.balance -= fee
        
        position_data = {
            'entry_price': entry_price_with_slippage,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'highest_price': entry_price_with_slippage,
            'entry_time': timestamp,
            'leverage': leverage,
            'metrics': metrics or {},
            'is_paper': is_paper_trade
        }
        
        if is_paper_trade:
            self.paper_positions[symbol] = position_data
            print(f"[{timestamp}] 📝 OPEN PAPER LONG {symbol} @ {entry_price_with_slippage:.4f}")
        else:
            self.positions[symbol] = position_data
            print(f"[{timestamp}] OPEN LONG {symbol} @ {entry_price_with_slippage:.4f} | SL: {stop_loss:.4f} (-0.75%/-15%ROE) | Size: {quantity:.2f}")

    def _close_position(self, symbol, exit_price, timestamp, reason):
        # Check if it's a real or paper position
        if symbol in self.positions:
            pos = self.positions[symbol]
            is_paper = False
        elif hasattr(self, 'paper_positions') and symbol in self.paper_positions:
            pos = self.paper_positions[symbol]
            is_paper = True
        else:
            return # Position not found
            
        # P1 FIX: Add exit slippage (0.05% worse price on exit)
        slippage = 0.0005  # 0.05% (reduced from 0.1%)
        exit_price_with_slippage = exit_price * (1 - slippage)
        
        # PnL
        pnl = (exit_price_with_slippage - pos['entry_price']) * pos['quantity']
        
        # Fee
        notional = exit_price_with_slippage * pos['quantity']
        fee = notional * 0.0005
        
        net_pnl = pnl - fee
        
        if not is_paper:
            self.balance += net_pnl
            
            # Update Peak Balance
            if self.balance > self.peak_balance:
                self.peak_balance = self.balance
                
            trade_record = {
                'symbol': symbol,
                'entry_price': pos['entry_price'],
                'exit_price': exit_price_with_slippage,
                'entry_time': pos['entry_time'],
                'exit_time': timestamp,
                'pnl': net_pnl,
                'balance_after': self.balance,  # Track balance after this trade
                'reason': reason,
                'duration': timestamp - pos['entry_time']
            }
            # Add metrics to trade record
            if 'metrics' in pos:
                trade_record.update(pos['metrics'])
                
            self.trades.append(trade_record)
            print(f"[{timestamp}] CLOSE {symbol} @ {exit_price:.4f} | PnL: ${net_pnl:.2f} | Reason: {reason}")
            
            del self.positions[symbol]
            
        else:
            # Paper Trade Logic
            print(f"[{timestamp}] 📝 CLOSE PAPER {symbol} | PnL: ${net_pnl:.2f} | Reason: {reason}")
            del self.paper_positions[symbol]
            
        # Feed result to Trend Detector (BOTH Real and Paper)
        # This allows the detector to see if "virtual" trades are winning
        self.trend_detector.add_trade_result(symbol, net_pnl, timestamp)

    def _generate_report(self, days=None):
        print("\n" + "=" * 40)
        title = f"REALISTIC BACKTEST RESULTS ({days} Days)" if days else "REALISTIC BACKTEST RESULTS (Full)"
        print(title)
        print("=" * 40)
        print(f"Final Balance: ${self.balance:.2f}")
        total_return = ((self.balance - self.initial_balance)/self.initial_balance)*100
        print(f"Total Return: {total_return:.2f}%")
        print(f"Total Trades: {len(self.trades)}")
        
        if self.trades:
            wins = [t for t in self.trades if t['pnl'] > 0]
            losses = [t for t in self.trades if t['pnl'] <= 0]
            winning_trades = len(wins)
            losing_trades = len(losses)
            win_rate = winning_trades / len(self.trades) * 100
            
            print(f"Winning Trades: {winning_trades}")
            print(f"Losing Trades: {losing_trades}")
            print(f"Win Rate: {win_rate:.2f}%")
            
            avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
            avg_loss = np.mean([t['pnl'] for t in losses]) if losses else 0
            profit_factor = abs(sum([t['pnl'] for t in wins]) / sum([t['pnl'] for t in losses])) if losses else float('inf')
            
            print(f"Avg Win: ${avg_win:.2f}")
            print(f"Avg Loss: ${avg_loss:.2f}")
            print(f"Profit Factor: {profit_factor:.2f}")

            # New Metrics
            max_profit_trade = max(self.trades, key=lambda x: x['pnl'])
            max_loss_trade = min(self.trades, key=lambda x: x['pnl'])
            
            print(f"Max Profit Trade: ${max_profit_trade['pnl']:.2f} ({max_profit_trade['symbol']})")
            print(f"Max Loss Trade: ${max_loss_trade['pnl']:.2f} ({max_loss_trade['symbol']})")
            
            max_duration = max(self.trades, key=lambda x: x['duration'])['duration']
            min_duration = min(self.trades, key=lambda x: x['duration'])['duration']
            
            print(f"Max Holding Time: {max_duration}")
            print(f"Min Holding Time: {min_duration}")
            
            # Save trades to CSV
            filename = f"backtest_trades_{days}d.csv" if days else "backtest_trades.csv"
            pd.DataFrame(self.trades).to_csv(filename)
            print(f"Trades saved to {filename}")
