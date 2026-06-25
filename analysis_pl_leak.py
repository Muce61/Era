"""
盈亏泄漏分析工具 (Profit/Loss Leak Analysis)

功能:
1. 读取回测交易记录 (backtest_trades_30d.csv)
2. 按币种分类统计盈亏 (Meme vs Mainstream)
3. 按持仓时间统计盈亏
4. 按退出原因统计盈亏
5. 输出详细诊断报告
"""

import pandas as pd
import numpy as np

def analyze_leaks(csv_path='backtest_results/csv/backtest_trades_30d.csv'):
    print(f"正在分析: {csv_path}")
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print("❌ 找不到文件，请先运行回测")
        return

    if df.empty:
        print("❌ 数据为空")
        return

    # 基础数据清洗
    df['pnl'] = pd.to_numeric(df['pnl'], errors='coerce')
    df['duration'] = pd.to_timedelta(df['duration'], errors='coerce') if 'duration' in df.columns else pd.to_timedelta(0)
    
    # 1. 总体概况
    total_pnl = df['pnl'].sum()
    win_trades = df[df['pnl'] > 0]
    loss_trades = df[df['pnl'] <= 0]
    
    print("\n" + "="*60)
    print("📊 总体概况")
    print("="*60)
    print(f"总盈亏: ${total_pnl:.2f}")
    print(f"平均盈利: ${win_trades['pnl'].mean():.2f}")
    print(f"平均亏损: ${loss_trades['pnl'].mean():.2f}")
    print(f"盈亏比 (Avg Win / Avg Loss): {abs(win_trades['pnl'].mean() / loss_trades['pnl'].mean()):.2f}")

    # 2. 亏损Top 10币种 (泄漏源)
    print("\n" + "="*60)
    print("🩸 亏损最大的10个币种 (主要出血点)")
    print("="*60)
    coin_stats = df.groupby('symbol')['pnl'].agg(['sum', 'count', 'mean']).sort_values('sum')
    print(coin_stats.head(10))
    
    # 3. 盈利Top 10币种
    print("\n" + "="*60)
    print("💰 盈利最大的10个币种")
    print("="*60)
    print(coin_stats.tail(10).sort_values('sum', ascending=False))

    # 4. 退出原因分析
    if 'exit_reason' in df.columns: # 兼容旧CSV可能没有此字段
        print("\n" + "="*60)
        print("🚪 退出原因分析")
        print("="*60)
        reason_stats = df.groupby('exit_reason')['pnl'].agg(['sum', 'count', 'mean'])
        print(reason_stats)

    # 5. 极端亏损分析 (亏损超过平均亏损2倍的交易)
    avg_loss = loss_trades['pnl'].mean()
    extreme_losses = df[df['pnl'] < avg_loss * 2]
    
    print("\n" + "="*60)
    print(f"⚠️ 极端亏损交易 (亏损 > ${abs(avg_loss*2):.2f})")
    print("="*60)
    print(f"数量: {len(extreme_losses)}")
    if not extreme_losses.empty:
        print(extreme_losses[['symbol', 'pnl', 'exit_reason']].head(10))

if __name__ == "__main__":
    analyze_leaks()
