"""
样本外回测脚本 (Out-of-Sample Backtest)

目标: 验证策略在 2025年10月 (非牛市/震荡市) 的表现
时间范围: 2025-10-01 ~ 2025-10-31
"""

import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine
from utils.backtest_metrics import calculate_comprehensive_metrics

def main():
    print("="*80)
    print("样本外压力测试: 2025年1月 - 11月 (01.01 - 11.30)")
    print("策略配置: 固定风险 2% (无守财模式) + 亏损模式过滤 + 资金回撤保护")
    print("="*80)
    
    # 初始化回测引擎
    engine = RealBacktestEngine(initial_balance=100)
    
    # Run for Jan to Nov (11 months)
    print("\n正在运行2025年1-11月份回测 (11个月)...")
    engine.run(start_date='2025-01-01', end_date='2025-11-30')
    
    # 计算指标
    metrics = calculate_comprehensive_metrics(
        engine.trades, 
        engine.initial_balance, 
        engine.balance
    )
    
    # 打印结果
    print("\n" + "="*60)
    print("样本外测试结果 (Out-of-Sample Results)")
    print("="*60)
    print(f"📊 总收益率: {metrics['total_return_pct']:.2f}%")
    print(f"📈 交易数量: {metrics['total_trades']}")
    print(f"✅ 盈利笔数: {metrics['winning_trades']}")
    print(f"❌ 亏损笔数: {metrics['losing_trades']}")
    print(f"🎯 胜率: {metrics['win_rate']:.2f}%")
    print(f"💰 平均利润率: {metrics['avg_profit_pct']:.2f}%")
    print(f"⚖️  盈亏比: {metrics['profit_factor']:.2f}")
    print(f"📉 最大回撤: {metrics['max_drawdown']:.2f}%")
    print("="*60)
    
    # 保存交易记录
    trades_df = pd.DataFrame(engine.trades)
    if not trades_df.empty:
        trades_df.to_csv('backtest_results/csv/backtest_trades_november.csv', index=False)
        print("交易记录已保存至 backtest_results/csv/backtest_trades_november.csv")

if __name__ == "__main__":
    main()
