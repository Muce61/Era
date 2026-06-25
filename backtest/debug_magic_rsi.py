import sys
from pathlib import Path
import pandas as pd
import pandas_ta as ta

def main():
    print("="*60)
    print("Verifying MAGIC RSI at 2025-12-09 17:56:58 UTC+8")
    print("="*60)
    
    # Path to data
    file_path = Path("backtest/temp_data_last_night/MAGICUSDT.csv")
    if not file_path.exists():
        print("Data file not found")
        return
        
    # Load 1m Data
    df = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
    
    # Target time: 2025-12-09 17:56:58 Beijing = 09:56:58 UTC
    # Logs are in Beijing Time (likely, based on current local time).
    # Wait, logs format: `2025-12-09 17:56:58`.
    # Current Local Time: 2025-12-10 17:58.
    # So Logs are Local/Beijing Time.
    # CSV is usually UTC (from Binance).
    # 17:56 Beijing = 09:56 UTC.
    
    target_time_utc = pd.Timestamp("2025-12-09 09:56:58")
    
    # Slice 1m data up to target
    df_slice = df.loc[:target_time_utc]
    
    print(f"Data slice ends at: {df_slice.index[-1]}")
    
    # Resample to 15m
    agg_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }
    
    # Pandas resample aligns to 00, 15, 30, 45.
    # 09:56:58 belongs to 09:45 candle (developing) or 09:45-10:00 bin.
    # Standard resample uses left label?
    # Let's see what `RealBacktestEngine` does.
    
    df_15m = df_slice.resample('15min').agg(agg_dict).dropna()
    print("Latest 15m candles:")
    print(df_15m.tail(3))
    
    # Calculate RSI
    rsi = ta.rsi(df_15m['close'], length=14)
    if rsi is not None and not rsi.empty:
        last_rsi = rsi.iloc[-1]
        print(f"\nCalculated RSI (14): {last_rsi:.2f}")
        print(f"Log Value: 49.5")
    else:
        print("Not enough data for RSI")

if __name__ == "__main__":
    main()
