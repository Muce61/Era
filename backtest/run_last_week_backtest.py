import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.run_1m_freq_backtest import MinuteFreqBacktestEngine

class LastWeekBacktestEngine(MinuteFreqBacktestEngine):
    def load_data(self):
        """
        Load from standard data directory: /Users/muce/1m_data/new_backtest_data_1year_1m
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        print(f"Loading 1m data from {data_dir}...")
        if not data_dir.exists():
             print(f"Error: Data directory {data_dir} does not exist!")
             return

        files = list(data_dir.glob("*.csv"))
        import pandas as pd
        
        # We can optionally limit to specific symbols if needed, or load all.
        # Loading all might be memory intensive if there are 600+ coins and 1 year data.
        # But we only need the last week.
        # Optimization: Read only the last part of the file if possible, or filter after reading.
        
        count = 0
        for file_path in files:
            try:
                symbol = file_path.stem 
                # Load 1m data directly
                # To optimize memory, we could use pd.read_csv with chunksize or skiprows, 
                # but simplified logic: read, parse, filter.
                
                # Check file size/lines first? No, let's just try reading.
                # If files are huge (1 year 1m data), reading full csv is slow.
                # Only read if modified recently? Files should be updated by the fetch script.
                
                df_1m = pd.read_csv(file_path, parse_dates=['timestamp'])
                
                # Filter for Relevant Date Range (Optimization)
                # UTC Start: 2025-12-04 01:00
                start_filter = datetime(2025, 12, 4, 0, 0, 0)
                df_1m = df_1m[df_1m['timestamp'] >= start_filter]
                
                df_1m.set_index('timestamp', inplace=True)
                df_1m.dropna(inplace=True)
                
                if len(df_1m) > 100: 
                    self.data_feed[symbol] = df_1m
                    count += 1
                    
                if count % 50 == 0:
                    print(f"Loaded {count} symbols...")
                    
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"Successfully loaded {len(self.data_feed)} symbols (Last Week Data).")

def main():
    print("="*60)
    print("Running Backtest: Last Week (Beijing Time Dec 4 09:00 - Dec 11 09:00)")
    print("UTC Time: Dec 4 01:00 - Dec 11 01:00")
    print("="*60)
    
    start_date = "2025-12-04 01:00:00"
    end_date = "2025-12-11 01:00:00"
    
    print(f"Start Date (UTC): {start_date}")
    print(f"End Date (UTC):   {end_date}")
    
    engine = LastWeekBacktestEngine(initial_balance=1000)
    engine.run(start_date=start_date, end_date=end_date, days=None) 

if __name__ == "__main__":
    main()
