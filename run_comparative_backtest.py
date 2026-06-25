import sys
from pathlib import Path
# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[0]))

from backtest.real_engine import RealBacktestEngine
import pandas as pd
import copy

class BacktestEngine30D(RealBacktestEngine):
    def load_data(self):
        """
        Override to load from the 1-year data directory
        """
        # Use the directory where fetch_1year_data.py is saving
        data_dir = Path("/Users/muce/1m_data/backtest_data_1year_1m")
        self.data_feed = {}
        
        print(f"Loading data from {data_dir}...")
        if not data_dir.exists():
            print(f"Error: Data directory {data_dir} does not exist!")
            return

        # Load all CSVs
        files = list(data_dir.glob("*.csv"))
        print(f"Found {len(files)} CSV files.")
        
        for file_path in files:
            try:
                # Symbol format: 1000BONKUSDTUSDT.csv -> 1000BONK/USDT
                symbol = file_path.stem 
                
                # Read CSV (1m data)
                df_1m = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                
                # Resample to 15m to match live strategy
                # Logic: Open=first, High=max, Low=min, Close=last, Volume=sum
                df_15m = df_1m.resample('15min').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                })
                
                # Drop incomplete or empty bins
                df_15m.dropna(inplace=True)
                
                # Only keep if we have enough data
                if len(df_15m) > 50:
                    self.data_feed[symbol] = df_15m
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"Successfully loaded {len(self.data_feed)} symbols (Resampled to 15m).")

def run_scenario(name, min_change, max_change):
    print("\n" + "="*60)
    print(f"Running Scenario: {name}")
    print(f"Filter: {min_change}% <= 24h Change <= {max_change}%")
    print("="*60)
    
    engine = BacktestEngine30D(initial_balance=100)
    
    # Override config thresholds
    engine.config.CHANGE_THRESHOLD_MIN = min_change
    engine.config.CHANGE_THRESHOLD_MAX = max_change
    
    # Run for last 30 days
    engine.run(days=30)
    
    return engine

def main():
    # Scenario 1: Restricted (Current Logic)
    # 5% - 20% (User requested this specific range for comparison)
    engine_restricted = run_scenario("Restricted (5% - 20%)", 5.0, 20.0)
    
    # Scenario 2: Unrestricted
    # -100% to 10000% (Effectively no filter)
    engine_unrestricted = run_scenario("Unrestricted (All Gainers)", -100.0, 10000.0)
    
    # Compare Results
    print("\n" + "="*60)
    print("COMPARISON RESULTS")
    print("="*60)
    
    def get_stats(engine):
        final_bal = engine.balance
        return_pct = ((final_bal - 100) / 100) * 100
        trades = len(engine.trades)
        wins = len([t for t in engine.trades if t['pnl'] > 0])
        win_rate = (wins / trades * 100) if trades > 0 else 0
        return final_bal, return_pct, trades, win_rate

    bal1, ret1, trades1, wr1 = get_stats(engine_restricted)
    bal2, ret2, trades2, wr2 = get_stats(engine_unrestricted)
    
    print(f"{'Metric':<20} | {'Restricted (5-20%)':<20} | {'Unrestricted':<20}")
    print("-" * 66)
    print(f"{'Final Balance':<20} | ${bal1:<19.2f} | ${bal2:<19.2f}")
    print(f"{'Total Return':<20} | {ret1:<19.2f}% | {ret2:<19.2f}%")
    print(f"{'Total Trades':<20} | {trades1:<20} | {trades2:<20}")
    print(f"{'Win Rate':<20} | {wr1:<19.2f}% | {wr2:<19.2f}%")

if __name__ == "__main__":
    main()
