import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
import time

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from data.binance_client import BinanceClient

def main():
    print("="*60)
    print("Fetching Recent 1m Data (Dec 9 - Dec 10)")
    print("="*60)
    
    client = BinanceClient()
    
    # Target Data Directory
    save_dir = Path("backtest/temp_data_last_night")
    save_dir.mkdir(parents=True, exist_ok=True)
    
    # Get Top Gainers/Volume to ensure we cover likely candidates
    # In live bot, it scans Top 200 by volume.
    # To be safe, let's fetch Top 100 + generic majors
    print("Fetching Top 200 coins list...")
    tickers = client.get_top_gainers(limit=200)
    symbols = [t[0] for t in tickers]
    
    # Specific ones from log to ensure we check them
    log_symbols = ['MAGIC/USDT:USDT', 'FOLKS/USDT:USDT', 'ADA/USDT:USDT', 'WIF/USDT:USDT', 
                   'AVAX/USDT:USDT', 'HYPER/USDT:USDT', 'ZEN/USDT:USDT', 'FET/USDT:USDT', 
                   'XPL/USDT:USDT', 'PENGU/USDT:USDT', 'ICP/USDT:USDT', 'FHE/USDT:USDT', 'RIVER/USDT:USDT']
    
    target_symbols = list(set(symbols + log_symbols))
    print(f"Targeting {len(target_symbols)} symbols.")
    
    # Timeframe: Dec 9 08:00 UTC (to cover 18:00 Beijing start with lookback) 
    # to Dec 10 10:00 UTC
    since_ts = int(datetime(2025, 12, 9, 8, 0, 0).timestamp() * 1000)
    
    for i, symbol in enumerate(target_symbols):
        try:
            print(f"[{i+1}/{len(target_symbols)}] Fetching {symbol}...", end='\r')
            
            # Fetch 1m candles
            # CCXT fetch_ohlcv
            ohlcv = client.exchange.fetch_ohlcv(symbol, timeframe='1m', since=since_ts, limit=1500)
            
            if not ohlcv:
                continue
                
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Clean symbol for filename
            clean_sym = symbol.replace('/USDT:USDT', 'USDT').replace('/', '')
            
            save_path = save_dir / f"{clean_sym}.csv"
            df.to_csv(save_path)
            
            time.sleep(0.1) # Rate limit nice
            
        except Exception as e:
            # print(f"Error {symbol}: {e}")
            pass
            
    print(f"\n✅ Done. Verified data saved to {save_dir}")

if __name__ == "__main__":
    main()
