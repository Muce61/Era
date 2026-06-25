import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import pytz

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[0]))

from strategy.momentum import MomentumStrategy
from data.binance_client import BinanceClient

def verify_signal(symbol, target_time_str):
    """
    Verify if a signal would be generated for a symbol at a specific time.
    """
    print(f"Verifying Signal for {symbol} at {target_time_str}")
    
    # 1. Parse Time
    # Input format: "2024-11-05 14:45:00" (UTC inferred from previous context, but user might give Beijing)
    # Let's assume input is UTC for consistency with backtest CSV
    target_time = pd.to_datetime(target_time_str)
    if target_time.tzinfo is None:
        target_time = pytz.UTC.localize(target_time)
        
    print(f"Target Time (UTC): {target_time}")
    
    # 2. Fetch Data
    # Need enough data BEFORE this time for indicators (e.g. 50-100 candles)
    client = BinanceClient()
    
    # End time needs to be the target time
    # Start time should be ~200 candles before
    end_ts = int(target_time.timestamp() * 1000)
    start_ts = int((target_time - timedelta(minutes=200*15)).timestamp() * 1000) # 15m candles
    
    print(f"Fetching data from Binance...")
    try:
        # Fetch 15m klines directly to match strategy input
        klines = client.get_historical_klines(
            symbol, 
            timeframe='15m',
            limit=200, # Strategy needs < 100 but fetch more to be safe
            # Note: client.get_historical_klines might just use limit or start/end
            # Let's use the method that main.py uses to be exact
        )
        
        # Checking main.py: df = self.client.get_historical_klines(symbol, timeframe=self.config.TIMEFRAME, limit=60)
        # It uses limit usually. To get a specific historical point, we need to be careful.
        # client.get_historical_klines usually fetches *recent* data if no start/end.
        # If we need historical verification, we might need a custom fetch or use ccxt directly.
        
        # Let's use ccxt from client if available or create new
        import ccxt
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv(symbol, '15m', since=start_ts, limit=200)
        
        # Filter to get exactly the candle closing at (or open at?) target_time
        # Signal is generated at Close of candle.
        # Trade is executed at Next Open.
        # Backtest time usually refers to Entry Time (Next Open) or Signal Time?
        # backtest_trades.csv "entry_time" is likely execution time.
        # So we need the candle BEFORE entry_time to check signal.
        
        entry_time_ts = target_time.timestamp() * 1000
        
        # Filter: Keep candles strictly BEFORE entry_time
        # Because signal is based on closed candles
        valid_candles = [x for x in ohlcv if x[0] < entry_time_ts]
        
        if not valid_candles:
            print("No valid candles found before target time.")
            return

        df = pd.DataFrame(valid_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # Slice last 50
        df_slice = df.tail(60)
        
        print(f"Data range: {df_slice.index[0]} -> {df_slice.index[-1]}")
        print(f"Analyzing signal on candle closing at {df_slice.index[-1]}...")
        
        strategy = MomentumStrategy()
        result = strategy.check_signal(symbol, df_slice)
        
        print("-" * 40)
        if result and result.get('status') == 'REJECTED':
            print(f"❌ REJECTED: {result['reason']}")
            # Calculate manual metrics for verification
            check_metrics(strategy, df_slice)
        elif result and result.get('side') == 'LONG':
            print("✅ SIGNAL VALID: WOULD OPEN LONG")
            print(f"Metrics: {result['metrics']}")
        else:
            print("❌ NO SIGNAL (Returned None)")
            
    except Exception as e:
        print(f"Error: {e}")

def check_metrics(strategy, df):
    # Manually print metrics to help user debug
    import pandas_ta as ta
    current = df.iloc[-1]
    
    avg_vol = df['volume'].iloc[-21:-1].mean()
    vol_ratio = current['volume'] / avg_vol if avg_vol > 0 else 0
    rsi = ta.rsi(df['close'], length=14).iloc[-1]
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)['ADX_14'].iloc[-1]
    upper_wick = current['high'] - current['close']
    upper_wick_ratio = upper_wick / current['close']
    
    print(f"--- Detail Metrics ---")
    print(f"RSI: {rsi:.2f} (Req: 65-90)")
    print(f"ADX: {adx:.2f} (Req: 25-60)")
    print(f"VolRatio: {vol_ratio:.2f} (Req: 2.5-12)")
    print(f"WickRatio: {upper_wick_ratio:.2%} (Req: <20%)")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 verify_signal.py SYMBOL TIMESTAMP(UTC)")
        print("Example: python3 verify_signal.py BTCUSDT '2024-11-05 14:45:00'")
    else:
        verify_signal(sys.argv[1], sys.argv[2])
