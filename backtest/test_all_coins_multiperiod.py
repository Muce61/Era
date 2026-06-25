import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

class AllCoinsEngine(RealBacktestEngine):
    """
    Test with ALL 597 coins (no whitelist)
    Keep 20x leverage + partial TP strategy
    """
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        # Force 20x leverage
        self.config.LEVERAGE = 20
        self.risk_manager.config.LEVERAGE = 20
        self.config.CHANGE_THRESHOLD_MIN = 5.0
        self.config.CHANGE_THRESHOLD_MAX = 200.0
        self.config.TOP_GAINER_COUNT = 50
        
        print(f"⚙️  Leverage: 20x")
        print(f"💰 Partial TP: 15% (40%), 25% (30%), 40% (all)")
        print(f"📋 Coins: ALL 597 (no whitelist)")
    
    def _open_position(self, symbol, price, timestamp, history_slice, metrics=None):
        """
        Override to force 20x leverage for all positions.
        """
        # FORCE 20x leverage - no dynamic assignment
        leverage = 20
        self.risk_manager.config.LEVERAGE = 20
        
        # ATR-based stop-loss calculation
        if history_slice is not None and len(history_slice) >= 14:
            import pandas_ta as ta
            atr = ta.atr(history_slice['high'], history_slice['low'], history_slice['close'], length=14).iloc[-1]
            sl_distance = atr * 2.5
            # Cap for 20x leverage (liquidation at ~5%)
            max_stop_distance = price * 0.035  # 3.5% max stop for 20x
            sl_distance = min(sl_distance, max_stop_distance)
            stop_loss_pct = sl_distance / price
        else:
            # Safe default for 20x leverage
            stop_loss_pct = 0.035  # 3.5% = 70% ROE stop
        
        # Add slippage
        slippage = 0.0005
        entry_price_with_slippage = price * (1 + slippage)
        stop_loss = entry_price_with_slippage * (1 - stop_loss_pct)
        
        # Calculate position size
        quantity = self.risk_manager.calculate_position_size(self.balance, entry_price_with_slippage, stop_loss)
        
        if quantity <= 0:
            return
        
        # Deduct fee
        notional = price * quantity
        fee = notional * 0.0005
        self.balance -= fee
        
        # Store position
        self.positions[symbol] = {
            'entry_price': entry_price_with_slippage,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'highest_price': entry_price_with_slippage,
            'entry_time': timestamp,
            'leverage': leverage,
            'metrics': metrics or {}
        }
        
        print(f"[{timestamp}] OPEN LONG {symbol} @ {entry_price_with_slippage:.4f} | SL: {stop_loss:.4f} | Size: {quantity:.2f}")
        
    def load_data(self):
        """
        Load ALL coins from new data directory (no whitelist filter)
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        print(f"Loading ALL coins from {data_dir}...")
        
        if not data_dir.exists():
            print(f"Error: Data directory {data_dir} does not exist!")
            return

        files = list(data_dir.glob("*.csv"))
        loaded_count = 0
        
        for file_path in files:
            try:
                symbol = file_path.stem
                
                # NO WHITELIST FILTER - load all coins
                
                # Read CSV (1m data)
                df_1m = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                
                # Resample to 15m
                df_15m = df_1m.resample('15min').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                })
                
                df_15m.dropna(inplace=True)
                
                if len(df_15m) > 50:
                    self.data_feed[symbol] = df_15m
                    loaded_count += 1
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"✅ Loaded {loaded_count} coins (Resampled to 15m).")

def run_multi_period_backtest():
    """Run backtests for 30, 90, and 180 days"""
    import time
    
    periods = [
        (30, "1 Month"),
        (90, "3 Months"),
        (180, "6 Months")
    ]
    
    results = {}
    
    for days, label in periods:
        print("\n" + "="*60)
        print(f"BACKTEST: {label} ({days} days)")
        print("Strategy: All 597 Coins + 20x Leverage + Partial TP")
        print("="*60)
        
        start_time = time.time()
        
        engine = AllCoinsEngine(initial_balance=100)
        engine.run(days=days)
        
        elapsed = time.time() - start_time
        
        # Store results
        results[label] = {
            'days': days,
            'final_balance': engine.balance,
            'total_return': (engine.balance - 100) / 100 * 100,
            'total_trades': len(engine.trades),
            'elapsed_time': elapsed
        }
        
        print(f"\n⏱️  Backtest completed in {elapsed:.1f} seconds\n")
    
    # Print summary
    print("\n" + "="*60)
    print("MULTI-PERIOD BACKTEST SUMMARY")
    print("="*60)
    print(f"{'Period':<15} {'Return':<15} {'Trades':<10} {'Time':<10}")
    print("-"*60)
    for label, data in results.items():
        print(f"{label:<15} {data['total_return']:>+13.2f}% {data['total_trades']:>8} {data['elapsed_time']:>8.1f}s")
    print("="*60)

if __name__ == "__main__":
    run_multi_period_backtest()
