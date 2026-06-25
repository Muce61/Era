import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
import time
import os

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from data.binance_client import BinanceClient

def main():
    print("="*60)
    print("Updating Historical Data Feed (Append Mode)")
    print("Target: /Users/muce/1m_data/new_backtest_data_1year_1m")
    print("="*60)
    
    data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
    if not data_dir.exists():
        print(f"Error: Directory {data_dir} not found.")
        return
        
    client = BinanceClient()
    
    # Get list of CSVs
    files = list(data_dir.glob("*.csv"))
    print(f"Found {len(files)} existing data files.")
    
    # Sort files to prioritize majors if possible, or just alpha
    files.sort()
    
    count = 0
    updated_count = 0
    
    for file_path in files:
        count += 1
        symbol_key = file_path.stem # e.g. BTCUSDTUSDT
        
        # Convert filename to Binance Symbol
        # Heuristic: BTCUSDTUSDT -> BTC/USDT:USDT
        # The stored files seem to have a double suffix logic or plain concat
        # Live bot uses 'BTC/USDT:USDT'
        # Let's try to deduce the symbol
        # If it ends with 'USDTUSDT', it's likely 'BASE/USDT:USDT'
        
        if symbol_key.endswith('USDTUSDT'):
            base = symbol_key.replace('USDTUSDT', '')
            symbol = f"{base}/USDT:USDT"
        else:
            # Maybe standard format?
            # skip weird ones for now or log warning
            # print(f"Skipping {symbol_key}: Unknown format")
            continue
            
        # Check exclusion
        if 'UP' in symbol or 'DOWN' in symbol:
            continue
            
        try:
            print(f"[{count}/{len(files)}] Updating {symbol}...", end='\r')
            
            # 1. Read last line of CSV to get last timestamp
            # Fast read using seek if possible, but pandas is easier for safety
            try:
                # Read only tail
                # But to be safe against unordered data, maybe read headers and last row
                # Let's assume sorted
                with open(file_path, 'rb') as f:
                    try:  # Catch OSError in case of a one line file 
                        f.seek(-100, os.SEEK_END)
                    except OSError:
                        pass # One line file
                    last = f.readlines()[-1].decode()
                    
                # Parse timestamp from last line "2024-11-28 21:00:00,..."
                last_ts_str = last.split(',')[0]
                last_ts = pd.Timestamp(last_ts_str)
                
            except Exception as e:
                # Fallback: Read full csv
                df_temp = pd.read_csv(file_path)
                if df_temp.empty:
                    # Empty file, need full fetch? Or skip
                    start_time = datetime(2024, 1, 1) # Default
                else:
                    last_ts = pd.to_datetime(df_temp['timestamp'].iloc[-1])
            
            # Start fetching from last_ts + 1 min
            since_ts = int((last_ts + timedelta(minutes=1)).timestamp() * 1000)
            now_ts = int(datetime.now().timestamp() * 1000)
            
            if now_ts - since_ts < 60000:
                # Up to date
                continue
                
            # Fetch Loop
            new_candles = []
            while since_ts < now_ts:
                ohlcv = client.exchange.fetch_ohlcv(symbol, timeframe='1m', since=since_ts, limit=1000)
                if not ohlcv:
                    break
                    
                new_candles.extend(ohlcv)
                since_ts = ohlcv[-1][0] + 60000
                
                # Rate limit
                time.sleep(client.exchange.rateLimit / 1000)
                
                if len(ohlcv) < 1000:
                    break
                    
            if new_candles:
                # Process and Append
                new_df = pd.DataFrame(new_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                new_df['timestamp'] = pd.to_datetime(new_df['timestamp'], unit='ms')
                
                # Filter duplicates just in case
                new_df = new_df[new_df['timestamp'] > last_ts]
                
                if not new_df.empty:
                    new_df.to_csv(file_path, mode='a', header=False, index=False)
                    updated_count += 1
                    # print(f"Appended {len(new_df)} rows to {symbol_key}")
                    
        except Exception as e:
            # print(f"Error updating {symbol}: {e}")
            pass
            
    print(f"\n✅ Update Complete. Updated {updated_count} files.")

if __name__ == "__main__":
    main()
