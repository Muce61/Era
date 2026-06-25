import ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import time

def fetch_180day_data():
    """
    Fetch 180 days of 15-minute kline data for Top 100 USDT perpetual contracts
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
    print(f"Fetching 180 days of 15-minute data...")
    print(f"Estimated time: 10-15 minutes\n")
    
    # Create output directory
    output_dir = Path('/Users/muce/1m_data/historical/backtest_180d_15m')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Timeframe: 15m
    timeframe = '15m'
    
    # Time range: 180 days back
    days_back = 180
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days_back)
    
    successful = 0
    failed = 0
    
    for idx, symbol in enumerate(top_symbols, 1):
        print(f"[{idx}/{len(top_symbols)}] {symbol}...", end=' ')
        
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
                current_start = datetime.fromtimestamp(last_timestamp / 1000) + timedelta(minutes=15)
                
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
    print(f"Successful: {successful}/{len(top_symbols)}")
    print(f"Failed: {failed}/{len(top_symbols)}")
    print(f"Data saved to: {output_dir}")
    print(f"{'='*60}")

if __name__ == "__main__":
    fetch_180day_data()
