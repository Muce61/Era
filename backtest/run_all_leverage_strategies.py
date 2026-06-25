"""
批量回测所有动态杠杆策略

对比基线与各种动态杠杆策略的表现
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.dynamic_leverage_engine import DynamicLeverageBacktestEngine
from utils.backtest_metrics import calculate_comprehensive_metrics, print_metrics_report, generate_comparison_table


def main():
    print("="*80)
    print("动态杠杆策略批量回测 (30天)")
    print("初始资金: 100 USDT")
    print("数据集: 精选50币种")
    print("="*80)
    
    # 定义要测试的策略
    strategies = [
        ('fixed', '基线固定20×杠杆'),
        ('volatility', '波动率调整动态杠杆'),
        ('signal_confidence', '信号置信度驱动动态杠杆'),
        ('risk_parity', '风险平价动态杠杆'),
        ('trend', '趋势确认动态杠杆'),
    ]
    
    results = {}
    
    for strategy_name, strategy_label in strategies:
        print(f"\n\n{'='*80}")
        print(f"开始回测: {strategy_label}")
        print(f"{'='*80}\n")
        
        try:
            # 创建回测引擎
            engine = DynamicLeverageBacktestEngine(
                leverage_strategy=strategy_name,
                initial_balance=100
            )
            
            # 运行30天回测
            engine.run(days=30)
            
            # 计算指标
            metrics = calculate_comprehensive_metrics(
                engine.trades,
                engine.initial_balance,
                engine.balance
            )
            
            # 打印报告
            print_metrics_report(metrics, strategy_label)
            
            # 保存结果
            results[strategy_label] = metrics
            
        except Exception as e:
            print(f"❌ 策略 {strategy_label} 回测失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 生成对比表格
    if results:
        print("\n\n" + "="*80)
        print("策略对比总结")
        print("="*80 + "\n")
        
        comparison_table = generate_comparison_table(results)
        print(comparison_table)
        
        # 保存到文件
        output_file = Path("backtest_results/leverage_strategies_comparison.md")
        output_file.parent.mkdir(exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# 动态杠杆策略对比结果\n\n")
            f.write("## 测试配置\n\n")
            f.write("- 初始资金: 100 USDT\n")
            f.write("- 回测周期: 30天\n")
            f.write("- 数据集: 精选50币种\n\n")
            f.write("## 对比表格\n\n")
            f.write(comparison_table)
            f.write("\n\n## 详细指标\n\n")
            
            for strategy_name, metrics in results.items():
                f.write(f"### {strategy_name}\n\n")
                for key, value in metrics.items():
                    f.write(f"- **{key}**: {value}\n")
                f.write("\n")
        
        print(f"\n✅ 结果已保存到: {output_file}")


if __name__ == "__main__":
    main()
