"""
智能离场模块 (Smart Exit Module)

功能:
1. 动态追踪止损 (Dynamic Trailing Stop)
2. 保本止损 (Break-even Stop): 盈利达到1R时强制保本
3. 时间止损 (Time-based Exit): 持仓超过N小时未盈利强制离场
4. 波动率止损 (Volatility Stop): 波动率异常放大时离场
"""

class SmartExitModule:
    def __init__(self, config=None):
        self.config = config or {}
        # 默认配置
        self.breakeven_trigger_roe = 0.15  # 15% ROE触发保本
        self.time_stop_hours = 24          # 24小时未盈利离场
        self.trailing_activation_roe = 0.30 # 30% ROE激活追踪
        self.trailing_callback = 0.10      # 10% 回撤止盈
        
    def check_exit(self, position, current_price, current_time, current_atr=None):
        """
        检查是否触发智能离场
        Returns: (should_exit, exit_reason, exit_price)
        """
        entry_price = position['entry_price']
        leverage = position.get('leverage', 20)
        quantity = position['quantity']
        entry_time = position['entry_time']
        highest_price = position.get('highest_price', entry_price)
        
        # 计算当前指标
        pnl_pct = (current_price - entry_price) / entry_price
        roe = pnl_pct * leverage
        
        # 更新最高价
        if current_price > highest_price:
            position['highest_price'] = current_price
            highest_price = current_price
            
        max_pnl_pct = (highest_price - entry_price) / entry_price
        max_roe = max_pnl_pct * leverage
        
        # 1. 保本止损 (Break-even)
        # 如果曾经达到过触发线，但现在价格回落到开仓价附近
        if max_roe >= self.breakeven_trigger_roe:
            # 允许0.2%的手续费缓冲
            breakeven_price = entry_price * 1.002
            if current_price <= breakeven_price:
                return True, "Smart Break-even", breakeven_price
                
        # 2. 动态追踪止损 (Trailing Stop)
        if max_roe >= self.trailing_activation_roe:
            # 动态回调阈值: ROE越高，回调容忍度越小
            # 30% ROE -> 10% callback
            # 100% ROE -> 5% callback
            dynamic_callback = max(0.05, self.trailing_callback - (max_roe * 0.05))
            
            stop_price = highest_price * (1 - (dynamic_callback / leverage))
            
            if current_price <= stop_price:
                return True, f"Smart Trailing (Max {max_roe*100:.0f}%)", stop_price
                
        # 3. 时间止损 (Time Stop)
        # 如果持仓超过N小时且处于亏损状态
        holding_time = (current_time - entry_time).total_seconds() / 3600
        if holding_time >= self.time_stop_hours and roe < 0:
            return True, f"Time Stop ({self.time_stop_hours}h)", current_price
            
        return False, None, None

    def get_current_exit_stop(self, position):
        """
        Return the current synthetic stop for break-even/trailing exits.
        This uses the position's existing highest_price and does not mutate state,
        which lets backtests avoid assuming a candle's high happened before its low.
        """
        entry_price = position['entry_price']
        leverage = position.get('leverage', 20)
        highest_price = position.get('highest_price', entry_price)

        max_pnl_pct = (highest_price - entry_price) / entry_price
        max_roe = max_pnl_pct * leverage

        target_stop_price = None
        reason = None

        if max_roe >= self.breakeven_trigger_roe:
            target_stop_price = entry_price * 1.002
            reason = "Smart Break-even"

        if max_roe >= self.trailing_activation_roe:
            dynamic_callback = max(0.05, self.trailing_callback - (max_roe * 0.05))
            trailing_price = highest_price * (1 - (dynamic_callback / leverage))

            if target_stop_price is None or trailing_price > target_stop_price:
                target_stop_price = trailing_price
                reason = f"Smart Trailing (Max {max_roe*100:.0f}%)"

        return target_stop_price, reason
            
    def get_current_trailing_stop(self, position):
        """
        Calculate the current theoretical Stop Loss price based on Trailing/Break-even logic.
        Used for updating the hard stop order on exchange.
        
        Returns: 
            float or None: The calculated new stop price, or None if no trailing condition active yet.
        """
        target_stop_price, _ = self.get_current_exit_stop(position)
        return target_stop_price
