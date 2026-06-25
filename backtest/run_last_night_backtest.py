import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.run_1m_freq_backtest import MinuteFreqBacktestEngine

class RecentDataBacktestEngine(MinuteFreqBacktestEngine):
    def load_data(self):
        """
        Load from temporary recent data directory
        """
        data_dir = Path("backtest/temp_data_last_night")
        self.data_feed = {}
        
        print(f"Loading recent 1m data from {data_dir}...")
        if not data_dir.exists():
             print(f"Error: Data directory {data_dir} does not exist!")
             return

        files = list(data_dir.glob("*.csv"))
        import pandas as pd
        
        for file_path in files:
            try:
                symbol = file_path.stem 
                # Load 1m data directly
                df_1m = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                df_1m.dropna(inplace=True)
                
                if len(df_1m) > 100: 
                    self.data_feed[symbol] = df_1m
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"Successfully loaded {len(self.data_feed)} symbols (Recent 1m Data).")

def main():
    print("="*60)
    print("Running Diagnostic Backtest: Last Night (Beijing Time Dec 9 18:00 - Dec 10 09:00)")
    print("UTC Time: Dec 9 10:00 - Dec 10 01:00")
    print("="*60)
    
    # 18:00 Beijing = 10:00 UTC
    # 09:00 Beijing (next day) = 01:00 UTC (next day)
    start_date = "2025-12-09 10:00:00"
    end_date = "2025-12-10 01:00:00"
    
    print(f"Start Date (UTC): {start_date}")
    print(f"End Date (UTC):   {end_date}")
    
    engine = RecentDataBacktestEngine(initial_balance=100)
    engine.run(start_date=start_date, end_date=end_date, days=None) 

if __name__ == "__main__":
    main()
