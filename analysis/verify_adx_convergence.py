import pandas as pd
import pandas_ta as ta
import sys
from pathlib import Path

# Mock config to match strategy
class Config:
    CHANGE_THRESHOLD_MIN = 2.0
    CHANGE_THRESHOLD_MAX = 200.0
    BULLISH_CANDLES_COUNT = 2
    TOP_GAINER_COUNT = 50

# Load data for LUNA2
# We need the source file. Assuming it's in the standard directory.
data_path = Path("/Users/muce/1m_data/new_backtest_data_1year_1m/LUNA2USDTUSDT.csv")

if not data_path.exists():
    print(f"Data file not found: {data_path}")
    sys.exit(1)

print(f"Loading data from {data_path}...")
df_1m = pd.read_csv(data_path, parse_dates=['timestamp'], index_col='timestamp')
if df_1m.index.tz is None:
    df_1m.index = df_1m.index.tz_localize('UTC')

# Resample to 15m to match live bot
agg_dict = {
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
}
df_15m = df_1m.resample('15min').agg(agg_dict).dropna()

# Target Timestamp: 2025-12-11 12:57 Beijing = 04:57 UTC
# We want to check the candle closely preceding this.
# 15m candles: 04:45, 05:00. 
# At 04:57 (live bot time), the active candle is 04:45 (closed at 05:00? No, 04:45-05:00).
# Wait, live bot usually fetches COMPLETED candles.
# At 12:57 (04:57), the last COMPLETED 15m candle is the 04:30-04:45 candle.
# Or maybe 04:45 is still open.
# The signal log was at 12:57:02. The 15m candle 12:45-13:00 is OPEN.
# The 12:30-12:45 candle is CLOSED.
# Effectively, calculation should be based on the last closed candle? 
# Or does the strategy use the developing candle?
# Step 11556 log: "LUNA2/USDT:USDT | ADX 17.8 not in [25, 60]"
# Let's check what value we get with different history lengths for the candle ending around 04:45 UTC.

target_time = pd.Timestamp("2025-12-11 04:45:00", tz='UTC') 
# Note: if the index is start time, 04:45 is the candle FROM 04:45 to 05:00.
# If we are strictly at 04:57, 04:45 is the LATEST AVAILABLE data (open).
# If we look at the previous closed one, it's 04:30.

print(f"\nAnalyzing Target Time: {target_time}")

def calc_adx(df_slice):
    if len(df_slice) < 15: return 0
    adx = ta.adx(df_slice['high'], df_slice['low'], df_slice['close'], length=14)
    if adx is None or adx.empty: return 0
    return adx['ADX_14'].iloc[-1]

# Test different warmups
lookbacks = [60, 100, 200, 300, 500, 1000]

print(f"{'Lookback':<10} | {'Start Time':<25} | {'ADX Value':<10} | {'Delta vs 1000':<15}")
print("-" * 70)

# Get the index location of target time
try:
    target_idx = df_15m.index.get_loc(target_time)
except KeyError:
    # Try finding nearest
    target_idx = df_15m.index.searchsorted(target_time)
    print(f"Target time not exact match, using nearest index: {df_15m.index[target_idx]}")

baseline_adx = 0

for limit in lookbacks:
    if target_idx < limit:
        print(f"Not enough data for limit {limit}")
        continue
        
    start_idx = target_idx - limit + 1
    # We include the target row? Yes.
    # slice is inclusive? iloc is [start : end+1] to include end
    df_slice = df_15m.iloc[start_idx : target_idx + 1].copy()
    
    adx_val = calc_adx(df_slice)
    
    if limit == 1000:
        baseline_adx = adx_val
    
    delta = ""
    if baseline_adx != 0:
        diff = adx_val - baseline_adx
        pct = (diff / baseline_adx) * 100
        delta = f"{diff:+.2f} ({pct:+.1f}%)"
        
    print(f"{limit:<10} | {str(df_slice.index[0]):<25} | {adx_val:.4f}     | {delta}")

print("-" * 70)
print("Conclusion: Does 60 candles produce a significantly different ADX than 300?")

print("\n--- HYPOTHESIS CHECK: 1-Minute Data Window (04:50 - 05:00) ---")
time_range = pd.date_range(start="2025-12-11 04:50:00", end="2025-12-11 05:00:00", freq="1min", tz='UTC')

print(f"{'Time':<25} | {'RSI':<6} | {'ADX':<6} | {'VolRatio':<8} | {'Result'}")
print("-" * 75)

for t in time_range:
    # Use data up to this minute
    if t not in df_1m.index:
        continue
        
    df_slice = df_1m.loc[:t].tail(300)
    
    rsi = ta.rsi(df_slice['close'], length=14).iloc[-1]
    adx_series = ta.adx(df_slice['high'], df_slice['low'], df_slice['close'], length=14)
    if adx_series is None or adx_series.empty: 
        adx = 0
    else:
        adx = adx_series['ADX_14'].iloc[-1]
        
    sma_vol = df_slice['volume'].iloc[-21:-1].mean()
    vol = df_slice['volume'].iloc[-1]
    vol_ratio = vol / sma_vol if sma_vol > 0 else 0
    
    status = "REJECTED"
    if 65 <= rsi <= 90 and 25 <= adx <= 60 and 2.5 <= vol_ratio <= 12:
        status = "✅ ACCEPTED"
    elif not (25 <= adx <= 60):
        status = f"REJ(ADX {adx:.1f})"
    elif not (65 <= rsi <= 90):
        status = f"REJ(RSI {rsi:.1f})"
    elif not (2.5 <= vol_ratio <= 12):
        status = f"REJ(Vol {vol_ratio:.1f})"
        
    print(f"{str(t):<25} | {rsi:.1f}   | {adx:.1f}   | {vol_ratio:.1f}     | {status}")
