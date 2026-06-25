import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from strategy.momentum import MomentumStrategy
from risk.manager import RiskManager
from config.settings import Config

class HybridBacktestEngine:
    """
    Hybrid Backtest Engine:
    - Uses 15m K-lines for signal generation
    - Uses 1m K-lines for precise stop-loss/take-profit execution
    - 90% position size
    """
    def __init__(self, initial_balance=100):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions = {}
        self.trades = []
        self.pending_signal = None
        self.strategy = MomentumStrategy()
        self.risk_manager = RiskManager()
        self.config = Config()
        
        # Override config - High frequency configuration (10×10% 50x leverage)
        self.config.MAX_OPEN_POSITIONS = 10     # 10 concurrent trades for maximum frequency
        self.config.LEVERAGE = 50               # 50x leverage for higher returns
        self.risk_manager.config.LEVERAGE = 50
        self.config.TRADE_MARGIN_PERCENT = 0.10 # 10% position size (10 slots × 10% = 100%)
        self.risk_manager.config.TRADE_MARGIN_PERCENT = 0.10
        
        # Widen signal search to increase frequency (Aggressive)
        self.config.CHANGE_THRESHOLD_MIN = 2.0   # Min 2%
        self.config.CHANGE_THRESHOLD_MAX = 200.0 # Max 200% (Capture moonshots)
        self.config.TOP_GAINER_COUNT = 50        # Check top 50 candidates
        
    def load_data(self):
        """
        Load 15m, 30m, and 1m data for multi-timeframe strategy
        Filter to Top 100 symbols by volume
        """
        # Load 15m data for signals (30-day dataset - matched with 1m data)
        data_dir_15m = Path("/Users/muce/1m_data/backtest_data_legacy")
        all_files_15m = list(data_dir_15m.glob("*.csv"))
        
        print(f"Found {len(all_files_15m)} symbols total")
        print("Selecting Top 100 by volume...")
        
        # Calculate average volume for each symbol to rank
        symbol_volumes = []
        for file_path in all_files_15m:
            symbol = file_path.stem
            df = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
            avg_volume = df['volume'].mean()
            symbol_volumes.append((symbol, avg_volume, file_path))
        
        # Sort by volume and take top 100
        symbol_volumes.sort(key=lambda x: x[1], reverse=True)
        top_symbols = symbol_volumes[:100]
        
        print(f"Selected Top 100 symbols by volume")
        
        # Load 15m data
        self.data_15m = {}
        for symbol, _, file_path in top_symbols:
            df = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
            self.data_15m[symbol] = df
        
        print(f"Loaded {len(self.data_15m)} symbols (15m)")
        
        # Generate 30m data by resampling 15m
        self.data_30m = {}
        print("Generating 30m data...")
        for symbol, df in self.data_15m.items():
            df_30m = df.resample('30min').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            self.data_30m[symbol] = df_30m
        
        print(f"Generated {len(self.data_30m)} symbols (30m)")
        
        # Load 1m data for risk management
        data_dir_1m = Path("/Users/muce/1m_data/backtest_data_1m")
        self.data_1m = {}
        
        print("Loading 1m data...")
        for file_path in data_dir_1m.glob("*.csv"):
            symbol = file_path.stem
            df = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
            self.data_1m[symbol] = df
        
        print(f"Loaded {len(self.data_1m)} symbols (1m)")
        
    def run(self):
        if not hasattr(self, 'data_15m'):
            self.load_data()
        
        # Get all 15m timestamps (for signal scanning)
        all_timestamps_15m = set()
        for df in self.data_15m.values():
            all_timestamps_15m.update(df.index)
        
        sorted_timestamps_15m = sorted(all_timestamps_15m)
        
        # Start from index where we have enough history
        lookback_24h = 96  # 24h in 15m candles
        min_history = 50
        start_index = max(lookback_24h, min_history)
        
        print(f"Starting hybrid backtest (Multi-Timeframe)...")
        print(f"Signal: 15m + 30m K-lines")
        print(f"Risk Management: 1m K-lines")
        print(f"Position Size: 30%")
        print(f"Stop-Loss: ATR × 2.5")
        print(f"Leverage: 20x\n")
        
        for i in range(start_index, len(sorted_timestamps_15m)):
            current_time_15m = sorted_timestamps_15m[i]
            
            # 1. Check for new signals (using 15m and 30m data)
            if len(self.positions) < self.config.MAX_OPEN_POSITIONS and not self.pending_signal:
                # Try 15m signals first
                self._scan_market_15m(current_time_15m)
                
                # If no 15m signal, try 30m signals
                if not self.pending_signal:
                    self._scan_market_30m(current_time_15m)
            
            # 2. Manage positions using 1m data
            # For each 15m candle, check all 1m candles within it
            if len(self.positions) > 0:
                next_time_15m = sorted_timestamps_15m[i+1] if i+1 < len(sorted_timestamps_15m) else current_time_15m + timedelta(minutes=15)
                self._manage_positions_1m(current_time_15m, next_time_15m)
            
            # 3. Execute pending signals at next 15m open
            if self.pending_signal and i+1 < len(sorted_timestamps_15m):
                next_time_15m = sorted_timestamps_15m[i+1]
                if self.pending_signal['entry_time'] == next_time_15m:
                    self._execute_pending_signal()
            
            if i % 100 == 0:
                print(f"Processing {current_time_15m}... Balance: ${self.balance:.2f}")
        
        self._generate_report()
    
    def _scan_market_15m(self, current_time):
        """
        Scan market using 15m data for signal generation
        """
        candidates = []
        time_24h_ago = current_time - timedelta(hours=24)
        
        for symbol, df in self.data_15m.items():
            if current_time not in df.index:
                continue
            
            try:
                row_loc = df.index.get_loc(current_time)
                if row_loc < 96:
                    continue
                
                # Use previous close for 24h change
                previous_close = df.iloc[row_loc - 1]['close']
                price_24h_ago = df.iloc[row_loc - 96]['close']
                change_pct = ((previous_close - price_24h_ago) / price_24h_ago) * 100
                
                # Filter 5-20%
                if self.config.CHANGE_THRESHOLD_MIN <= change_pct <= self.config.CHANGE_THRESHOLD_MAX:
                    candidates.append({
                        'symbol': symbol,
                        'change': change_pct,
                        'df': df,
                        'row_loc': row_loc
                    })
            except Exception:
                continue
        
        # Sort by change
        candidates.sort(key=lambda x: x['change'], reverse=True)
        top_candidates = candidates[:self.config.TOP_GAINER_COUNT]
        
        # Check strategy signals
        for cand in top_candidates:
            symbol = cand['symbol']
            df = cand['df']
            row_loc = cand['row_loc']
            
            history_slice = df.iloc[row_loc - 50 : row_loc + 1]
            signal = self.strategy.check_signal(symbol, history_slice)
            
            if signal and signal['side'] == 'LONG':
                # CRITICAL: Filter high volatility coins first (prevent liquidation)
                import pandas_ta as ta
                atr = ta.atr(history_slice['high'], history_slice['low'], history_slice['close'], length=14).iloc[-1]
                atr_pct = atr / history_slice['close'].iloc[-1]
                
                if atr_pct > 0.10:  # Skip if ATR > 10% (extreme volatility only)
                    print(f"  ✗ {symbol} filtered: ATR too high ({atr_pct*100:.2f}%)")
                    continue
                
                # Apply enhanced filters
                from strategy.enhanced_filter import EnhancedSignalFilter
                
                passed, filter_results = EnhancedSignalFilter.apply_all_filters(
                    symbol, df, row_loc, current_time, self.data_15m
                )
                
                if not passed:
                    # Signal filtered out
                    print(f"  ✗ {symbol} filtered: {filter_results}")
                    continue
                
                # Get next 15m open price for entry
                if row_loc + 1 < len(df):
                    next_open_price = df.iloc[row_loc + 1]['open']
                    next_time = df.iloc[row_loc + 1].name
                    
                    self.pending_signal = {
                        'symbol': symbol,
                        'entry_price': next_open_price,
                        'entry_time': next_time,
                        'metrics': signal.get('metrics', {}),
                        'history_slice': history_slice,  # For ATR calculation
                        'filters': filter_results  # Store filter results
                    }
                    # print(f"  ✓ {symbol} passed all filters")
                    break
    
    def _execute_pending_signal(self):
        """
        Execute pending signal
        """
        if not self.pending_signal:
            return
        
        symbol = self.pending_signal['symbol']
        price = self.pending_signal['entry_price']
        timestamp = self.pending_signal['entry_time']
        metrics = self.pending_signal['metrics']
        history_slice = self.pending_signal.get('history_slice')  # For ATR calculation
        
        # Calculate stop loss with slippage and ATR
        leverage = self.config.LEVERAGE
        slippage = 0.0005  # 0.05%
        
        # Plan A: ATR-based stop with 2.5x multiplier
        if history_slice is not None and len(history_slice) >= 14:
            import pandas_ta as ta
            atr = ta.atr(history_slice['high'], history_slice['low'], history_slice['close'], length=14).iloc[-1]
            stop_distance = max(0.0075 * price, atr * 2.5)  # ATR × 2.5 (widened from 1.5)
            
            # CRITICAL: Cap stop loss at 1.4% for 50x leverage (liquidation at ~1.5%)
            # MUST be lower than liquidation to prevent false "zero liquidation" results
            max_stop_distance = 0.014 * price  # 1.4% hard cap (safe margin)
            stop_distance = min(stop_distance, max_stop_distance)
            
            stop_loss_pct = stop_distance / price
        else:
            stop_loss_pct = 0.0075  # Fallback
        
        entry_price_with_slippage = price * (1 + slippage)
        stop_loss = entry_price_with_slippage * (1 - stop_loss_pct)
        
        # Calculate position size
        quantity = self.risk_manager.calculate_position_size(self.balance, entry_price_with_slippage, stop_loss)
        
        if quantity <= 0:
            self.pending_signal = None
            return
        
        # Open position
        margin_used = (entry_price_with_slippage * quantity) / leverage
        fee = margin_used * 0.0005
        self.balance -= fee
        
        self.positions[symbol] = {
            'entry_price': entry_price_with_slippage,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'highest_price': entry_price_with_slippage,
            'entry_time': timestamp,
            'leverage': leverage,
            'metrics': metrics
        }
        
        print(f"[{timestamp}] OPEN {symbol} @ {entry_price_with_slippage:.4f} | SL: {stop_loss:.4f} | Size: {quantity:.2f}")
        
        self.pending_signal = None
    
    def _manage_positions_1m(self, start_time_15m, end_time_15m):
        """
        Manage positions using 1m data for precise execution
        """
        active_symbols = list(self.positions.keys())
        
        for symbol in active_symbols:
            pos = self.positions[symbol]
            df_1m = self.data_1m.get(symbol)
            
            if df_1m is None:
                continue
            
            # Get all 1m candles within this 15m period
            mask = (df_1m.index >= start_time_15m) & (df_1m.index < end_time_15m)
            candles_1m = df_1m[mask]
            
            # Check each 1m candle
            for timestamp, candle in candles_1m.iterrows():
                current_price = candle['close']
                high_price = candle['high']
                low_price = candle['low']
                
                # Update highest price
                pos['highest_price'] = max(pos['highest_price'], high_price)
                
                # Check stop loss FIRST (价格下跌时先触发止损)
                if low_price <= pos['stop_loss']:
                    self._close_position(symbol, pos['stop_loss'], timestamp, 'Stop Loss')
                    break
                
                # Check liquidation SECOND (只有跳空才会爆仓)
                liq_price = pos['entry_price'] * (1 - (1 / pos['leverage']) + 0.005)
                if low_price <= liq_price:
                    self._close_position(symbol, liq_price, timestamp, 'LIQUIDATION')
                    break
                
                # Balanced profit taking - protect gains while letting winners run
                current_roe = ((current_price - pos['entry_price']) / pos['entry_price']) * pos['leverage']
                
                # Move to breakeven earlier for safety
                if current_roe >= 0.15 and pos['stop_loss'] < pos['entry_price']:
                    # Move to breakeven at 15% ROE (vs 20% in extreme config)
                    pos['stop_loss'] = pos['entry_price'] * 1.002
                elif current_roe >= 0.25:
                    # Lock in 12% profit at 25% ROE
                    target_sl_roe = 0.12
                    new_sl_price = pos['entry_price'] * (1 + (target_sl_roe / pos['leverage']))
                    pos['stop_loss'] = max(pos['stop_loss'], new_sl_price)
                elif current_roe >= 0.40:
                    # Lock in 25% profit at 40% ROE
                    target_sl_roe = 0.25
                    new_sl_price = pos['entry_price'] * (1 + (target_sl_roe / pos['leverage']))
                    pos['stop_loss'] = max(pos['stop_loss'], new_sl_price)
                
                # ENABLED: Stagnation Exit - Free up slots for new opportunities
                time_held = timestamp - pos['entry_time']
                if time_held > timedelta(hours=24) and current_roe < 0.05:
                     self._close_position(symbol, current_price, timestamp, 'Stagnation Exit')
                     break
                
                # Check stepped trailing profit
                max_roe = ((pos['highest_price'] - pos['entry_price']) / pos['entry_price']) * pos['leverage']
                
                if max_roe >= 0.20:
                    bracket_floor = int(max_roe / 0.20) * 0.20
                    target_sl_roe = bracket_floor - 0.05
                    new_sl_price = pos['entry_price'] * (1 + (target_sl_roe / pos['leverage']))
                    
                    if new_sl_price > pos['stop_loss']:
                        pos['stop_loss'] = new_sl_price
                    
                    if low_price <= pos['stop_loss']:
                        self._close_position(symbol, pos['stop_loss'], timestamp, 'Trailing Stop')
                        break
    
    def _close_position(self, symbol, exit_price, timestamp, reason):
        pos = self.positions[symbol]
        
        # Apply exit slippage
        slippage = 0.0005
        exit_price_with_slippage = exit_price * (1 - slippage)
        
        # Calculate PnL
        pnl = (exit_price_with_slippage - pos['entry_price']) * pos['quantity']
        notional = exit_price_with_slippage * pos['quantity']
        fee = notional * 0.0005
        net_pnl = pnl - fee
        
        self.balance += net_pnl
        
        # Record trade
        trade_record = {
            'symbol': symbol,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price_with_slippage,
            'entry_time': pos['entry_time'],
            'exit_time': timestamp,
            'pnl': net_pnl,
            'reason': reason,
            'duration': timestamp - pos['entry_time']
        }
        
        if 'metrics' in pos:
            trade_record.update(pos['metrics'])
        
        self.trades.append(trade_record)
        
        print(f"[{timestamp}] CLOSE {symbol} @ {exit_price_with_slippage:.4f} | PnL: ${net_pnl:.2f} | {reason}")
        
        del self.positions[symbol]
    
    def _generate_report(self):
        print(f"\n{'='*60}")
        print("HYBRID BACKTEST RESULTS (15m Signal + 1m Risk Management)")
        print(f"{'='*60}")
        print(f"Final Balance: ${self.balance:.2f}")
        print(f"Total Return: {((self.balance - self.initial_balance) / self.initial_balance * 100):.2f}%")
        print(f"Total Trades: {len(self.trades)}")
        
        if self.trades:
            df_trades = pd.DataFrame(self.trades)
            wins = df_trades[df_trades['pnl'] > 0]
            losses = df_trades[df_trades['pnl'] <= 0]
            
            print(f"Winning Trades: {len(wins)}")
            print(f"Losing Trades: {len(losses)}")
            print(f"Win Rate: {len(wins)/len(df_trades)*100:.2f}%")
            
            if len(wins) > 0:
                print(f"Avg Win: ${wins['pnl'].mean():.2f}")
            if len(losses) > 0:
                print(f"Avg Loss: ${losses['pnl'].mean():.2f}")
            
            if len(wins) > 0 and len(losses) > 0:
                profit_factor = abs(wins['pnl'].sum() / losses['pnl'].sum())
                print(f"Profit Factor: {profit_factor:.2f}")
            
            df_trades.to_csv('backtest_trades_hybrid.csv', index=False)
            print(f"Trades saved to backtest_trades_hybrid.csv")
    def _scan_market_30m(self, current_time_15m):
        """
        Scan market using 30m data for signal generation
        """
        # Find corresponding 30m timestamp
        # 30m timestamps are at :00 and :30
        current_time_30m = current_time_15m.replace(minute=(current_time_15m.minute // 30) * 30)
        
        candidates = []
        
        for symbol, df in self.data_30m.items():
            if current_time_30m not in df.index:
                continue
            
            try:
                row_loc = df.index.get_loc(current_time_30m)
                if row_loc < 48:  # Need 24h history (48 x 30m candles)
                    continue
                
                # Use previous close for 24h change
                previous_close = df.iloc[row_loc - 1]['close']
                price_24h_ago = df.iloc[row_loc - 48]['close']
                change_pct = ((previous_close - price_24h_ago) / price_24h_ago) * 100
                
                # Filter 5-20%
                if self.config.CHANGE_THRESHOLD_MIN <= change_pct <= self.config.CHANGE_THRESHOLD_MAX:
                    candidates.append({
                        'symbol': symbol,
                        'change': change_pct,
                        'df': df,
                        'row_loc': row_loc
                    })
            except Exception:
                continue
        
        # Sort by change
        candidates.sort(key=lambda x: x['change'], reverse=True)
        top_candidates = candidates[:self.config.TOP_GAINER_COUNT]
        
        # Check strategy signals
        for cand in top_candidates:
            symbol = cand['symbol']
            df = cand['df']
            row_loc = cand['row_loc']
            
            history_slice = df.iloc[row_loc - 50 : row_loc + 1]
            signal = self.strategy.check_signal(symbol, history_slice)
            
            if signal and signal['side'] == 'LONG':
                # Apply enhanced filters (using 15m data for 1h trend check)
                from strategy.enhanced_filter import EnhancedSignalFilter
                
                passed, filter_results = EnhancedSignalFilter.apply_all_filters(
                    symbol, df, row_loc, current_time_30m, self.data_15m
                )
                
                if not passed:
                    continue
                
                # Get next 30m open price for entry
                # But we execute on 15m boundaries, so find next 15m timestamp
                if row_loc + 1 < len(df):
                    next_30m_open = df.iloc[row_loc + 1]['open']
                    next_30m_time = df.iloc[row_loc + 1].name
                    
                    # Find the corresponding 15m timestamp for execution
                    # Execution happens at the start of next 30m period
                    next_15m_time = next_30m_time
                    
                    self.pending_signal = {
                        'symbol': symbol,
                        'entry_price': next_30m_open,
                        'entry_time': next_15m_time,
                        'metrics': signal.get('metrics', {}),
                        'history_slice': history_slice,
                        'filters': filter_results,
                        'timeframe': '30m'  # Mark as 30m signal
                    }
                    # print(f"  ✓ {symbol} passed all filters (30m)")
                    break
