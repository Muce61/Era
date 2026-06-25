import ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time

def fetch_180day_1m_data():
    """
    Fetch 180 days of 1-minute kline data for Top 100 USDT perpetual contracts
    WARNING: This will download ~6GB of data and take 2-4 hours
    """
    exchange = ccxt.binance({
        'options': {'defaultType': 'future'}
    })
    
    # Load markets
    print("Loading markets...")
    markets = exchange.load_markets()
    
    # Get all USDT perpetual contracts
    usdt_perpetuals = [s for s in markets.keys() if '/USDT:USDT' in s]
    
    # Get 24h volume for ranking
    print("Fetching tickers for volume ranking...")
    tickers = exchange.fetch_tickers()
    
    # Sort by volume and take top 100
    symbol_volumes = []
    for symbol in usdt_perpetuals:
        if symbol in tickers:
            volume = tickers[symbol].get('quoteVolume', 0)
            if volume:
                symbol_volumes.append((symbol, volume))
    
    symbol_volumes.sort(key=lambda x: x[1], reverse=True)
    top_symbols = [s[0] for s in symbol_volumes[:100]]
    
    print(f"Selected Top 100 symbols by volume")
    print(f"Fetching 180 days of 1-minute data...")
    print(f"⚠️  WARNING: This will download ~6GB data")
    print(f"⚠️  Estimated time: 2-4 hours")
    print(f"⚠️  Please ensure stable internet connection\n")
    
    # Create output directory
    output_dir = Path('/Users/muce/1m_data/backtest_data_1m_180d')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Timeframe: 1m
    timeframe = '1m'
    
    # Time range: 180 days back
    days_back = 180
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days_back)
    
    print(f"Start time: {start_time}")
    print(f"End time: {end_time}\n")
    
    successful = 0
    failed = 0
    start_download = time.time()
    
    for idx, symbol in enumerate(top_symbols, 1):
        symbol_start = time.time()
        print(f"[{idx}/{len(top_symbols)}] {symbol}...", end=' ', flush=True)
        
        try:
            all_data = []
            current_start = start_time
            fetch_count = 0
            
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
                fetch_count += 1
                
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
            
            symbol_time = time.time() - symbol_start
            print(f"✓ {len(df):,} candles ({fetch_count} requests, {symbol_time:.1f}s)")
            successful += 1
            
            # Progress update
            if idx % 10 == 0:
                elapsed = time.time() - start_download
                avg_time = elapsed / idx
                remaining = (len(top_symbols) - idx) * avg_time
                print(f"  Progress: {idx}/{len(top_symbols)} ({idx/len(top_symbols)*100:.1f}%) - "
                      f"Elapsed: {elapsed/60:.0f}min - "
                      f"ETA: {remaining/60:.0f}min")
            
        except Exception as e:
            print(f"✗ {e}")
            failed += 1
            continue
    
    total_time = time.time() - start_download
    print(f"\n{'='*60}")
    print(f"Download Complete!")
    print(f"Successful: {successful}/{len(top_symbols)}")
    print(f"Failed: {failed}/{len(top_symbols)}")
    print(f"Total time: {total_time/60:.1f} minutes ({total_time/3600:.2f} hours)")
    print(f"Data saved to: {output_dir}")
    print(f"{'='*60}")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("180-Day 1-Minute Data Download")
    print("="*60)
    print("\nThis will download:")
    print("- Timeframe: 1 minute")
    print("- Period: 180 days")
    print("- Symbols: Top 100 USDT perpetuals")
    print("- Estimated size: ~6 GB")
    print("- Estimated time: 2-4 hours")
    print("\n" + "="*60)
    
    response = input("\nAre you sure you want to continue? (yes/no): ")
    if response.lower() in ['yes', 'y']:
        print("\nStarting download...\n")
        fetch_180day_1m_data()
    else:
        print("\nDownload cancelled.")
