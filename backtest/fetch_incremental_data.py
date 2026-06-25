import ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time
import pytz

def fetch_incremental_data():
    """
    Incrementally fetch 1-minute kline data for ALL USDT perpetual contracts.
    Updates existing data in /Users/muce/1m_data/new_backtest_data_1year_1m
    Target: Fetch from last timestamp to 2025-12-05 19:00 Beijing Time (11:00 UTC)
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
    print(f"Incremental Update Mode")
    print(f"Target End Time (Beijing): 2025-12-12 17:00")
    print(f"Target End Time (UTC): 2025-12-12 09:00")
    
    # Create output directory
    data_dir = Path('/Users/muce/1m_data/new_backtest_data_1year_1m')
    if not data_dir.exists():
        print(f"Error: Data directory {data_dir} does not exist!")
        return
    
    # Timeframe: 1m
    timeframe = '1m'
    
    # Define end time in UTC (2025-12-12 17:00 Beijing = 09:00 UTC)
    end_time = datetime(2025, 12, 12, 9, 0, 0, tzinfo=pytz.UTC)
    
    successful = 0
    failed = 0
    
    for idx, symbol in enumerate(usdt_perpetuals, 1):
        print(f"[{idx}/{len(usdt_perpetuals)}] {symbol}...", end=' ')
        
        try:
            # Convert symbol to filename format
            filename = data_dir / f"{symbol.replace('/', '').replace(':', '')}.csv"
            
            # Determine start time
            if filename.exists():
                # Read existing file to find last timestamp
                df_existing = pd.read_csv(filename, parse_dates=['timestamp'])
                
                # Robust Timezone Handling
                if 'timestamp' in df_existing.columns and not df_existing.empty:
                     # Check if it has timezone info
                     if df_existing['timestamp'].dt.tz is None:
                         # It is naive, localize to UTC
                         df_existing['timestamp'] = df_existing['timestamp'].dt.tz_localize('UTC')
                     else:
                         # It is aware, convert to UTC
                         df_existing['timestamp'] = df_existing['timestamp'].dt.tz_convert('UTC')
                
                if len(df_existing) > 0:
                    last_timestamp = df_existing['timestamp'].max()
                    # Start from next minute
                    start_time = last_timestamp + timedelta(minutes=1)
                    
                    # Force start_time to be UTC
                    if start_time.tzinfo is None:
                        start_time = pytz.UTC.localize(start_time)
                    else:
                        start_time = start_time.astimezone(pytz.UTC)
                else:
                    # Empty file, start from 1 year ago
                    start_time = end_time - timedelta(days=365)
                    if start_time.tzinfo is None: start_time = pytz.UTC.localize(start_time)
            else:
                # New file, start from 1 year ago
                start_time = end_time - timedelta(days=365)
            
            # Ensure start_time is tz-aware
            if start_time.tzinfo is None:
                start_time = pytz.UTC.localize(start_time)
            
            # Check if we need to fetch
            if start_time >= end_time:
                print(f"✓ Already up to date")
                successful += 1
                continue
            
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
                    
                # Filter data to ensure it's within range
                chunk_data = []
                for candle in ohlcv:
                    ts = candle[0]
                    if start_time.timestamp() * 1000 <= ts <= end_time.timestamp() * 1000:
                        chunk_data.append(candle)
                
                if not chunk_data:
                    # If we got data but it's all outside our range, stop
                    if ohlcv[0][0] > end_time.timestamp() * 1000:
                        break
                
                all_data.extend(chunk_data)
                
                # Update current_start to the last timestamp + 1 interval
                last_timestamp = ohlcv[-1][0]
                current_start = datetime.fromtimestamp(last_timestamp / 1000, tz=pytz.UTC) + timedelta(minutes=1)
                
                # Rate limiting
                time.sleep(0.05)
            
            if not all_data:
                print(f"✓ No new data")
                successful += 1
                continue

            # Convert new data to DataFrame
            df_new = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms')
            
            # Merge with existing data if file exists
            if filename.exists():
                df_existing = pd.read_csv(filename, parse_dates=['timestamp'])
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            else:
                df_combined = df_new
            
            # Remove duplicates and sort
            df_combined = df_combined.drop_duplicates(subset=['timestamp'])
            df_combined = df_combined.sort_values('timestamp')
            
            # Save to CSV
            df_combined.to_csv(filename, index=False)
            
            print(f"✓ +{len(df_new):,} new candles (total: {len(df_combined):,})")
            successful += 1
            
        except Exception as e:
            print(f"✗ {e}")
            failed += 1
            continue
    
    print(f"\n{'='*60}")
    print(f"Incremental Update Complete!")
    print(f"Successful: {successful}/{len(usdt_perpetuals)}")
    print(f"Failed: {failed}/{len(usdt_perpetuals)}")
    print(f"Data directory: {data_dir}")
    print(f"{'='*60}")

if __name__ == "__main__":
    fetch_incremental_data()
