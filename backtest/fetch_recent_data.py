import ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time
import pytz

def fetch_recent_data():
    """
    Fetch 1-minute kline data for ALL USDT perpetual contracts.
    Time range: 2025-12-05 00:00 to 17:00 (Beijing Time, UTC+8)
    UTC Range: 2025-12-04 16:00 to 2025-12-05 09:00
    """
    exchange = ccxt.binance({
        'options': {'defaultType': 'future'}
    })
    
    # Load markets
    print("Loading markets...")
    markets = exchange.load_markets()
    
    # Get all USDT perpetual contracts
    usdt_perpetuals = [s for s in markets.keys() if '/USDT:USDT' in s]
    
    print(f"Total USDT perpetuals: {len(usdt_perpetuals)}")
    print(f"Fetching 1-minute kline data for ALL symbols...")
    print(f"Target Time Range (UTC+8): 2025-11-28 00:00 - 2025-12-05 18:00")
    print(f"With 24h Warmup (UTC+8):  2025-11-27 00:00 - 2025-12-05 18:00")
    print(f"UTC Range: 2025-11-26 16:00 - 2025-12-05 10:00")
    
    # Create output directory
    output_dir = Path('/Users/muce/1m_data/recent_backtest_data')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Timeframe: 1m
    timeframe = '1m'
    
    # Define exact time range in UTC
    # Start: Nov 26 16:00 UTC (Nov 27 00:00 UTC+8) - Provides 24h warmup before Nov 28
    # End: Dec 5 10:00 UTC (Dec 5 18:00 UTC+8)
    start_time = datetime(2025, 11, 26, 16, 0, 0, tzinfo=pytz.UTC)
    end_time = datetime(2025, 12, 5, 10, 0, 0, tzinfo=pytz.UTC)
    
    successful = 0
    failed = 0
    
    for idx, symbol in enumerate(usdt_perpetuals, 1):
        print(f"[{idx}/{len(usdt_perpetuals)}] {symbol}...", end=' ')
        
        try:
            all_data = []
            current_start = start_time
            
            # Fetch data in chunks (pagination)
            while current_start < end_time:
                since = int(current_start.timestamp() * 1000)
                
                # Fetch OHLCV data
                ohlcv = exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=1000  # Max limit per request
                )
                
                if not ohlcv:
                    break
                    
                # Filter data to ensure it's within range (fetch_ohlcv might return more)
                chunk_data = []
                for candle in ohlcv:
                    ts = candle[0]
                    if start_time.timestamp() * 1000 <= ts <= end_time.timestamp() * 1000:
                        chunk_data.append(candle)
                
                if not chunk_data:
                     # If we got data but it's all outside our range (e.g. future data?), stop
                     if ohlcv[0][0] > end_time.timestamp() * 1000:
                         break
                
                all_data.extend(chunk_data)
                
                # Update current_start to the last timestamp + 1 interval
                last_timestamp = ohlcv[-1][0]
                current_start = datetime.fromtimestamp(last_timestamp / 1000, tz=pytz.UTC) + timedelta(minutes=1)
                
                # Rate limiting
                time.sleep(0.05)
            
            if not all_data:
                print(f"No data in range")
                continue

            # Convert to DataFrame
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Remove duplicates
            df = df.drop_duplicates(subset=['timestamp'])
            df = df.sort_values('timestamp')
            
            # Save to CSV
            filename = output_dir / f"{symbol.replace('/', '').replace(':', '')}.csv"
            df.to_csv(filename, index=False)
            
            print(f"✓ {len(df):,} candles")
            successful += 1
            
        except Exception as e:
            print(f"✗ {e}")
            failed += 1
            continue
    
    print(f"\n{'='*60}")
    print(f"Download Complete!")
    print(f"Successful: {successful}/{len(usdt_perpetuals)}")
    print(f"Failed: {failed}/{len(usdt_perpetuals)}")
    print(f"Data saved to: {output_dir}")
    print(f"{'='*60}")

if __name__ == "__main__":
    fetch_recent_data()
