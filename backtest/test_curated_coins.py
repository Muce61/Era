import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

class CuratedCoinsEngine(RealBacktestEngine):
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        # Use current strict filters
        self.config.CHANGE_THRESHOLD_MIN = 5.0
        self.config.CHANGE_THRESHOLD_MAX = 200.0
        self.config.TOP_GAINER_COUNT = 50
        
        # Load quality whitelist
        whitelist_file = Path(__file__).parent.parent / "config" / "quality_whitelist.txt"
        self.quality_whitelist = set()
        with open(whitelist_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    self.quality_whitelist.add(line)
        
        print(f"📋 Loaded quality whitelist: {len(self.quality_whitelist)} coins")
        
    def load_data(self):
        """
        Load from NEW data directory but ONLY quality coins from whitelist
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        print(f"Loading data from {data_dir}...")
        print(f"Filtering to {len(self.quality_whitelist)} quality coins...")
        
        if not data_dir.exists():
            print(f"Error: Data directory {data_dir} does not exist!")
            return

        files = list(data_dir.glob("*.csv"))
        loaded_count = 0
        skipped_count = 0
        
        for file_path in files:
            try:
                symbol = file_path.stem
                
                # QUALITY FILTER: Only load coins in whitelist
                if symbol not in self.quality_whitelist:
                    skipped_count += 1
                    continue
                
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
                    loaded_count += 1
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"✅ Loaded {loaded_count} quality coins (Resampled to 15m).")
        print(f"⏭️  Skipped {skipped_count} non-quality coins.")

def main():
    print("="*60)
    print("CURATED COIN STRATEGY TEST")
    print("Data: New 1-year data (597 coins)")
    print("Filter: 50 Quality Coins (from legacy success)")
    print("Strategy: Strict filters (RSI 70-85, ADX 30-50)")
    print("="*60)
    
    engine = CuratedCoinsEngine(initial_balance=100)
    engine.run(days=30)

if __name__ == "__main__":
    main()
