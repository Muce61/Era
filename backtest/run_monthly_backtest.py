import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

class MonthlyBacktestEngine(RealBacktestEngine):
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        # Use standard config matching live trading
        
    def load_data(self):
        """
        Load from main 1m data directory and resample to 15m
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
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
                
                if len(df_15m) > 50: 
                    self.data_feed[symbol] = df_15m
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"Successfully loaded {len(self.data_feed)} symbols (Resampled to 15m).")

def main():
    print("="*60)
    print("Running 30-Day Backtest (Most Recent Month)")
    print("Data: /Users/muce/1m_data/new_backtest_data_1year_1m")
    print("="*60)
    
    engine = MonthlyBacktestEngine(initial_balance=100)
    # Run for last 30 days
    engine.run(days=30) 

if __name__ == "__main__":
    main()
