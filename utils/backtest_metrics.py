"""
回测度量标准计算模块

提供统一的绩效指标计算
"""

import numpy as np
import pandas as pd


def calculate_comprehensive_metrics(trades, initial_balance, final_balance):
    """
    计算完整的回测指标
    
    Args:
        trades: 交易记录列表
        initial_balance: 初始资金
        final_balance: 最终资金
        
    Returns:
        dict: 包含所有关键指标的字典
    """
    metrics = {}
    
    if not trades:
        # 无交易情况
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_return_pct': 0,
            'win_rate': 0,
            'max_profit_pct': 0,
            'min_profit_pct': 0,
            'avg_profit_pct': 0,
            'profit_factor': 0,
            'max_drawdown': 0
        }
    
    # 基础统计
    metrics['total_trades'] = len(trades)
    metrics['winning_trades'] = len([t for t in trades if t['pnl'] > 0])
    metrics['losing_trades'] = len([t for t in trades if t['pnl'] <= 0])
    
    # 收益率
    metrics['total_return_pct'] = ((final_balance - initial_balance) / initial_balance) * 100
    
    # 胜率
    metrics['win_rate'] = (metrics['winning_trades'] / metrics['total_trades'] * 100) if metrics['total_trades'] > 0 else 0
    
    # 盈亏统计 (转换为百分比)
    winning_pnls = [t['pnl'] for t in trades if t['pnl'] > 0]
    losing_pnls = [t['pnl'] for t in trades if t['pnl'] <= 0]
    
    # 最大/最小/平均利润(百分比)
    if winning_pnls:
        # 估算单笔利润率: PnL / (初始资金 * 交易序号的估算权重)
        # 简化: PnL / 初始资金作为近似
        metrics['max_profit_pct'] = (max(winning_pnls) / initial_balance) * 100
        metrics['avg_win_pct'] = (np.mean(winning_pnls) / initial_balance) * 100
    else:
        metrics['max_profit_pct'] = 0
        metrics['avg_win_pct'] = 0
    
    if losing_pnls:
        metrics['min_profit_pct'] = (min(losing_pnls) / initial_balance) * 100
        metrics['avg_loss_pct'] = (np.mean(losing_pnls) / initial_balance) * 100
    else:
        metrics['min_profit_pct'] = 0
        metrics['avg_loss_pct'] = 0
    
    # 平均利润率 (所有交易)
    all_pnls = [t['pnl'] for t in trades]
    metrics['avg_profit_pct'] = (np.mean(all_pnls) / initial_balance) * 100
    
    # 盈亏比 (Profit Factor)
    total_profit = sum(winning_pnls) if winning_pnls else 0
    total_loss = abs(sum(losing_pnls)) if losing_pnls else 1
    metrics['profit_factor'] = total_profit / total_loss if total_loss != 0 else float('inf')
    
    # 最大回撤 (需要权益曲线)
    # 简化计算: 累计PnL曲线的最大回撤
    cumulative_pnl = [initial_balance]
    for trade in trades:
        cumulative_pnl.append(cumulative_pnl[-1] + trade['pnl'])
    
    equity_curve = np.array(cumulative_pnl)
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max * 100
    metrics['max_drawdown'] = abs(drawdown.min())
    
    return metrics


def print_metrics_report(metrics, strategy_name="Strategy"):
    """
    打印格式化的指标报告
    
    Args:
        metrics: 指标字典
        strategy_name: 策略名称
    """
    print(f"\n{'='*60}")
    print(f"{strategy_name} - 回测结果")
    print(f"{'='*60}")
    
    print(f"📊 总收益率: {metrics['total_return_pct']:.2f}%")
    print(f"📈 交易数量: {metrics['total_trades']}")
    print(f"✅ 盈利笔数: {metrics['winning_trades']}")
    print(f"❌ 亏损笔数: {metrics['losing_trades']}")
    print(f"🎯 胜率: {metrics['win_rate']:.2f}%")
    print(f"💰 平均利润率: {metrics['avg_profit_pct']:.2f}%")
    print(f"📈 最大利润率: {metrics['max_profit_pct']:.2f}%")
    print(f"📉 最小利润率: {metrics['min_profit_pct']:.2f}%")
    print(f"⚖️  盈亏比: {metrics['profit_factor']:.2f}")
    print(f"📉 最大回撤: {metrics['max_drawdown']:.2f}%")
    print(f"{'='*60}\n")


def generate_comparison_table(results_dict):
    """
    生成策略对比表格
    
    Args:
        results_dict: {策略名称: 指标字典} 的字典
        
    Returns:
        str: Markdown格式的对比表格
    """
    if not results_dict:
        return "无数据"
    
    # 表头
    table = "| 策略 | 月收益率 | 胜率 | 交易数 | 盈利:亏损 | 平均利润 | 最大利润 | 最小利润 | 盈亏比 | 最大回撤 |\n"
    table += "|------|----------|------|--------|-----------|----------|----------|----------|--------|----------|\n"
    
    # 数据行
    for strategy_name, metrics in results_dict.items():
        table += f"| {strategy_name} "
        table += f"| {metrics['total_return_pct']:.2f}% "
        table += f"| {metrics['win_rate']:.2f}% "
        table += f"| {metrics['total_trades']} "
        table += f"| {metrics['winning_trades']}:{metrics['losing_trades']} "
        table += f"| {metrics['avg_profit_pct']:.2f}% "
        table += f"| {metrics['max_profit_pct']:.2f}% "
        table += f"| {metrics['min_profit_pct']:.2f}% "
        table += f"| {metrics['profit_factor']:.2f} "
        table += f"| {metrics['max_drawdown']:.2f}% |\n"
    
    return table
