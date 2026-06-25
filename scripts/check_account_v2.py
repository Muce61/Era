import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import Config
from data.binance_client import BinanceClient

def check_balance():
    try:
        client = BinanceClient()
        balance = client.get_balance()
        print(f"Current Balance: {balance} USDT")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_balance()
