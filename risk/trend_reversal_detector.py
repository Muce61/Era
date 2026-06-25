"""
趋势反转检测与停损保护模块
Trend Reversal Detection & Capital Protection

功能:
1. 检测连续止损
2. 识别市场趋势反转
3. 暂停开仓保护资金
4. (可选) 切换做空模式
"""

import json
import os

class TrendReversalDetector:
    def __init__(self, state_file="logs/trend_detector_state.json"):
        self.state_file = state_file
        self.recent_trades = []  # 最近交易记录
        self.pause_long = False  # 是否暂停多头
        self.enable_short = False  # 是否启用做空
        
        # Load state if exists
        self.load_state()
        
    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.recent_trades = data.get('recent_trades', [])
                    self.pause_long = data.get('pause_long', False)
                    # self.enable_short = data.get('enable_short', False) # Optional
            except Exception as e:
                print(f"Failed to load trend detector state: {e}")

    def save_state(self):
        try:
            data = {
                'recent_trades': self.recent_trades,
                'pause_long': self.pause_long
            }
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(data, f, default=str) # default=str for datetime objects if any
        except Exception as e:
            print(f"Failed to save trend detector state: {e}")
        
    def add_trade_result(self, symbol, pnl, timestamp):
        """记录交易结果"""
        self.recent_trades.append({
            'symbol': symbol,
            'pnl': pnl,
            'timestamp': timestamp
        })
        
        # 只保留最近20笔
        if len(self.recent_trades) > 20:
            self.recent_trades.pop(0)
            
        # Save state after update
        self.save_state()
    
    def check_consecutive_losses(self, window=5):
        """检测连续止损"""
        if len(self.recent_trades) < window:
            return False
        
        recent = self.recent_trades[-window:]
        loss_count = sum(1 for t in recent if t['pnl'] < 0)
        
        # 5笔中有4笔止损
        return loss_count >= 4
    
    def calculate_recent_winrate(self, window=10):
        """计算最近胜率"""
        if len(self.recent_trades) < window:
            return 0.5
        
        recent = self.recent_trades[-window:]
        wins = sum(1 for t in recent if t['pnl'] > 0)
        return wins / len(recent)
    
    def detect_trend_reversal(self):
        """检测趋势反转信号"""
        # 策略1: 连续止损
        if self.check_consecutive_losses(window=5):
            return True, "连续止损 (5笔中4笔亏损)"
        
        # 策略2: 胜率骤降
        recent_wr = self.calculate_recent_winrate(window=10)
        if recent_wr < 0.25:
            return True, f"胜率骤降 ({recent_wr*100:.1f}%)"
        
        # 策略3: 净亏损过大
        if len(self.recent_trades) >= 10:
            recent_pnl = sum(t['pnl'] for t in self.recent_trades[-10:])
            if recent_pnl < 0:  # 最近10笔净亏损
                return True, f"净亏损 (${recent_pnl:.2f})"
        
        return False, ""
    
    def should_pause_trading(self, current_balance, peak_balance):
        """判断是否应该暂停交易"""
        # 检测趋势反转
        is_reversal, reason = self.detect_trend_reversal()
        
        if is_reversal:
            if not self.pause_long:
                # print(f"⚠️ [TrendDetector] 检测到趋势反转: {reason} -> 暂停开仓")
                self.pause_long = True
                self.save_state() # SAVE STATE
            return True
        
        # 检测大幅回撤
        if peak_balance > 0:
            drawdown = (peak_balance - current_balance) / peak_balance
            if drawdown > 0.30:  # 回撤超过30%
                if not self.pause_long:
                    # print(f"⚠️ [TrendDetector] 回撤过大 ({drawdown*100:.1f}%) -> 暂停开仓")
                    self.pause_long = True
                    self.save_state() # SAVE STATE
                return True
        
        return False
    
    def check_recovery(self):
        """检查是否恢复正常，可以重新开仓"""
        if not self.pause_long:
            return True
        
        # 恢复条件: 最近3笔中有2笔盈利
        if len(self.recent_trades) >= 3:
            recent_3 = self.recent_trades[-3:]
            wins = sum(1 for t in recent_3 if t['pnl'] > 0)
            
            if wins >= 2:
                self.pause_long = False
                # print(f"✅ 策略恢复: 最近3笔中2笔盈利，重新开启交易")
                return True
        
        return False
    
    def get_risk_multiplier(self, current_balance):
        """根据资金规模动态调整风险"""
        # 分级风险管理
        if current_balance >= 1000:
            return 0.5  # 大资金时风险减半
        elif current_balance >= 500:
            return 0.75
        elif current_balance >= 200:
            return 1.0
        else:
            return 1.2  # 小资金时风险可适当提高
    
    def get_status(self):
        """获取当前状态"""
        return {
            'pause_long': self.pause_long,
            'enable_short': self.enable_short,
            'recent_winrate': self.calculate_recent_winrate(10),
            'recent_trades_count': len(self.recent_trades)
        }

# 使用示例
"""
detector = TrendReversalDetector()

# 在每笔交易结束后
detector.add_trade_result(symbol='BTCUSDT', pnl=-10.5, timestamp=current_time)

# 在开新仓前检查
if detector.should_pause_trading(current_balance=500, peak_balance=1000):
    # 跳过开仓
    continue

# 动态调整风险
risk_percent = 0.02 * detector.get_risk_multiplier(current_balance)
"""
