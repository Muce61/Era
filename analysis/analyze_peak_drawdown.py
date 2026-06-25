"""
峰值回撤深度分析
分析资金从峰值到低谷的连续止损特征
"""

import pandas as pd
import numpy as np
from datetime import datetime
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

def analyze_peak_drawdown():
    # 加载交易数据
    trades = pd.read_csv('backtest_results/csv/backtest_trades_november.csv')
    trades['exit_time'] = pd.to_datetime(trades['exit_time'])
    
    print("="*80)
    print("📈 资金曲线峰值回撤分析")
    print("="*80)
    
    # 找到峰值
    max_balance = trades['balance_after'].max()
    max_balance_idx = trades['balance_after'].idxmax()
    max_balance_time = trades.loc[max_balance_idx, 'exit_time']
    
    print(f"\n💰 峰值信息:")
    print(f"  最高余额: ${max_balance:.2f}")
    print(f"  达到时间: {max_balance_time}")
    print(f"  交易序号: #{max_balance_idx + 1}")
    
    # 找到峰值后的最低点
    post_peak_trades = trades.loc[max_balance_idx:]
    min_balance_post_peak = post_peak_trades['balance_after'].min()
    min_balance_idx = post_peak_trades['balance_after'].idxmin()
    min_balance_time = trades.loc[min_balance_idx, 'exit_time']
    
    drawdown = (max_balance - min_balance_post_peak) / max_balance * 100
    
    print(f"\n📉 回撤信息:")
    print(f"  最低余额: ${min_balance_post_peak:.2f}")
    print(f"  回撤时间: {min_balance_time}")
    print(f"  最大回撤: {drawdown:.2f}%")
    print(f"  回撤期间交易数: {min_balance_idx - max_balance_idx}")
    
    # 分析峰值后的交易
    drawdown_period = trades.loc[max_balance_idx:min_balance_idx]
    
    print(f"\n🔍 回撤期间统计:")
    print(f"  总交易数: {len(drawdown_period)}")
    
    losses = drawdown_period[drawdown_period['pnl'] < 0]
    wins = drawdown_period[drawdown_period['pnl'] > 0]
    
    print(f"  亏损笔数: {len(losses)}")
    print(f"  盈利笔数: {len(wins)}")
    print(f"  胜率: {len(wins) / len(drawdown_period) * 100:.2f}%")
    print(f"  总亏损: ${losses['pnl'].sum():.2f}")
    print(f"  总盈利: ${wins['pnl'].sum():.2f}")
    print(f"  净亏损: ${drawdown_period['pnl'].sum():.2f}")
    
    # 识别连续止损
    print(f"\n⚠️ 连续止损分析:")
    consecutive_losses = []
    current_streak = []
    
    for idx, row in drawdown_period.iterrows():
        if row['pnl'] < 0:
            current_streak.append(row)
        else:
            if len(current_streak) >= 3:
                consecutive_losses.append(current_streak.copy())
            current_streak = []
    
    if len(current_streak) >= 3:
        consecutive_losses.append(current_streak)
    
    print(f"  发现 {len(consecutive_losses)} 个连续止损段 (>=3笔)")
    
    # 分析每个连续止损段
    for i, streak in enumerate(consecutive_losses[:5], 1):  # 只显示前5个
        streak_df = pd.DataFrame(streak)
        print(f"\n  连续止损段 #{i}:")
        print(f"    笔数: {len(streak)}")
        print(f"    时间: {streak[0]['exit_time']} ~ {streak[-1]['exit_time']}")
        print(f"    总亏损: ${streak_df['pnl'].sum():.2f}")
        print(f"    平均RSI: {streak_df['rsi'].mean():.2f}")
        print(f"    平均ADX: {streak_df['adx'].mean():.2f}")
        print(f"    平均成交量倍数: {streak_df['volume_ratio'].mean():.2f}")
        print(f"    主要币种: {streak_df['symbol'].value_counts().head(3).to_dict()}")
    
    # 分析止损特征（峰值后所有亏损）
    print(f"\n📊 亏损交易特征分析 (峰值后):")
    
    print(f"\n  RSI分布:")
    print(f"    平均值: {losses['rsi'].mean():.2f}")
    print(f"    中位数: {losses['rsi'].median():.2f}")
    print(f"    <70: {(losses['rsi'] < 70).sum()} 笔 ({(losses['rsi'] < 70).sum() / len(losses) * 100:.1f}%)")
    print(f"    70-80: {((losses['rsi'] >= 70) & (losses['rsi'] < 80)).sum()} 笔")
    print(f"    80-90: {((losses['rsi'] >= 80) & (losses['rsi'] < 90)).sum()} 笔")
    print(f"    >90: {(losses['rsi'] >= 90).sum()} 笔")
    
    print(f"\n  ADX分布:")
    print(f"    平均值: {losses['adx'].mean():.2f}")
    print(f"    <25: {(losses['adx'] < 25).sum()} 笔 (弱趋势)")
    print(f"    25-50: {((losses['adx'] >= 25) & (losses['adx'] < 50)).sum()} 笔 (中等趋势)")
    print(f"    >50: {(losses['adx'] >= 50).sum()} 笔 (强趋势)")
    
    print(f"\n  成交量倍数:")
    print(f"    平均值: {losses['volume_ratio'].mean():.2f}")
    print(f"    <2: {(losses['volume_ratio'] < 2).sum()} 笔")
    print(f"    2-4: {((losses['volume_ratio'] >= 2) & (losses['volume_ratio'] < 4)).sum()} 笔")
    print(f"    >4: {(losses['volume_ratio'] >= 4).sum()} 笔")
    
    # 时间分析
    losses_with_hour = losses.copy()
    losses_with_hour['hour'] = pd.to_datetime(losses_with_hour['exit_time']).dt.hour
    
    print(f"\n  时间分布 (Top 5):")
    hour_counts = losses_with_hour['hour'].value_counts().head(5)
    for hour, count in hour_counts.items():
        print(f"    {hour:02d}:00 - {count} 笔 ({count/len(losses)*100:.1f}%)")
    
    # 币种分析
    print(f"\n  高频止损币种 (Top 10):")
    symbol_counts = losses['symbol'].value_counts().head(10)
    for symbol, count in symbol_counts.items():
        avg_loss = losses[losses['symbol'] == symbol]['pnl'].mean()
        print(f"    {symbol}: {count} 笔, 平均亏损 ${avg_loss:.2f}")
    
    # 做空可行性分析
    print(f"\n" + "="*80)
    print(f"💡 做空策略可行性分析")
    print("="*80)
    
    # 假设在峰值后的所有亏损多头变成做空
    print(f"\n  假设场景: 在亏损信号出现时改为做空")
    print(f"  注意: 这是理想化的回测偏见，实际中无法预知哪些信号会亏损")
    
    # 检查市场趋势
    print(f"\n  市场趋势分析 (峰值后):")
    # 使用BTC作为市场代理
    btc_trades = drawdown_period[drawdown_period['symbol'].str.contains('BTC', na=False)]
    if len(btc_trades) > 0:
        print(f"    BTC交易数: {len(btc_trades)}")
        print(f"    BTC平均PnL: ${btc_trades['pnl'].mean():.2f}")
    
    # 分析价格趋势（通过entry vs exit price）
    avg_price_change = ((losses['exit_price'] - losses['entry_price']) / losses['entry_price'] * 100).mean()
    print(f"    亏损交易平均价格变化: {avg_price_change:.2f}%")
    
    if avg_price_change < -0.5:
        print(f"    ✅ 趋势判断: 下跌市，做空可能有效")
    else:
        print(f"    ⚠️  趋势判断: 震荡市，做空效果不确定")
    
    # 保存详细数据
    drawdown_period.to_csv('backtest_results/csv/peak_drawdown_trades.csv', index=False)
    print(f"\n✅ 回撤期间交易已保存至: backtest_results/csv/peak_drawdown_trades.csv")
    
    return {
        'max_balance': max_balance,
        'max_balance_time': max_balance_time,
        'drawdown_pct': drawdown,
        'losses': losses,
        'consecutive_losses': consecutive_losses
    }

if __name__ == "__main__":
    analyze_peak_drawdown()
