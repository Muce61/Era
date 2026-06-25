import sys
import os

try:
    import data.binance_client
    print(f"data.binance_client file: {data.binance_client.__file__}")
except ImportError as e:
    print(f"ImportError: {e}")
    print(f"CWD: {os.getcwd()}")
    print(f"sys.path: {sys.path}")
    # List current directory
    print("Listing directory:")
    for f in os.listdir('.'):
        print(f)
