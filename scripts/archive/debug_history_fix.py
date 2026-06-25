import ccxt
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

def get_binance_client():
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_SECRET')
    
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'options': {
            'defaultType': 'future',
            'adjustForTimeDifference': True
        }
    })
    return exchange

def debug_history():
    print("Initializing Exchange...")
    exchange = get_binance_client()
    print("Loading Markets...")
    markets = exchange.load_markets()
    print(f"Loaded {len(markets)} markets.")

    print("\n1. Fetching Income History...")
    try:
        income_history = exchange.fapiPrivateGetIncome({'limit': 1000})
        print(f"Fetched {len(income_history)} income records.")
        
        if len(income_history) > 0:
            print(f"Sample income record: {income_history[0]}")
    except Exception as e:
        print(f"Error fetching income: {e}")
        return

    print("\n2. Extracting Symbols...")
    active_symbols = set()
    
    # Create a reverse map for faster lookup: id -> symbol
    id_to_symbol = {}
    for sym, data in markets.items():
        id_to_symbol[data['id']] = sym
        
    print(f"Created ID map with {len(id_to_symbol)} entries.")
    
    for item in income_history:
        raw_sym = item.get('symbol')
        if not raw_sym:
            continue
            
        # Try direct map
        if raw_sym in id_to_symbol:
            active_symbols.add(id_to_symbol[raw_sym])
        else:
            print(f"Warning: Could not map raw symbol '{raw_sym}' to CCXT symbol")

    print(f"Found active symbols: {active_symbols}")
    
    if not active_symbols:
        print("No active symbols found! Checking if manual mapping helps...")
        # Debug: Check what 'ORDERUSDT' maps to
        if 'ORDERUSDT' in id_to_symbol:
            print(f"ORDERUSDT maps to {id_to_symbol['ORDERUSDT']}")
        else:
            print("ORDERUSDT not found in markets!")
            
    print("\n3. Fetching Trades (Last 7 Days)...")
    since = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)
    
    all_trades = []
    for symbol in active_symbols:
        print(f"Fetching trades for {symbol}...")
        
        # Test 1: Standard CCXT symbol
        try:
            trades = exchange.fetch_my_trades(symbol, since=since, limit=50)
            print(f"  [Standard] Found {len(trades)} trades.")
            if trades: all_trades.extend(trades)
        except Exception as e:
            print(f"  [Standard] Error: {e}")

        # Test 2: Simple symbol (remove :USDT)
        simple_symbol = symbol.split(':')[0]
        if simple_symbol != symbol:
            try:
                trades = exchange.fetch_my_trades(simple_symbol, since=since, limit=50)
                print(f"  [Simple] Found {len(trades)} trades for {simple_symbol}.")
                if trades: all_trades.extend(trades)
            except Exception as e:
                print(f"  [Simple] Error: {e}")

        # Test 3: Fetch Orders
        try:
            orders = exchange.fetch_orders(symbol, since=since, limit=50)
            print(f"  [Orders] Found {len(orders)} orders.")
        except Exception as e:
            print(f"  [Orders] Error: {e}")

    print(f"\nTotal trades found: {len(all_trades)}")
    for t in all_trades[:5]:
        print(f" - {t['datetime']} {t['symbol']} {t['side']} {t['amount']} @ {t['price']}")

if __name__ == "__main__":
    debug_history()
