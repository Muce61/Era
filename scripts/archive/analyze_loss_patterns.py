import pandas as pd
import numpy as np
from datetime import timedelta

def analyze_period(filename, period_name):
    print(f"\n{'='*60}")
    print(f"{period_name} 亏损分析")
    print('='*60)
    
    # Load data
    df = pd.read_csv(filename)
    
    # Convert duration to timedelta if it's a string
    if 'duration' in df.columns and df['duration'].dtype == 'object':
        df['duration'] = pd.to_timedelta(df['duration'])
    
    # Separate wins and losses
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    
    print(f"\n📊 基础统计:")
    print(f"总交易数: {len(df)}")
    print(f"盈利单: {len(wins)} ({len(wins)/len(df)*100:.1f}%)")
    print(f"亏损单: {len(losses)} ({len(losses)/len(df)*100:.1f}%)")
    
    # Loss reasons
    print(f"\n❌ 亏损原因分布:")
    loss_reasons = losses['reason'].value_counts()
    for reason, count in loss_reasons.items():
        pct = count / len(losses) * 100
        avg_loss = losses[losses['reason'] == reason]['pnl'].mean()
        print(f"  {reason}: {count}单 ({pct:.1f}%), 平均亏损: ${avg_loss:.2f}")
    
    # Top losing symbols
    print(f"\n💸 亏损最多的币种 (Top 10):")
    loss_by_symbol = losses.groupby('symbol').agg({
        'pnl': ['count', 'sum', 'mean']
    }).sort_values(('pnl', 'sum'))
    
    for i, (symbol, row) in enumerate(loss_by_symbol.head(10).iterrows(), 1):
        count = int(row[('pnl', 'count')])
        total = row[('pnl', 'sum')]
        avg = row[('pnl', 'mean')]
        print(f"  {i}. {symbol}: {count}次亏损, 累计${total:.2f}, 平均${avg:.2f}")
    
    # Duration analysis
    if 'duration' in df.columns:
        print(f"\n⏱️ 持仓时间对比:")
        win_dur = wins['duration'].mean()
        loss_dur = losses['duration'].mean()
        print(f"  盈利单平均持仓: {win_dur}")
        print(f"  亏损单平均持仓: {loss_dur}")
        
        # Quick losses (< 15 min)
        quick_losses = losses[losses['duration'] < timedelta(minutes=15)]
        print(f"  快速止损 (<15分钟): {len(quick_losses)}单 ({len(quick_losses)/len(losses)*100:.1f}%%)")
    
    # PnL comparison
    print(f"\n💰 盈亏对比:")
    print(f"  盈利单平均: ${wins['pnl'].mean():.2f}")
    print(f"  亏损单平均: ${losses['pnl'].mean():.2f}")
    print(f"  盈亏比 (平均盈利/平均亏损): {abs(wins['pnl'].mean() / losses['pnl'].mean()):.2f}:1")
    
    # Identify "repeat offenders" - symbols that lose frequently
    print(f"\n⚠️ 高频亏损币种 (亏损≥3次):")
    high_freq_losers = loss_by_symbol[loss_by_symbol[('pnl', 'count')] >= 3]
    for symbol, row in high_freq_losers.iterrows():
        count = int(row[('pnl', 'count')])
        total = row[('pnl', 'sum')]
        # Check win rate for this symbol
        symbol_trades = df[df['symbol'] == symbol]
        symbol_wins = len(symbol_trades[symbol_trades['pnl'] > 0])
        symbol_total = len(symbol_trades)
        win_rate = symbol_wins / symbol_total * 100 if symbol_total > 0 else 0
        print(f"  {symbol}: {count}次亏损/{symbol_total}次交易 (胜率{win_rate:.0f}%), 累计亏${abs(total):.2f}")
    
    return df, wins, losses

# Analyze all periods
df_30d, wins_30d, losses_30d = analyze_period('backtest_trades_30d.csv', '30天回测')
df_15d, wins_15d, losses_15d = analyze_period('backtest_trades_15d.csv', '15天回测')
df_7d, wins_7d, losses_7d = analyze_period('backtest_trades_7d.csv', '7天回测')

# Cross-period analysis
print(f"\n\n{'='*60}")
print("跨周期综合分析")
print('='*60)

# Find consistently bad symbols
all_losses = pd.concat([losses_30d, losses_15d, losses_7d])
worst_symbols = all_losses.groupby('symbol')['pnl'].agg(['count', 'sum']).sort_values('sum').head(15)

print(f"\n🔴 跨周期最差币种 (所有回测累计):")
for i, (symbol, row) in enumerate(worst_symbols.iterrows(), 1):
    print(f"  {i}. {symbol}: {int(row['count'])}次亏损, 累计亏${abs(row['sum']):.2f}")

# Liquidation analysis
all_liquidations = all_losses[all_losses['reason'] == 'LIQUIDATION']
print(f"\n💥 强平分析:")
print(f"  总强平次数: {len(all_liquidations)}")
print(f"  强平占所有亏损比例: {len(all_liquidations)/len(all_losses)*100:.1f}%")
print(f"  平均强平损失: ${all_liquidations['pnl'].mean():.2f}")

# Recommendations
print(f"\n\n{'='*60}")
print("💡 优化建议")
print('='*60)

print("\n1. 规避高频亏损币种:")
high_risk_symbols = worst_symbols.head(5).index.tolist()
print(f"   建议避开: {', '.join(high_risk_symbols)}")

print("\n2. 强平风险过高:")
liquidation_rate = len(all_liquidations) / len(all_losses) * 100
if liquidation_rate > 50:
    print(f"   ⚠️ {liquidation_rate:.0f}%的亏损来自强平，说明止损距离太小或杠杆太高")
    print("   建议: 考虑降低杠杆至 20x-30x 或放宽止损至 2%")

print("\n3. 币种筛选:")
print("   某些币种波动过于激烈，建议增加币种质量过滤:")
print("   - 避开上市<30天的新币")
print("   - 避开24h波动率>50%的极端币")
print("   - 优先选择成交量排名前50的主流币")

print("\n分析完成。详细数据已保存在各 CSV 文件中。")
