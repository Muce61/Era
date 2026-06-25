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

class Last3DaysBacktestEngine1m(RealBacktestEngine):
    def load_data(self):
        """
        Load data from the 1-year 1m dataset (updated incrementally).
        NO RESAMPLING - Uses raw 1m data.
        """
        data_dir = Path("E:/ALIXZ/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        # Target Period: 3 Days Back from 2025-12-13 04:00 Beijing
        # End: 2025-12-12 20:00:00 UTC
        # Start: 2025-12-09 20:00:00 UTC
        end_date = pd.Timestamp("2025-12-12 20:00:00", tz='UTC')
        start_date = end_date - pd.Timedelta(days=3)
        
        print(f"Loading 1m data (Raw) for period: {start_date} to {end_date}...")
        
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
                if df_1m.index[-1] < start_date or df_1m.index[0] > end_date:
                    continue

                mask = (df_1m.index >= start_date) & (df_1m.index <= end_date)
                df_subset = df_1m.loc[mask].copy()
                
                if not df_subset.empty:
                    # FIX: Resample 1m to 15m to match Live Bot TIMEFRAME
                    agg_dict = {
                        'open': 'first',
                        'high': 'max',
                        'low': 'min',
                        'close': 'last',
                        'volume': 'sum'
                    }
                    # Handle capitalized columns if needed (engine standardizes to lower, but raw might be different)
                    final_agg = {}
                    available_cols = df_subset.columns.tolist()
                    for col, func in agg_dict.items():
                        if col in available_cols:
                            final_agg[col] = func
                        elif col.capitalize() in available_cols:
                            final_agg[col.capitalize()] = func
                            
                    df_15m = df_subset.resample('15min').agg(final_agg).dropna()
                    df_15m.columns = [c.lower() for c in df_15m.columns]
                    
                    self.data_feed[symbol] = df_15m
                    count += 1
                    
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
                
        print(f"Loaded {count} symbols with 1m data in range.")

def main():
    end_date_str = "2025-12-12 20:00:00"
    # 3 days prior
    start_date_str = "2025-12-09 20:00:00"
    
    print(f"Starting 3-Day Backtest (1m Timeframe): {start_date_str} -> {end_date_str} (UTC)")
    
    # Run Engine
    engine = Last3DaysBacktestEngine1m(initial_balance=1000)
    
    # Hack config to use 15m (Enable Resampling for Signal)
    engine.config.TIMEFRAME = '15m'
    
    # Force alignment parameters just in case
    engine.config.TOP_GAINER_COUNT = 50 
    
    engine.run(start_date=start_date_str, end_date=end_date_str, days=None)

if __name__ == "__main__":
    main()
