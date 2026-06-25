from config.settings import Config
from data.binance_client import BinanceClient
import time

def check_balance():
    try:
        client = BinanceClient()
        balance = client.get_balance()
        print(f"Current Balance: {balance} USDT")
        
        # Check permissions
        print("Checking permissions...")
        # try to fetch open orders
        orders = client.exchange.fetch_open_orders()
        print(f"Open Orders: {len(orders)}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_balance()
