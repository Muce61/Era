import sys
import os
from pathlib import Path
from datetime import datetime
import pytz
import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from backtest.real_engine import RealBacktestEngine

class Last3DaysBacktestEngine(RealBacktestEngine):
    def load_data(self):
        """
        Load data from the 1-year 1m dataset (updated incrementally).
        Filter for the last 3 days only.
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        # Target Period: 
        # End: 2025-12-11 13:30 Beijing (05:30 UTC)
        # Start: 2025-12-08 13:30 Beijing (05:30 UTC) [3 Days]
        
        start_date = pd.Timestamp("2025-12-08 05:30:00", tz='UTC')
        end_date = pd.Timestamp("2025-12-11 05:30:00", tz='UTC')
        
        print(f"Loading data for period: {start_date} to {end_date}...")
        
        files = list(data_dir.glob("*.csv"))
        # import pandas as pd # Removed to avoid shadowing
        
        count = 0
        for file_path in files:
            try:
                symbol = file_path.stem 
                # Parse Dates
                df_1m = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                
                # Check timezone
                if df_1m.index.tz is None:
                    df_1m.index = df_1m.index.tz_localize('UTC')
                
                # Filter by Date Range
                mask = (df_1m.index >= start_date) & (df_1m.index <= end_date)
                df_subset = df_1m.loc[mask].copy()
                
                if not df_subset.empty:
                    # Fix: Resample to 15m to match Live Bot
                    agg_dict = {
                        'open': 'first',
                        'high': 'max',
                        'low': 'min',
                        'close': 'last',
                        'volume': 'sum'
                    }
                    # Map columns case-insensitively
                    available_cols = df_subset.columns.tolist()
                    final_agg = {}
                    for col, func in agg_dict.items():
                        if col in available_cols:
                            final_agg[col] = func
                        elif col.capitalize() in available_cols:
                            final_agg[col.capitalize()] = func
                            
                    df_resampled = df_subset.resample('15min').agg(final_agg).dropna()
                    df_resampled.columns = [c.lower() for c in df_resampled.columns]
                    
                    if not df_resampled.empty:
                        self.data_feed[symbol] = df_resampled
                        count += 1
                    
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
                
        print(f"Loaded {count} symbols with data in range.")

def main():
    # Setup Range (Strings for Engine)
    # Beijing: Dec 08 13:30 to Dec 11 13:30
    # UTC: Dec 08 05:30 to Dec 11 05:30
    start_date = "2025-12-08 05:30:00"
    end_date = "2025-12-11 05:30:00"
    
    print(f"Starting 3-Day Backtest: {start_date} -> {end_date} (UTC)")
    
    # Run Engine
    engine = Last3DaysBacktestEngine(initial_balance=1000)
    # import pandas as pd # Removed to avoid shadowing
    engine.run(start_date=start_date, end_date=end_date, days=None)

if __name__ == "__main__":
    main()
