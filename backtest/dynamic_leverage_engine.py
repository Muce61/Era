"""
统一动态杠杆回测引擎

支持多种杠杆策略切换:
- fixed: 固定20x杠杆 (基线)
- volatility: 波动率调整动态杠杆
- signal_confidence: 信号置信度驱动动态杠杆
- risk_parity: 风险平价动态杠杆 (待实现)
- trend: 趋势确认动态杠杆 (待实现)
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine


class DynamicLeverageBacktestEngine(RealBacktestEngine):
    """
    统一的动态杠杆回测引擎
    """
    
    def __init__(self, leverage_strategy='fixed', initial_balance=100):
        """
        初始化动态杠杆回测引擎
        
        Args:
            leverage_strategy: 杠杆策略类型
                - 'fixed': 固定20x
                - 'volatility': 波动率调整
                - 'signal_confidence': 信号置信度
            initial_balance: 初始资金
        """
        super().__init__(initial_balance)
        
        self.leverage_strategy_name = leverage_strategy
        self.leverage_module = None
        
        # 加载对应的杠杆策略模块
        if leverage_strategy == 'volatility':
            from leverage_strategies.volatility import VolatilityModule
            self.leverage_module = VolatilityModule()
            print(f"📊 使用策略: 波动率调整动态杠杆")
            
        elif leverage_strategy == 'signal_confidence':
            from leverage_strategies.signal_confidence import SignalConfidenceModule
            self.leverage_module = SignalConfidenceModule()
            print(f"📊 使用策略: 信号置信度驱动动态杠杆")
            
        elif leverage_strategy == 'risk_parity':
            from leverage_strategies.risk_parity import RiskParityModule
            self.leverage_module = RiskParityModule()
            print(f"📊 使用策略: 风险平价动态杠杆")
            
        elif leverage_strategy == 'trend':
            from leverage_strategies.trend import TrendModule
            self.leverage_module = TrendModule()
            print(f"📊 使用策略: 趋势确认动态杠杆")
            
        elif leverage_strategy == 'fixed':
            self.leverage_module = None
            print(f"📊 使用策略: 基线固定20x杠杆")
            
        else:
            raise ValueError(f"未知的杠杆策略: {leverage_strategy}")
    
    def _open_position(self, symbol, price, timestamp, history_slice, metrics=None):
        """
        Override: 使用动态杠杆开仓
        """
        # 计算动态杠杆
        if self.leverage_module is None:
            leverage = 20  # 基线固定20x
        else:
            # 构造signal用于杠杆计算
            signal = {
                'symbol': symbol,
                'side': 'LONG',
                'entry_price': price,
                'timestamp': timestamp,
                'metrics': metrics or {}
            }
            
            # 使用策略模块计算杠杆
            leverage = self.leverage_module.calculate(
                symbol=symbol,
                signal=signal,
                current_price=price,
                df=history_slice if history_slice is not None else self.data_feed.get(symbol)
            )
        
        # 更新风险管理器的杠杆
        self.risk_manager.config.LEVERAGE = leverage
        
        # 计算止损
        if history_slice is not None and len(history_slice) >= 14:
            import pandas_ta as ta
            atr = ta.atr(history_slice['high'], history_slice['low'], history_slice['close'], length=14).iloc[-1]
            sl_distance = atr * 2.5
            
            # 根据杠杆调整止损上限
            if leverage >= 30:
                max_stop_distance = price * 0.025  # 30x杠杆: 2.5%止损
            elif leverage >= 20:
                max_stop_distance = price * 0.035  # 20x杠杆: 3.5%止损
            else:
                max_stop_distance = price * 0.045  # 10x杠杆: 4.5%止损
                
            sl_distance = min(sl_distance, max_stop_distance)
            stop_loss_pct = sl_distance / price
        else:
            # Fallback止损
            if leverage >= 30:
                stop_loss_pct = 0.025
            elif leverage >= 20:
                stop_loss_pct = 0.035
            else:
                stop_loss_pct = 0.045
        
        # 滑点
        slippage = 0.0005
        entry_price_with_slippage = price * (1 + slippage)
        stop_loss = entry_price_with_slippage * (1 - stop_loss_pct)
        
        # 计算仓位大小
        quantity = self.risk_manager.calculate_position_size(
            self.balance, 
            entry_price_with_slippage, 
            stop_loss
        )
        
        if quantity <= 0:
            return
        
        # 手续费
        notional = price * quantity
        fee = notional * 0.0005
        self.balance -= fee
        
        # 记录订单
        self.positions[symbol] = {
            'entry_price': entry_price_with_slippage,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'highest_price': entry_price_with_slippage,
            'entry_time': timestamp,
            'leverage': leverage,  # 记录实际使用的杠杆
            'metrics': metrics or {}
        }
        
        print(f"[{timestamp}] OPEN LONG {symbol} @ {entry_price_with_slippage:.4f} | Leverage: {leverage}x | SL: {stop_loss:.4f} | Size: {quantity:.2f}")
