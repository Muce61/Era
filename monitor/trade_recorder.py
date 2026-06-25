import csv
import os
from datetime import datetime
import threading

class TradeRecorder:
    def __init__(self, log_dir="logs/trades"):
        self.log_dir = log_dir
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        self.trades_file = os.path.join(log_dir, "trades.csv")
        self.orders_file = os.path.join(log_dir, "orders.csv")
        self.lock = threading.Lock()
        
        self._init_files()
        
    def _init_files(self):
        # Initialize Trades CSV
        if not os.path.exists(self.trades_file):
            with open(self.trades_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'trade_id', 'symbol', 'side', 'entry_time', 'entry_price', 
                    'quantity', 'leverage', 'signal_score', 'confidence_score',
                    'rsi', 'adx', 'volume_ratio', 'market_regime',
                    'exit_time', 'exit_price', 'exit_reason', 'pnl', 'pnl_pct', 
                    'roe', 'fees', 'holding_time_min', 'mae', 'mfe', 'efficiency'
                ])
                
        # Initialize Orders CSV
        if not os.path.exists(self.orders_file):
            with open(self.orders_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'order_id', 'symbol', 'type', 'side', 
                    'price', 'quantity', 'status', 'leverage', 'confidence_score',
                    'rsi', 'adx', 'volume_ratio', 'upper_wick_ratio'
                ])

    def log_trade_open(self, trade_data):
        """
        Log a new trade opening. 
        Note: We usually log the FULL trade row on exit, but we can log partial here 
        or maintain a separate 'active_trades.csv'. 
        For simplicity, we'll log to 'orders.csv' for entry, and 'trades.csv' on exit.
        """
        pass

    def log_trade_close(self, trade_data):
        """
        Log a completed trade to trades.csv
        """
        with self.lock:
            with open(self.trades_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    trade_data.get('trade_id', datetime.now().strftime('%Y%m%d%H%M%S')),
                    trade_data['symbol'],
                    trade_data['side'],
                    trade_data['entry_time'],
                    trade_data['entry_price'],
                    trade_data['quantity'],
                    trade_data.get('leverage', 20),
                    trade_data.get('signal_score', 0),
                    trade_data.get('confidence_score', 0),
                    trade_data.get('rsi', 0),
                    trade_data.get('adx', 0),
                    trade_data.get('volume_ratio', 0),
                    trade_data.get('market_regime', 'Unknown'),
                    trade_data['exit_time'],
                    trade_data['exit_price'],
                    trade_data['exit_reason'],
                    trade_data['pnl'],
                    trade_data['pnl_pct'],
                    trade_data['roe'],
                    trade_data.get('fees', 0),
                    trade_data.get('holding_time_min', 0),
                    trade_data.get('mae', 0),
                    trade_data.get('mfe', 0),
                    trade_data.get('efficiency', 0)
                ])

    def log_order(self, order_data):
        """
        Log an order execution (Entry, Exit, Stop Loss)
        """
        with self.lock:
            with open(self.orders_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                metrics = order_data.get('signal_metrics', {})
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    order_data.get('order_id', ''),
                    order_data['symbol'],
                    order_data['type'],
                    order_data['side'],
                    order_data['price'],
                    order_data['quantity'],
                    order_data['status'],
                    order_data.get('leverage', 20),
                    order_data.get('confidence_score', 0),
                    metrics.get('rsi', 0),
                    metrics.get('upper_wick_ratio', 0)
                ])

    # Alias for compatibility with main.py
    log_trade = log_trade_close
