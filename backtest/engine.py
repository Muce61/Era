import pandas as pd
from strategy.momentum import MomentumStrategy
from risk.manager import RiskManager
from config.settings import Config

class BacktestEngine:
    def __init__(self, initial_balance=10000):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions = [] # List of active positions
        self.trades = [] # History of closed trades
        self.strategy = MomentumStrategy()
        self.risk_manager = RiskManager()
        self.config = Config()
        
    def run(self, data_feed):
        """
        Run backtest on a dictionary of DataFrames {symbol: df}
        """
        # We need to simulate time.
        # Merge all dataframes by timestamp? 
        # Or just iterate symbol by symbol? 
        # For "Top Gainer" logic, we need cross-sectional data at each timestamp.
        # This is complex for a simple backtest.
        
        # Simplified approach: 
        # 1. Iterate through each symbol's history independently (assuming no capital constraint conflict for now).
        # 2. Or, better: Iterate timestamp by timestamp across all symbols.
        
        # Let's go with independent symbol backtest for validation first.
        
        print(f"Starting Backtest with ${self.initial_balance}...")
        
        for symbol, df in data_feed.items():
            self._backtest_symbol(symbol, df)
            
        self._generate_report()

    def _backtest_symbol(self, symbol, df):
        position = None
        highest_price = 0.0
        
        # Iterate through candles
        # Need window for strategy
        window_size = 50
        
        for i in range(window_size, len(df)):
            current_slice = df.iloc[i-window_size:i+1]
            current_candle = df.iloc[i]
            timestamp = current_candle['timestamp']
            price = current_candle['close']
            
            # Manage Open Position
            if position:
                # Update Highest Price
                highest_price = max(highest_price, price)
                
                # Check Stop Loss
                if price <= position['stop_loss']:
                    self._close_position(position, price, timestamp, 'Stop Loss')
                    position = None
                    continue
                    
                # Check Trailing Stop
                triggered, exit_price = self.risk_manager.check_trailing_stop(
                    price, highest_price, position['entry_price'], 'LONG'
                )
                if triggered:
                    self._close_position(position, exit_price, timestamp, 'Trailing Stop')
                    position = None
                    continue
                    
            # Look for New Entry
            else:
                signal = self.strategy.check_signal(symbol, current_slice)
                if signal and signal['side'] == 'LONG':
                    # Calculate Size & SL
                    stop_loss = self.risk_manager.calculate_stop_loss(current_slice, price, 'LONG')
                    quantity = self.risk_manager.calculate_position_size(self.balance, price, stop_loss)
                    
                    position = {
                        'symbol': symbol,
                        'entry_price': price,
                        'quantity': quantity,
                        'stop_loss': stop_loss,
                        'entry_time': timestamp,
                        'leverage': self.config.LEVERAGE
                    }
                    highest_price = price
                    # Deduct Fee (0.05% Taker)
                    fee = (price * quantity) * 0.0005
                    self.balance -= fee

    def _close_position(self, position, exit_price, timestamp, reason):
        # Calculate PnL
        # Long PnL = (Exit - Entry) * Quantity
        pnl = (exit_price - position['entry_price']) * position['quantity']
        
        # Deduct Fee (0.05% Taker)
        fee = (exit_price * position['quantity']) * 0.0005
        net_pnl = pnl - fee
        
        self.balance += net_pnl
        
        trade_record = {
            'symbol': position['symbol'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'entry_time': position['entry_time'],
            'exit_time': timestamp,
            'pnl': net_pnl,
            'reason': reason
        }
        self.trades.append(trade_record)

    def _generate_report(self):
        print("-" * 30)
        print("Backtest Results")
        print("-" * 30)
        print(f"Final Balance: ${self.balance:.2f}")
        print(f"Total Return: {((self.balance - self.initial_balance)/self.initial_balance)*100:.2f}%")
        print(f"Total Trades: {len(self.trades)}")
        
        if self.trades:
            wins = [t for t in self.trades if t['pnl'] > 0]
            win_rate = len(wins) / len(self.trades) * 100
            print(f"Win Rate: {win_rate:.2f}%")
