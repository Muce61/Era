import ccxt
from dotenv import load_dotenv
import os
import json
from datetime import datetime, timedelta

# Load environment variables
load_dotenv(override=True)

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_SECRET')

exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'options': {
        'defaultType': 'future',
    }
})

print("Fetching recent trades to check for PnL...")
try:
    # Try to find a symbol with trades
    # We'll check a few common ones or use the log file method if needed
    # For now, let's try to fetch from a symbol we know might have activity or just check the structure
    # Since I don't know which symbol has trades for sure, I'll try the ones from the log again
    target_symbol = 'SUPER/USDT:USDT' 
    
    trades = exchange.fetch_my_trades(target_symbol, limit=5)
    if trades:
        print(f"Found {len(trades)} trades.")
        print("Sample Trade Data (First Item):")
        print(json.dumps(trades[0], indent=2, default=str))
        
        # Check for realizedPnl in 'info'
        if 'info' in trades[0] and 'realizedPnl' in trades[0]['info']:
            print(f"\nRealized PnL found: {trades[0]['info']['realizedPnl']}")
        else:
            print("\nRealized PnL NOT found in 'info'.")
    else:
        print("No trades found for SUPER/USDT:USDT. Trying to fetch open orders to find active symbols...")
        orders = exchange.fetch_orders(limit=5) # This might fail without symbol
        # If fetch_orders without symbol fails, we can't easily find active symbols without the log file
        # But I assume the structure is standard Binance Futures structure.
        # I will assume realizedPnl is present in 'info' as per Binance API docs.
        print("Could not verify PnL directly, but proceeding with assumption based on API docs.")

except Exception as e:
    print(f"Error: {e}")
