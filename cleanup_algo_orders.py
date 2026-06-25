
import os
import sys
import time
import hmac
import hashlib
import urllib.parse
import requests
import json
from dotenv import load_dotenv

# Load Env
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

API_KEY = os.getenv('BINANCE_API_KEY')
SECRET = os.getenv('BINANCE_SECRET')

if not API_KEY or not SECRET:
    print(f"❌ Error: API Keys not found in {dotenv_path}")
    print(f"Keys: {API_KEY is not None}, {SECRET is not None}")
    sys.exit(1)
    
print(f"✅ Loaded API Key: {API_KEY[:4]}***")

BASE_URL = "https://fapi.binance.com"

def get_signature(params):
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        SECRET.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return query_string, signature

def fetch_open_algo_orders():
    endpoint = "/fapi/v1/openAlgoOrders"
    params = {
        'timestamp': int(time.time() * 1000),
        'recvWindow': 5000
    }
    qs, sig = get_signature(params)
    url = f"{BASE_URL}{endpoint}?{qs}&signature={sig}"
    
    headers = {'X-MBX-APIKEY': API_KEY}
    resp = requests.get(url, headers=headers)
    
    print(f"Fetch Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Raw Data Type: {type(data)}")
        if isinstance(data, dict) and 'orders' in data:
            return data['orders']
        return data
    else:
        print(f"Error: {resp.text}")
        return []

def cancel_algo_order(symbol, algo_id):
    endpoint = "/fapi/v1/algo/order"
    params = {
        'symbol': symbol,
        'algoId': algo_id,
        'timestamp': int(time.time() * 1000),
        'recvWindow': 5000
    }
    qs, sig = get_signature(params)
    url = f"{BASE_URL}{endpoint}?{qs}&signature={sig}"
    
    headers = {'X-MBX-APIKEY': API_KEY}
    print(f"Attempting DELETE for AlgoID: {algo_id}...")
    resp = requests.delete(url, headers=headers)
    
    print(f"Delete Status: {resp.status_code}")
    print(f"Delete Response: {resp.text}")

if __name__ == "__main__":
    print("--- Fetching Open Algo Orders ---")
    orders = fetch_open_algo_orders()
    print(f"Found {len(orders)} orders.")
    
    if orders:
        print("First Order Sample:")
        print(json.dumps(orders[0], indent=2))
        
        print("\n--- Cleaning Up ---")
        for o in orders:
            algo_id = o.get('algoId')
            symbol = o.get('symbol')
            print(f"Cancelling {symbol} - AlgoID: {algo_id}")
            cancel_algo_order(symbol, algo_id)
            time.sleep(0.5)
