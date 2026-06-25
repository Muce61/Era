import sys
from pathlib import Path
# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[0]))

from backtest.real_engine import RealBacktestEngine
import pandas as pd

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
                # But real_engine usually expects simple format or handles it.
                # Let's just use the stem for now, consistent with original load_data
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

def main():
    print("="*60)
    print("Running 30-Day Backtest")
    print("="*60)
    
    # Initialize engine
    engine = BacktestEngine30D(initial_balance=100)
    
    # Run for last 30 days
    # The engine.run(days=30) method handles the filtering
    engine.run(days=30)

if __name__ == "__main__":
    main()
