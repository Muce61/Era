import ccxt
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import json

# Global variables to be set in debug_binance_history
api_key = None
api_secret = None
use_testnet = False

def check_market_type(market_type_name, options):
    print(f"\n\n====== Checking Market Type: {market_type_name} ======")
    try:
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'options': options
        })
        if use_testnet:
            exchange.set_sandbox_mode(True)
            
        # Balance
        try:
            balance = exchange.fetch_balance()
            print("  Balance fetched successfully.")
        except Exception as e:
            print(f"  Balance fetch failed: {e}")
            return

        # Scan 90 days for BTC and ETH
        test_symbols = ['BTC/USDT', 'ETH/USDT']
        if market_type_name == 'Coin-M Futures':
            test_symbols = ['BTC/USD', 'ETH/USD']
        elif market_type_name == 'Spot':
            test_symbols = ['BTC/USDT', 'ETH/USDT']
            
        print(f"  Scanning last 90 days for {test_symbols}...")
        
        end_time = datetime.now()
        start_time_limit = end_time - timedelta(days=90)
        
        for sym in test_symbols:
            print(f"    Scanning {sym}...")
            found_trades = False
            
            # Loop backwards in 7-day chunks
            current_end = end_time
            while current_end > start_time_limit:
                current_start = current_end - timedelta(days=7)
                if current_start < start_time_limit:
                    current_start = start_time_limit
                
                # print(f"      Checking {current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}...")
                
                try:
                    since_ts = int(current_start.timestamp() * 1000)
                    params = {'endTime': int(current_end.timestamp() * 1000)}
                    
                    trades = exchange.fetch_my_trades(sym, since=since_ts, limit=5, params=params)
                    if trades:
                        print(f"      ✅ FOUND {len(trades)} trades between {current_start.strftime('%Y-%m-%d')} and {current_end.strftime('%Y-%m-%d')}!")
                        print(f"      Sample: {trades[0]['datetime']} | {trades[0]['side']} | {trades[0]['price']}")
                        found_trades = True
                        break # Found some, move to next symbol
                except Exception as e:
                    print(f"      Error fetching chunk: {e}")
                
                current_end = current_start
                
            if not found_trades:
                print(f"      ❌ No trades found in last 90 days for {sym}")

    except Exception as e:
        print(f"  Init failed: {e}")

def debug_binance_history():
    global api_key, api_secret, use_testnet
    load_dotenv(override=True)
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_SECRET')
    use_testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
    
    print(f"--- Binance API Debugger (Deep Scan) ---")
    
    # 1. USD-M Futures (Most likely)
    check_market_type('USD-M Futures', {'defaultType': 'future', 'adjustForTimeDifference': True})
    
    # 2. Coin-M Futures
    # check_market_type('Coin-M Futures', {'defaultType': 'delivery', 'adjustForTimeDifference': True})
    
    # 3. Spot
    # check_market_type('Spot', {'defaultType': 'spot', 'adjustForTimeDifference': True})

if __name__ == "__main__":
    debug_binance_history()
