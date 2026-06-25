import ccxt
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time

def debug_income_discovery():
    load_dotenv(override=True)
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_SECRET')
    use_testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
    
    print(f"--- Binance Income Discovery Debugger ---")
    
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'options': {
            'defaultType': 'future',
        }
    })
    if use_testnet:
        exchange.set_sandbox_mode(True)
        
    # Scan 90 days of income history using Backwards Pagination
    end_time = datetime.now()
    start_time_limit = end_time - timedelta(days=90)
    start_ts = int(start_time_limit.timestamp() * 1000)
    
    print(f"Scanning Income History (Backwards) from {end_time} back to {start_time_limit}...")
    
    active_symbols = set()
    total_items = 0
    
    current_end_ts = int(end_time.timestamp() * 1000)
    
    while current_end_ts > start_ts:
        try:
            params = {
                'endTime': current_end_ts,
                'limit': 1000
            }
            # print(f"  Fetching 1000 items before {datetime.fromtimestamp(current_end_ts/1000)}...")
            
            income = exchange.fapiPrivateGetIncome(params)
            
            if not income:
                print(f"  No more income items found.")
                break
                
            count = len(income)
            total_items += count
            
            # Collect symbols
            min_ts = current_end_ts
            for item in income:
                if item.get('symbol'):
                    active_symbols.add(item['symbol'])
                
                # Handle timestamp safely
                if 'time' in item:
                    try:
                        ts = int(item['time'])
                        if ts < min_ts:
                            min_ts = ts
                    except ValueError:
                        pass
                        
            print(f"  Fetched {count} items. Oldest: {datetime.fromtimestamp(min_ts/1000)}. Active Symbols: {len(active_symbols)}")
            
            # Prepare for next page
            # If min_ts didn't change (all items in same ms?), decrement by 1 to avoid infinite loop
            if min_ts == current_end_ts:
                current_end_ts -= 1000 # Jump back 1s if stuck
            else:
                current_end_ts = min_ts - 1
                
            time.sleep(0.2) # Rate limit
            
        except Exception as e:
            print(f"  Error fetching page: {e}")
            break

    print(f"\nDiscovery Complete!")
    print(f"Total Income Items: {total_items}")
    print(f"Active Symbols Found ({len(active_symbols)}): {active_symbols}")

if __name__ == "__main__":
    debug_income_discovery()
