import sys
from pathlib import Path
import pandas as pd
from datetime import datetime
import pytz

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

class MinuteFreqBacktestEngine(RealBacktestEngine):
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        
    def load_data(self):
        """
        Load from main 1m data directory WITHOUT resampling
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        print(f"Loading 1m data from {data_dir}...")
        if not data_dir.exists():
             print(f"Error: Data directory {data_dir} does not exist!")
             return

        files = list(data_dir.glob("*.csv"))
        print(f"Found {len(files)} CSV files. Loading full 1m resolution...")
        
        for file_path in files:
            try:
                symbol = file_path.stem 
                # Load 1m data directly
                df_1m = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                df_1m.dropna(inplace=True)
                
                if len(df_1m) > 1000: 
                    self.data_feed[symbol] = df_1m
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"Successfully loaded {len(self.data_feed)} symbols (1m Frequency).")

def main():
    print("="*60)
    print("Running 1-Minute Frequency Backtest (Nov 2024 - Dec 2025)")
    print("Logic: Trade Checks every minute (High Frequency Simulation)")
    print("="*60)
    
    start_date = "2024-11-01 00:00:00"
    end_date = "2025-12-08 09:00:00"
    
    print(f"Start Date (UTC): {start_date}")
    print(f"End Date (UTC):   {end_date}")
    
    engine = MinuteFreqBacktestEngine(initial_balance=100)
    # WARNING: This will be slow due to 500k+ iterations
    engine.run(start_date=start_date, end_date=end_date, days=None) 

if __name__ == "__main__":
    main()
