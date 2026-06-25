import sys
from pathlib import Path
import pandas as pd
import pandas_ta as ta

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from strategy.momentum import MomentumStrategy

class DebugStrategy(MomentumStrategy):
    def check_signal_debug(self, symbol, df):
        if df.empty or len(df) < 20:
            return "Not enough data"
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 1. Breakout Check
        if current['close'] <= prev['high']:
            return f"No Breakout (Close {current['close']:.4f} <= PrevHigh {prev['high']:.4f})"
        
        # 2. Volume Check
        avg_vol = df['volume'].iloc[-21:-1].mean()
        vol_ratio = current['volume'] / avg_vol if avg_vol > 0 else 0
        if current['volume'] < 2.0 * avg_vol:
            return f"Low Volume (Ratio {vol_ratio:.2f} < 2.0)"
        
        # 3. RSI Check
        rsi = ta.rsi(df['close'], length=14).iloc[-1]
        if not (55 <= rsi <= 90):
            return f"RSI Out of Range ({rsi:.2f})"
            
        return "SIGNAL MATCH!"

def debug_coin(symbol, file_path):
    print(f"\n🔍 Analyzing {symbol}...")
    
    # Load data
    df_1m = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
    df_15m = df_1m.resample('15min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    })
    df_15m.dropna(inplace=True)
    
    strategy = DebugStrategy()
    
    # Scan last 1000 candles
    signals_found = 0
    reasons = {}
    
    for i in range(50, len(df_15m)):
        window = df_15m.iloc[:i+1]
        result = strategy.check_signal_debug(symbol, window)
        
        if result == "SIGNAL MATCH!":
            print(f"✅ SIGNAL at {window.index[-1]}: Price {window.iloc[-1]['close']}")
            signals_found += 1
        else:
            reason_key = result.split('(')[0].strip()
            reasons[reason_key] = reasons.get(reason_key, 0) + 1
            
    print(f"\n📊 Summary for {symbol}:")
    print(f"Total Candles: {len(df_15m)}")
    print(f"Signals Found: {signals_found}")
    print("Rejection Reasons:")
    for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {reason}: {count}")

def main():
    # Test on a few known volatile coins
    data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
    test_coins = ["PIPPINUSDT", "DOGEUSDT", "PEPEUSDT"]
    
    found = 0
    for file_path in data_dir.glob("*.csv"):
        symbol = file_path.stem.replace("USDT", "") + "USDT" # Normalize
        # Just pick the first 3 files to test if specific ones aren't found easily
        if found < 3:
            debug_coin(file_path.stem, file_path)
            found += 1
        else:
            break

if __name__ == "__main__":
    main()
