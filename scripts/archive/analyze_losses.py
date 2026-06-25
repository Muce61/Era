import pandas as pd
import numpy as np

# Load trades
df = pd.read_csv('backtest_trades.csv')

# Separate winners and losers
winners = df[df['pnl'] > 0]
losers = df[df['pnl'] <= 0]

print(f"Total Trades: {len(df)}")
print(f"Winners: {len(winners)}")
print(f"Losers: {len(losers)}")

# Analyze Metrics
metrics = ['rsi', 'adx', 'volume_ratio', 'upper_wick_ratio']

print("\n--- Metric Analysis (Mean) ---")
print(f"{'Metric':<20} {'Winners':<10} {'Losers':<10} {'Diff %':<10}")
for m in metrics:
    if m in df.columns:
        w_mean = winners[m].mean()
        l_mean = losers[m].mean()
        diff = ((w_mean - l_mean) / l_mean) * 100 if l_mean != 0 else 0
        print(f"{m:<20} {w_mean:<10.4f} {l_mean:<10.4f} {diff:<10.2f}%")

print("\n--- Time of Day Analysis ---")
df['hour'] = pd.to_datetime(df['entry_time']).dt.hour
hourly_win_rate = df.groupby('hour')['pnl'].apply(lambda x: (x > 0).mean())
print(hourly_win_rate.sort_values())

print("\n--- Symbol Analysis (Worst Performers) ---")
symbol_pnl = df.groupby('symbol')['pnl'].sum().sort_values()
print(symbol_pnl.head(5))
