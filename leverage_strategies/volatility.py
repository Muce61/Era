"""
波动率调整动态杠杆策略

根据ATR波动率动态调整杠杆:
- 高波动 (ATR > 3%): 10x杠杆
- 中波动 (1.5% - 3%): 20x杠杆
- 低波动 (< 1.5%): 30x杠杆
"""

import pandas_ta as ta


class VolatilityModule:
    def __init__(self, atr_period=14, high_vol_threshold=0.03, low_vol_threshold=0.015):
        """
        初始化波动率调整模块
        
        Args:
            atr_period: ATR计算周期
            high_vol_threshold: 高波动阈值 (百分比)
            low_vol_threshold: 低波动阈值 (百分比)
        """
        self.atr_period = atr_period
        self.high_vol_threshold = high_vol_threshold
        self.low_vol_threshold = low_vol_threshold
        
    def calculate(self, symbol, signal, current_price, df):
        """
        计算动态杠杆
        
        Args:
            symbol: 交易对
            signal: 信号字典
            current_price: 当前价格
            df: 历史数据DataFrame
            
        Returns:
            int: 杠杆倍数 (10, 20, 或 30)
        """
        # 使用预计算的ATR (如果存在)
        if 'atr' in df.columns:
            atr = df['atr'].iloc[-1]
        else:
            # 实时计算ATR
            atr_series = ta.atr(df['high'], df['low'], df['close'], length=self.atr_period)
            atr = atr_series.iloc[-1]
        
        # 标准化为价格百分比
        atr_pct = atr / current_price
        
        # 分段调整杠杆
        if atr_pct > self.high_vol_threshold:
            # 高波动: 降低杠杆
            return 10
        elif atr_pct > self.low_vol_threshold:
            # 中等波动: 标准杠杆
            return 20
        else:
            # 低波动: 提高杠杆
            return 30
