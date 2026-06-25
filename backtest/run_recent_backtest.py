import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

class RecentBacktestEngine(RealBacktestEngine):
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        # Use standard config or override if needed
        # Ensuring we use the same logic as "Real" engine which mimics live trading
        
    def load_data(self):
        """
        Load from recent 1m data directory and resample to 15m
        """
        data_dir = Path("/Users/muce/1m_data/recent_backtest_data")
        self.data_feed = {}
        
        print(f"Loading data from {data_dir}...")
        if not data_dir.exists():
            print(f"Error: Data directory {data_dir} does not exist!")
            return

        files = list(data_dir.glob("*.csv"))
        print(f"Found {len(files)} CSV files.")
        
        for file_path in files:
            try:
                symbol = file_path.stem 
                
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
                
                # We might have very few candles since it's only 17 hours (17 * 4 = 68 candles max)
                # So we lower the minimum requirement
                if len(df_15m) > 10: 
                    self.data_feed[symbol] = df_15m
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"Successfully loaded {len(self.data_feed)} symbols (Resampled to 15m).")

def main():
    print("="*60)
    print("Running Backtest for Nov 28 - Dec 5 (UTC+8)")
    print("Data: /Users/muce/1m_data/recent_backtest_data")
    print("="*60)
    
    engine = RecentBacktestEngine(initial_balance=100)
    # Run for 8 days to cover Nov 28 - Dec 5
    engine.run(days=8) 

if __name__ == "__main__":
    main()
