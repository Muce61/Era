import pandas as pd
import numpy as np

# Load trade data
df = pd.read_csv('backtest_trades_30d.csv', index_col=0)

# Classify trades
df['is_win'] = df['pnl'] > 0
wins = df[df['is_win']]
losses = df[~df['is_win']]

print("="*60)
print("TRADE ANALYSIS: Winners vs Losers")
print("="*60)
print(f"\nTotal Trades: {len(df)}")
print(f"Winners: {len(wins)} ({len(wins)/len(df)*100:.2f}%)")
print(f"Losers: {len(losses)} ({len(losses)/len(df)*100:.2f}%)")

# Feature comparison
features = ['rsi', 'adx', 'volume_ratio', 'upper_wick_ratio']

print("\n" + "="*60)
print("FEATURE COMPARISON (Median Values)")
print("="*60)
print(f"{'Feature':<20} {'Winners':<15} {'Losers':<15} {'Diff':<15}")
print("-"*60)

for feature in features:
    win_median = wins[feature].median()
    loss_median = losses[feature].median()
    diff = win_median - loss_median
    print(f"{feature:<20} {win_median:<15.2f} {loss_median:<15.2f} {diff:<15.2f}")

# Exit reason analysis
print("\n" + "="*60)
print("EXIT REASON BREAKDOWN")
print("="*60)
exit_reasons = df.groupby('reason')['pnl'].agg(['count', 'mean', lambda x: (x > 0).sum() / len(x) * 100])
exit_reasons.columns = ['Count', 'Avg PnL', 'Win Rate %']
exit_reasons = exit_reasons.sort_values('Count', ascending=False)
print(exit_reasons)

# Top 10 winning trades
print("\n" + "="*60)
print("TOP 10 WINNING TRADES")
print("="*60)
top_wins = wins.nlargest(10, 'pnl')[['symbol', 'pnl', 'rsi', 'adx', 'volume_ratio', 'upper_wick_ratio', 'reason']]
print(top_wins.to_string())

# Top 10 losing trades
print("\n" + "="*60)
print("TOP 10 LOSING TRADES")
print("="*60)
top_losses = losses.nsmallest(10, 'pnl')[['symbol', 'pnl', 'rsi', 'adx', 'volume_ratio', 'upper_wick_ratio', 'reason']]
print(top_losses.to_string())

# RSI range analysis
print("\n" + "="*60)
print("RSI RANGE ANALYSIS")
print("="*60)
rsi_bins = [0, 50, 60, 70, 80, 90, 100]
rsi_labels = ['<50', '50-60', '60-70', '70-80', '80-90', '90+']
df['rsi_bin'] = pd.cut(df['rsi'], bins=rsi_bins, labels=rsi_labels)
rsi_analysis = df.groupby('rsi_bin')['pnl'].agg(['count', 'mean', lambda x: (x > 0).sum() / len(x) * 100])
rsi_analysis.columns = ['Count', 'Avg PnL', 'Win Rate %']
print(rsi_analysis)

# ADX range analysis
print("\n" + "="*60)
print("ADX RANGE ANALYSIS (Trend Strength)")
print("="*60)
adx_bins = [0, 20, 30, 40, 50, 100]
adx_labels = ['<20 (Weak)', '20-30', '30-40', '40-50', '50+ (Strong)']
df['adx_bin'] = pd.cut(df['adx'], bins=adx_bins, labels=adx_labels)
adx_analysis = df.groupby('adx_bin')['pnl'].agg(['count', 'mean', lambda x: (x > 0).sum() / len(x) * 100])
adx_analysis.columns = ['Count', 'Avg PnL', 'Win Rate %']
print(adx_analysis)

# Volume ratio analysis
print("\n" + "="*60)
print("VOLUME RATIO ANALYSIS")
print("="*60)
vol_bins = [0, 2, 5, 10, 50]
vol_labels = ['<2x', '2-5x', '5-10x', '10x+']
df['vol_bin'] = pd.cut(df['volume_ratio'], bins=vol_bins, labels=vol_labels)
vol_analysis = df.groupby('vol_bin')['pnl'].agg(['count', 'mean', lambda x: (x > 0).sum() / len(x) * 100])
vol_analysis.columns = ['Count', 'Avg PnL', 'Win Rate %']
print(vol_analysis)

# Upper wick analysis
print("\n" + "="*60)
print("UPPER WICK RATIO ANALYSIS")
print("="*60)
wick_bins = [0, 0.1, 0.2, 0.3, 1.0]
wick_labels = ['<10%', '10-20%', '20-30%', '30%+']
df['wick_bin'] = pd.cut(df['upper_wick_ratio'], bins=wick_bins, labels=wick_labels)
wick_analysis = df.groupby('wick_bin')['pnl'].agg(['count', 'mean', lambda x: (x > 0).sum() / len(x) * 100])
wick_analysis.columns = ['Count', 'Avg PnL', 'Win Rate %']
print(wick_analysis)

# Key insights
print("\n" + "="*60)
print("KEY INSIGHTS & RECOMMENDATIONS")
print("="*60)

# 1. Optimal RSI range
best_rsi_bin = rsi_analysis.loc[rsi_analysis['Win Rate %'].idxmax()]
print(f"\n1. OPTIMAL RSI RANGE: {rsi_analysis['Win Rate %'].idxmax()}")
print(f"   - Win Rate: {best_rsi_bin['Win Rate %']:.2f}%")
print(f"   - Avg PnL: ${best_rsi_bin['Avg PnL']:.2f}")

# 2. Optimal ADX range
best_adx_bin = adx_analysis.loc[adx_analysis['Win Rate %'].idxmax()]
print(f"\n2. OPTIMAL ADX RANGE: {adx_analysis['Win Rate %'].idxmax()}")
print(f"   - Win Rate: {best_adx_bin['Win Rate %']:.2f}%")
print(f"   - Avg PnL: ${best_adx_bin['Avg PnL']:.2f}")

# 3. Optimal Volume
best_vol_bin = vol_analysis.loc[vol_analysis['Win Rate %'].idxmax()]
print(f"\n3. OPTIMAL VOLUME RATIO: {vol_analysis['Win Rate %'].idxmax()}")
print(f"   - Win Rate: {best_vol_bin['Win Rate %']:.2f}%")
print(f"   - Avg PnL: ${best_vol_bin['Avg PnL']:.2f}")

# 4. Wick warning
worst_wick_bin = wick_analysis.loc[wick_analysis['Win Rate %'].idxmin()]
print(f"\n4. AVOID UPPER WICK > 20%")
print(f"   - Trades with wick >20% have {worst_wick_bin['Win Rate %']:.2f}% win rate")
print(f"   - Avg PnL: ${worst_wick_bin['Avg PnL']:.2f}")

print("\n" + "="*60)
