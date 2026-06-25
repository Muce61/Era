"""
风险平价动态杠杆策略

根据币种波动率分配杠杆,使每个交易的风险贡献均等:
- 高波动币种: 降低杠杆
- 低波动币种: 提高杠杆

目标: 平衡风险敞口,降低单币种暴露
"""

import numpy as np


class RiskParityModule:
    def __init__(self, target_volatility=0.02, base_leverage=20):
        """
        初始化风险平价模块
        
        Args:
            target_volatility: 目标波动率 (默认2%日波动)
            base_leverage: 基准杠杆倍数
        """
        self.target_volatility = target_volatility
        self.base_leverage = base_leverage
        
    def calculate(self, symbol, signal, current_price, df):
        """
        计算基于风险平价的动态杠杆
        
        Args:
            symbol: 交易对
            signal: 信号字典
            current_price: 当前价格
            df: 历史数据DataFrame
            
        Returns:
            int: 杠杆倍数 (10-30)
        """
        if df is None or len(df) < 20:
            return self.base_leverage
        
        # 计算过去20日的波动率
        returns = df['close'].pct_change().dropna()
        
        if len(returns) < 20:
            return self.base_leverage
            
        # 使用最近20个交易日的波动率
        volatility = returns.tail(20).std()
        
        if volatility == 0 or np.isnan(volatility):
            return self.base_leverage
        
        # 风险平价公式: 杠杆 = 基准杠杆 * (目标波动率 / 当前波动率)
        leverage = self.base_leverage * (self.target_volatility / volatility)
        
        # 限制杠杆范围 [10, 30]
        leverage = max(10, min(30, int(leverage)))
        
        return leverage
