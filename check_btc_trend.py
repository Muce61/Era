import pandas as pd
import pandas_ta as ta

def check_btc_trend():
    df = pd.read_csv('/Users/muce/1m_data/new_backtest_data_1year_1m/BTCUSDTUSDT.csv', parse_dates=['timestamp'], index_col='timestamp')
    df_15m = df.resample('15min').agg({'close': 'last'}).dropna()
    
    # Calculate EMA 200
    df_15m['ema200'] = ta.ema(df_15m['close'], length=200)
    
    # Check Dec 6 - Dec 7
    target_start = '2025-12-06 00:00:00'
    target_end = '2025-12-07 12:00:00'
    
    slice_df = df_15m.loc[target_start:target_end]
    
    print(f"Checking BTC Trend from {target_start} to {target_end}")
    print(f"Total bars: {len(slice_df)}")
    
    bearish_count = 0
    for idx, row in slice_df.iterrows():
        is_bearish = row['close'] < row['ema200']
        if is_bearish:
            bearish_count += 1
            
    print(f"Bearish Bars: {bearish_count} / {len(slice_df)}")
    print(f"Bearish %: {bearish_count/len(slice_df)*100:.1f}%")
    
    # Sample logs
    print("\nSample Data (Dec 6 02:00):")
    try:
        sample = df_15m.loc['2025-12-06 02:00:00']
        print(f"Close: {sample['close']:.2f}, EMA200: {sample['ema200']:.2f}, Bearish: {sample['close'] < sample['ema200']}")
    except:
        print("Sample not found")

if __name__ == "__main__":
    check_btc_trend()
