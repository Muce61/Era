import ccxt
from dotenv import load_dotenv
import os
import json

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

print("Loading markets...")
markets = exchange.load_markets()
print(f"Total markets: {len(markets)}")
print("Sample symbols:", list(markets.keys())[:5])

target_symbol = 'SUPER/USDT:USDT'
alt_symbol = 'SUPER/USDT'

print(f"\nChecking {target_symbol}...")
try:
    trades = exchange.fetch_my_trades(target_symbol, limit=5)
    print(f"Trades: {len(trades)}")
except Exception as e:
    print(f"Error fetching trades: {e}")

try:
    orders = exchange.fetch_orders(target_symbol, limit=5)
    print(f"Orders: {len(orders)}")
    if orders:
        print("Sample Order:", json.dumps(orders[0], indent=2, default=str))
except Exception as e:
    print(f"Error fetching orders: {e}")

print(f"\nChecking {alt_symbol}...")
try:
    trades = exchange.fetch_my_trades(alt_symbol, limit=5)
    print(f"Trades: {len(trades)}")
except Exception as e:
    print(f"Error fetching trades: {e}")
