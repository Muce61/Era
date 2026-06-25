#!/usr/bin/env python3
import ccxt
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv(override=True)

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_SECRET')
use_testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'

print(f"API Key: {api_key[:10]}..." if api_key else "No API Key")
print(f"API Secret: {api_secret[:10]}..." if api_secret else "No API Secret")
print(f"Use Testnet: {use_testnet}")

# Initialize exchange
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
    print("Using testnet mode")

# Test connection
try:
    print("\nTesting balance fetch...")
    balance = exchange.fetch_balance()
    usdt = balance.get('USDT', {})
    print(f"✓ Success! USDT Balance: {usdt.get('free', 0) + usdt.get('used', 0)}")
except Exception as e:
    print(f"✗ Error: {e}")

try:
    print("\nTesting positions fetch...")
    positions = exchange.fetch_positions()
    print(f"✓ Success! Found {len(positions)} positions")
    open_pos = [p for p in positions if abs(float(p.get('contracts', 0))) > 0]
    print(f"  Open positions: {len(open_pos)}")
except Exception as e:
    print(f"✗ Error: {e}")
