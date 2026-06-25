"""
单独运行信号置信度动态杠杆策略回测
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.dynamic_leverage_engine import DynamicLeverageBacktestEngine
from utils.backtest_metrics import calculate_comprehensive_metrics, print_metrics_report

def main():
    print("="*80)
    print("信号置信度动态杠杆 - 30天回测 (优化版: SmartExit + QualityFilter)")
    print("="*80)
    print()
    
    # 创建引擎
    engine = DynamicLeverageBacktestEngine(
        leverage_strategy='signal_confidence',
        initial_balance=100
    )
    
    # 运行30天回测
    print("正在运行30天回测 (使用新数据源)...")
    engine.run(days=30)
    
    # 计算指标
    metrics = calculate_comprehensive_metrics(
        engine.trades,
        engine.initial_balance,
        engine.balance
    )
    
    # 打印详细报告
    print_metrics_report(metrics, "信号置信度动态杠杆")
    
    # 额外输出
    print("\n" + "="*80)
    print("📊 详细指标")
    print("="*80)
    print(f"💰 最终资金: {engine.balance:.2f} USDT")
    print(f"📈 初始资金: {engine.initial_balance:.2f} USDT")
    print(f"🎯 交易胜率: {metrics['win_rate']:.2f}%")
    print(f"📊 回测最终收益率: {metrics['total_return_pct']:.2f}%")
    print(f"🔢 交易数量: {metrics['total_trades']}")
    print(f"✅ 盈利数量: {metrics['winning_trades']}")
    print(f"❌ 亏损数量: {metrics['losing_trades']}")
    print(f"📈 最大利润率: {metrics['max_profit_pct']:.2f}%")
    print(f"📉 最小利润率: {metrics['min_profit_pct']:.2f}%")
    print(f"💹 平均利润率: {metrics['avg_profit_pct']:.2f}%")
    print(f"⚖️  盈亏比: {metrics['profit_factor']:.2f}")
    print(f"📉 最大回撤: {metrics['max_drawdown']:.2f}%")
    print("="*80)

if __name__ == "__main__":
    main()
