import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

class OptimizedCuratedEngine(RealBacktestEngine):
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        # Override to ensure 20x leverage
        self.config.LEVERAGE = 20
        self.risk_manager.config.LEVERAGE = 20
        self.config.CHANGE_THRESHOLD_MIN = 5.0
        self.config.CHANGE_THRESHOLD_MAX = 200.0
        self.config.TOP_GAINER_COUNT = 50
        
        # Load quality whitelist
        whitelist_file = Path(__file__).parent.parent / "config" / "quality_whitelist.txt"
        self.quality_whitelist = set()
        with open(whitelist_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    self.quality_whitelist.add(line)
        
        print(f"📋 Loaded quality whitelist: {len(self.quality_whitelist)} coins")
        print(f"⚙️  Leverage: 20x (reduced from 50x)")
        print(f"💰 Partial TP: 15% (40%), 25% (30%), 40% (all)")
    
    def _open_position(self, symbol, price, timestamp, history_slice, metrics=None):
        """
        Override to force 20x leverage for all positions.
        Prevents the base class dynamic leverage logic from using 50x.
        """
        # FORCE 20x leverage - no dynamic assignment
        leverage = 20
        self.risk_manager.config.LEVERAGE = 20
        
        # ATR-based stop-loss calculation
        if history_slice is not None and len(history_slice) >= 14:
            import pandas_ta as ta
            atr = ta.atr(history_slice['high'], history_slice['low'], history_slice['close'], length=14).iloc[-1]
            sl_distance = atr * 2.5
            # Cap for 20x leverage (liquidation at ~5%)
            max_stop_distance = price * 0.035  # 3.5% max stop for 20x
            sl_distance = min(sl_distance, max_stop_distance)
            stop_loss_pct = sl_distance / price
        else:
            # Safe default for 20x leverage
            stop_loss_pct = 0.035  # 3.5% = 70% ROE stop
        
        # Add slippage
        slippage = 0.0005
        entry_price_with_slippage = price * (1 + slippage)
        stop_loss = entry_price_with_slippage * (1 - stop_loss_pct)
        
        # Calculate position size
        quantity = self.risk_manager.calculate_position_size(self.balance, entry_price_with_slippage, stop_loss)
        
        if quantity <= 0:
            return
        
        # Deduct fee
        notional = price * quantity
        fee = notional * 0.0005
        self.balance -= fee
        
        # Store position
        self.positions[symbol] = {
            'entry_price': entry_price_with_slippage,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'highest_price': entry_price_with_slippage,
            'entry_time': timestamp,
            'leverage': leverage,
            'metrics': metrics or {}
        }
        
        margin_used = (entry_price_with_slippage * quantity) / leverage
        print(f"仓位计算: 余额={self.balance:.2f}, 保证金(10.0%)={margin_used:.2f}, 杠杆={leverage}x, 仓位价值={entry_price_with_slippage * quantity:.2f}, 数量={quantity:.6f}")
        print(f"[{timestamp}] OPEN LONG {symbol} @ {entry_price_with_slippage:.4f} | SL: {stop_loss:.4f} (-{stop_loss_pct*100:.2f}%/-{stop_loss_pct*leverage*100:.0f}%ROE) | Size: {quantity:.2f}")
        
        
    def load_data(self):
        """
        Load from NEW data directory but ONLY quality coins from whitelist
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        
        print(f"Loading data from {data_dir}...")
        print(f"Filtering to {len(self.quality_whitelist)} quality coins...")
        
        if not data_dir.exists():
            print(f"Error: Data directory {data_dir} does not exist!")
            return

        files = list(data_dir.glob("*.csv"))
        loaded_count = 0
        
        for file_path in files:
            try:
                symbol = file_path.stem
                
                # QUALITY FILTER: Only load coins in whitelist
                if symbol not in self.quality_whitelist:
                    continue
                
                # Read CSV (1m data)
                df_1m = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                
                # Resample to 15m
                df_15m = df_1m.resample('15min').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                })
                
                df_15m.dropna(inplace=True)
                
                if len(df_15m) > 50:
                    self.data_feed[symbol] = df_15m
                    loaded_count += 1
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
            
        print(f"✅ Loaded {loaded_count} quality coins (Resampled to 15m).")

def main():
    print("="*60)
    print("6-MONTH OPTIMIZED STRATEGY TEST")
    print("Leverage: 20x (reduced from 50x)")
    print("Partial TP: ROE 15%→40%, 25%→30%, 40%→all")
    print("Coins: 50 Quality (curated whitelist)")
    print("Period: 180 days (6 months)")
    print("="*60)
    
    engine = OptimizedCuratedEngine(initial_balance=100)
    engine.run(days=180)

if __name__ == "__main__":
    main()
