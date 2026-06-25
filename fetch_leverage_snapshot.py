import sys
from pathlib import Path
import json
import pandas as pd
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from data.binance_client import BinanceClient

def main():
    print("="*60)
    print("Fetching CURRENT Max Leverage Snapshot for Backtest")
    print("="*60)
    
    client = BinanceClient()
    
    # Force load leverage brackets to cache
    # The init() of BinanceClient usually does this now, but let's be sure
    if not client.leverage_cache:
        print("Leverage cache empty, forcing reload...")
        client._load_leverage_brackets()
        
    leverage_map = client.leverage_cache
    
    if not leverage_map:
        print("❌ Failed to fetch leverage data.")
        return

    print(f"✅ Retrieved leverage limits for {len(leverage_map)} symbols.")
    
    # Convert to DataFrame for easier inspection/saving
    data = []
    for symbol, max_lev in leverage_map.items():
        data.append({
            'symbol': symbol,
            'max_leverage': max_lev,
            'updated_at': datetime.now().isoformat()
        })
        
    df = pd.DataFrame(data)
    
    # Filter for USDT pairs mostly
    df = df[df['symbol'].str.contains('USDT')]
    
    # Sort by symbol
    df = df.sort_values('symbol')
    
    output_file = Path("backtest/leverage_snapshot.json")
    
    # Save as JSON map for easy loading {symbol: max_lev}
    # This is lighter than CSV for the engine to load
    simple_map = dict(zip(df['symbol'], df['max_leverage']))
    
    with open(output_file, 'w') as f:
        json.dump(simple_map, f, indent=4)
        
    print(f"Saved snapshot to: {output_file}")
    print("\nPreview Top 10:")
    print(df.head(10))
    print("\nPreview Bottom 10:")
    print(df.tail(10))

if __name__ == "__main__":
    main()
