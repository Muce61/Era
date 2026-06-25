import sys
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
import pytz

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from backtest.real_engine import RealBacktestEngine

class Last3MonthsBacktestEngine1m(RealBacktestEngine):
    def load_data(self):
        """
        Load data from the 1-year 1m dataset (updated incrementally).
        NO RESAMPLING - Uses raw 1m data.
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        end_date = pd.Timestamp("2025-12-12 20:00:00", tz='UTC')
        start_date = pd.Timestamp("2025-09-13 05:30:00", tz='UTC')
        warmup_start = start_date - pd.Timedelta(days=3)
        
        print(f"Loading raw 1m data for backtest period: {start_date} to {end_date}...")
        print(f"Including warmup history from: {warmup_start}")
        
        if not data_dir.exists():
             print(f"Error: Data directory {data_dir} not found.")
             return

        files = list(data_dir.glob("*.csv"))
        
        count = 0
        for file_path in files:
            try:
                symbol = file_path.stem 
                # Parse Dates Robustly
                try:
                    df_1m = pd.read_csv(file_path, on_bad_lines='skip')
                    if 'timestamp' not in df_1m.columns:
                        continue
                        
                    df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'], errors='coerce')
                    df_1m = df_1m.dropna(subset=['timestamp'])
                    df_1m.set_index('timestamp', inplace=True)
                    df_1m.sort_index(inplace=True)
                    df_1m = df_1m[~df_1m.index.duplicated(keep='last')]
                except Exception as e:
                    print(f"CSV Read Error {file_path.name}: {e}")
                    continue
                
                # Check timezone
                if df_1m.index.tz is None:
                    df_1m.index = df_1m.index.tz_localize('UTC')
                else:
                    df_1m.index = df_1m.index.tz_convert('UTC')
                
                # Filter by Date Range
                # Optimization: Check if file even overlaps with range before heavy operations
                if df_1m.index[-1] < warmup_start or df_1m.index[0] > end_date:
                    continue

                mask = (df_1m.index >= warmup_start) & (df_1m.index <= end_date)
                df_subset = df_1m.loc[mask].copy()
                
                if not df_subset.empty:
                    df_subset.columns = [c.lower() for c in df_subset.columns]
                    required_cols = ['open', 'high', 'low', 'close', 'volume']
                    if any(col not in df_subset.columns for col in required_cols):
                        continue
                    
                    self.data_feed[symbol] = df_subset[required_cols]
                    count += 1
                    
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
                
        print(f"Loaded {count} symbols with raw 1m data in range.")

def main():
    end_date_str = "2025-12-12 20:00:00"
    start_date_str = "2025-09-13 05:30:00"
    
    print(f"Starting 3-Month Backtest (1m Timeframe): {start_date_str} -> {end_date_str} (UTC)")
    print("This might take a while due to large dataset processing...")
    
    # Run Engine
    engine = Last3MonthsBacktestEngine1m(initial_balance=1000)
    
    # Use raw 1m execution data while generating strategy signals on 15m candles.
    engine.config.TIMEFRAME = '15m'
    
    # Force alignment parameters just in case
    engine.config.TOP_GAINER_COUNT = 50 # Match 'Strict Logic' update
    
    engine.run(start_date=start_date_str, end_date=end_date_str, days=None)

if __name__ == "__main__":
    main()
