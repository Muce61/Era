import ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time

def fetch_historical_data():
    """
    Fetch 1-minute kline data for ALL USDT perpetual contracts.
    Time range: Last 30 days.
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
    print(f"Estimated data size: ~2.5 GB")
    print(f"Estimated time: 30-60 minutes\n")
    
    # Create output directory
    output_dir = Path('/Users/muce/1m_data/backtest_data_1m')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Timeframe: 1m
    timeframe = '1m'
    
    # Time range: 30 days back
    days_back = 30
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days_back)
    
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
                    
                all_data.extend(ohlcv)
                
                # Update current_start to the last timestamp + 1 interval
                last_timestamp = ohlcv[-1][0]
                current_start = datetime.fromtimestamp(last_timestamp / 1000) + timedelta(minutes=1)
                
                # Rate limiting
                time.sleep(0.05)
            
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
    fetch_historical_data()
