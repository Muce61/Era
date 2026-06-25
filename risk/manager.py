import pandas_ta as ta
from config.settings import Config

class RiskManager:
    def __init__(self):
        self.config = Config()

    def calculate_position_size(self, account_balance, entry_price, stop_loss_price, leverage=None):
        """
        Calculate position size based on Fixed Risk Model with TIERED RISK.
        
        Tiered Risk Schedule:
        - Balance < $200:       2.0% Risk (Aggressive Growth)
        - Balance $200-$500:    1.5% Risk (Balanced)
        - Balance $500-$1000:   1.0% Risk (Defensive)
        - Balance > $1000:      0.5% Risk (Capital Preservation)
        """
        if entry_price == 0 or account_balance == 0 or entry_price <= stop_loss_price:
            return 0
            
        # 1. Determine Risk Percentage (Fixed 2.0% - Aggressive Mode)
        risk_pct = 0.02
            
        # 2. Calculate Risk Amount
        risk_amount = account_balance * risk_pct
        
        # 3. Calculate Risk Per Unit
        risk_per_unit = entry_price - stop_loss_price
        
        # 4. Calculate Quantity
        quantity = risk_amount / risk_per_unit
        
        # 5. Check Leverage Limit
        # Use passed leverage or default from config
        max_leverage = leverage if leverage else self.config.LEVERAGE
        max_position_value = account_balance * max_leverage
        current_position_value = quantity * entry_price
        
        if current_position_value > max_position_value:
            quantity = max_position_value / entry_price
            print(f"⚠️ Position capped by leverage {max_leverage}x")
            
        print(f"仓位计算: 余额={account_balance:.2f}, 风险等级={risk_pct*100}%, 风险金额=${risk_amount:.2f}, 数量={quantity:.6f}")
        
        return quantity

    def calculate_stop_loss(self, df, entry_price, side='LONG'):
        """
        Calculate ATR-based Stop Loss with hard cap for 50x leverage safety.
        """
        if len(df) < self.config.ATR_PERIOD:
            return entry_price * 0.98 # Fallback 2%
            
        # Calculate ATR
        atr = ta.atr(df['high'], df['low'], df['close'], length=self.config.ATR_PERIOD)
        current_atr = atr.iloc[-1]
        
        sl_distance = current_atr * self.config.ATR_MULTIPLIER
        
        # CRITICAL: Cap stop loss at 1.4% for 50x leverage (liquidation at ~1.5%)
        max_stop_distance = entry_price * self.config.STOP_LOSS_CAP_PERCENT
        sl_distance = min(sl_distance, max_stop_distance)
        
        if side == 'LONG':
            return entry_price - sl_distance
        else:
            return entry_price + sl_distance

    def check_trailing_stop(self, current_price, highest_price, entry_price, side='LONG'):
        """
        Check if trailing stop is triggered.
        """
        if side == 'LONG':
            # 1. Check Activation
            if highest_price >= entry_price * (1 + self.config.TRAILING_ACTIVATION):
                # 2. Check Callback
                stop_price = highest_price * (1 - self.config.TRAILING_CALLBACK)
                if current_price <= stop_price:
                    return True, stop_price
        
        return False, 0.0
