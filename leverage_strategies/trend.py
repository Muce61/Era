"""
趋势确认动态杠杆策略

分段建仓策略:
1. 初始试探仓位: 10x杠杆 (30%资金)
2. 趋势确认后加仓: 30x杠杆
3. 条件: 价格上涨≥2% 且创新高

目标: 在确认趋势时放大收益,不确定时控制风险
"""


class TrendModule:
    def __init__(self):
        """初始化趋势确认模块"""
        self.active_positions = {}  # 跟踪试探仓位状态
        
    def calculate(self, symbol, signal, current_price, df):
        """
        计算基于趋势确认的动态杠杆
        
        Args:
            symbol: 交易对
            signal: 信号字典
            current_price: 当前价格
            df: 历史数据DataFrame
            
        Returns:
            int: 杠杆倍数 (10 或 30)
        """
        # 检查是否已有该币种的试探仓位记录
        if symbol in self.active_positions:
            entry_price = self.active_positions[symbol]['entry_price']
            
            # 计算涨幅
            gain_pct = (current_price - entry_price) / entry_price
            
            # 检查是否创新高 (过去5根K线)
            if df is not None and len(df) >= 5:
                recent_high = df['high'].tail(5).max()
                is_new_high = current_price > recent_high
            else:
                is_new_high = False
            
            # 趋势确认条件: 涨幅≥2% 且创新高
            if gain_pct >= 0.02 and is_new_high:
                # 趋势确认,使用高杠杆
                return 30
            else:
                # 趋势未确认,维持试探仓位
                return 10
        else:
            # 首次开仓,使用试探仓位
            # 记录入场价格用于后续判断
            self.active_positions[symbol] = {
                'entry_price': current_price,
                'entry_time': signal.get('timestamp')
            }
            return 10
    
    def reset_position(self, symbol):
        """
        清除仓位记录 (平仓时调用)
        
        Args:
            symbol: 交易对
        """
        if symbol in self.active_positions:
            del self.active_positions[symbol]
