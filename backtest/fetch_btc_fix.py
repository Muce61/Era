import ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time
import pytz

def fetch_btc_fix():
    print("Fixing BTC Data...")
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    
    symbol = 'BTC/USDT:USDT'
    data_dir = Path('/Users/muce/1m_data/new_backtest_data_1year_1m')
    filename = data_dir / "BTCUSDTUSDT.csv"
    
    # Target End Time: 2025-12-07 04:00 UTC
    end_time = datetime(2025, 12, 7, 4, 0, 0, tzinfo=pytz.UTC)
    
    if filename.exists():
        df = pd.read_csv(filename, parse_dates=['timestamp'])
        last_timestamp = df['timestamp'].max()
        # Convert to UTC
        if last_timestamp.tzinfo is None:
            last_timestamp = pytz.UTC.localize(last_timestamp)
            
        print(f"Current BTC end time: {last_timestamp}")
        start_time = last_timestamp + timedelta(minutes=1)
    else:
        print("BTC file not found!")
        return

    if start_time >= end_time:
        print("BTC already up to date.")
        return

    print(f"Fetching from {start_time} to {end_time}")
    
    all_data = []
    current_start = start_time
    timeframe = '1m'
    
    while current_start < end_time:
        since = int(current_start.timestamp() * 1000)
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, 1000)
            if not ohlcv: break
            
            chunk_data = []
            for candle in ohlcv:
                ts = candle[0]
                if start_time.timestamp() * 1000 <= ts <= end_time.timestamp() * 1000:
                    chunk_data.append(candle)
            
            if not chunk_data:
                if ohlcv[0][0] > end_time.timestamp() * 1000: break
            
            all_data.extend(chunk_data)
            last_timestamp = ohlcv[-1][0]
            current_start = datetime.fromtimestamp(last_timestamp/1000, tz=pytz.UTC) + timedelta(minutes=1)
            time.sleep(0.05)
            print(f".", end='', flush=True)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)
            
    if all_data:
        df_new = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms')
        
        # Merge
        df_combined = pd.concat([df, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
        df_combined.to_csv(filename, index=False)
        print(f"\nUpdated BTC. New tail: {df_combined['timestamp'].iloc[-1]}")
    else:
        print("\nNo new data fetched for BTC.")

if __name__ == "__main__":
    fetch_btc_fix()
