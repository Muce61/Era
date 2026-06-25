import ccxt
from dotenv import load_dotenv
import os
import json
from datetime import datetime, timedelta

# Load environment variables
load_dotenv(override=True)

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_SECRET')
use_testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'

exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True
    }
})

if use_testnet:
    exchange.set_sandbox_mode(True)

print("Fetching history...")
try:
    # Get trades from the last 180 days
    since = int((datetime.now() - timedelta(days=180)).timestamp() * 1000)
    
    # Try fetching for a known symbol first if possible, or just a few common ones
    symbols_to_check = ['ETH/USDT:USDT', 'BTC/USDT:USDT', 'SUPER/USDT:USDT', 'ORDER/USDT:USDT']
    
    all_trades = []
    for symbol in symbols_to_check:
        print(f"Checking {symbol}...")
        try:
            trades = exchange.fetch_my_trades(symbol, since=since, limit=10)
            if trades:
                print(f"Found {len(trades)} trades for {symbol}")
                all_trades.extend(trades)
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")

    if all_trades:
        print("\nSample Trade Data:")
        print(json.dumps(all_trades[0], indent=2, default=str))
    else:
        print("\nNo trades found in the last 180 days for checked symbols.")

except Exception as e:
    print(f"Global Error: {e}")
