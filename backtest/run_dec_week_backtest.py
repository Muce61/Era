import sys
from pathlib import Path
import pandas as pd
from datetime import datetime
import pytz

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

class DecWeekBacktestEngine(RealBacktestEngine):
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        
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
                
                # Check file modification time to prioritize recently updated ones? 
                # No, just load them all.
                
                # OPTIMIZATION: Read only needed columns
                # timestamp is index
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
                
                if len(df_15m) > 100: 
                    self.data_feed[symbol] = df_15m
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"Successfully loaded {len(self.data_feed)} symbols (Resampled to 15m).")

def main():
    print("="*60)
    print("Running Dec Week Backtest (Dec 1 - Dec 8, 2025)")
    print("Data: /Users/muce/1m_data/new_backtest_data_1year_1m")
    
    # Define Time Range (UTC)
    # Beijing: 2025-12-01 00:00 -> UTC: 2025-11-30 16:00
    # Beijing: 2025-12-08 17:00 -> UTC: 2025-12-08 09:00
    
    start_date = "2025-11-30 16:00:00"
    end_date = "2025-12-08 09:00:00"
    
    print(f"Start Date (UTC): {start_date}")
    print(f"End Date (UTC):   {end_date}")
    print("="*60)
    
    engine = DecWeekBacktestEngine(initial_balance=100)
    engine.run(start_date=start_date, end_date=end_date, days=None) 

if __name__ == "__main__":
    main()
