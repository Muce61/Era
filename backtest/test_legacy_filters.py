import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

class LegacyDataEngine(RealBacktestEngine):
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        # Use current filters (RSI 70-85, ADX 30-50, etc.)
        self.config.CHANGE_THRESHOLD_MIN = 5.0
        self.config.CHANGE_THRESHOLD_MAX = 200.0
        self.config.TOP_GAINER_COUNT = 50
        
    def load_data(self):
        """
        Load from LEGACY data directory (227 coins that achieved 900%)
        """
        data_dir = Path("/Users/muce/1m_data/backtest_data_legacy")
        self.data_feed = {}
        
        print(f"Loading LEGACY data from {data_dir}...")
        if not data_dir.exists():
            print(f"Error: Data directory {data_dir} does not exist!")
            return

        files = list(data_dir.glob("*.csv"))
        print(f"Found {len(files)} CSV files.")
        
        for file_path in files:
            try:
                symbol = file_path.stem 
                
                # Legacy data is already 15m, no resampling needed
                df = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                
                if len(df) > 50:
                    self.data_feed[symbol] = df
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"Successfully loaded {len(self.data_feed)} symbols (Legacy 15m data).")

def main():
    print("="*60)
    print("Test: Current Filters on LEGACY Data (227 coins)")
    print("Goal: Determine if filters work in 'quality environment'")
    print("="*60)
    
    engine = LegacyDataEngine(initial_balance=100)
    engine.run(days=30)

if __name__ == "__main__":
    main()
