import sys
from pathlib import Path
import pandas as pd
from datetime import datetime
import pytz

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[0]))

from data.binance_client import BinanceClient

def check_live_fetch():
    client = BinanceClient()
    symbol = "BTC/USDT:USDT" # or ETHUSDT... use one that works
    
    print(f"Fetching live data for {symbol}...")
    df = client.get_historical_klines("BTC/USDT:USDT", timeframe='15m', limit=5)
    
    if df.empty:
        print("Empty DF")
        return

    print("\nLast 3 Candles:")
    print(df.tail(3)[['timestamp', 'close', 'volume']])
    
    last_ts = df.iloc[-1]['timestamp']
    now_utc = datetime.now(pytz.UTC)
    
    # Convert last_ts to aware if needed (it comes from binance_client as datetime but maybe naive? client says pd.to_datetime(unit='ms'))
    # pd.to_datetime usually returns naive if not specified? No, usually OK.
    # Let's check.
    
    print(f"\nLast Candle TS: {last_ts}")
    print(f"Current Time:   {now_utc}")
    
    # Diff
    # If last_ts is roughly current time (e.g. 15:00 and now is 15:05), it is the OPEN candle.
    # If last_ts is 15:00 and now is 15:05, this candle closes at 15:15. So it is ACTIVE/INCOMPLETE.
    
    if last_ts.tzinfo is None:
        last_ts = pytz.UTC.localize(last_ts)
        
    diff = now_utc - last_ts
    print(f"Time since candle open: {diff}")
    
    if diff < pd.Timedelta(minutes=15):
        print(">> CONCLUSION: The last candle is INCOMPLETE (Active).")
        print(">> Strategy using iloc[-1] will fail volume checks.")
    else:
        print(">> CONCLUSION: The last candle is COMPLETE.")

if __name__ == "__main__":
    check_live_fetch()
