from dashboard_server import get_binance_client
import time

try:
    print("Initializing Binance Client...")
    exchange = get_binance_client()
    print("Fetching Balance...")
    balance = exchange.fetch_balance()
    print(f"Success! USDT Free: {balance['USDT']['free']}")
except Exception as e:
    print(f"Failed: {e}")
