#!/usr/bin/env python3
"""
Test icon download for specific symbols to debug issues
"""

from utils.icon_helper import download_icon
import os

# Test some symbols that are failing
test_symbols = ['btc', 'eth', 'order', 'iota', 'defi', 'people', 'xai', 'ai']

print("Testing icon downloads...\n")

for symbol in test_symbols:
    print(f"\n{'='*60}")
    print(f"Testing: {symbol.upper()}")
    print('='*60)
    
    # Check if exists
    icon_path = f"static/icons/{symbol}.png"
    if os.path.exists(icon_path):
        print(f"✓ Icon already exists: {icon_path}")
        continue
    
    # Try to download
    result = download_icon(symbol, retries=1)
    if result:
        print(f"✓ Successfully downloaded: {result}")
    else:
        print(f"✗ Failed to download {symbol}")
        print(f"  Tried URLs:")
        print(f"  - https://assets.coincap.io/assets/icons/{symbol}@2x.png")
        print(f"  - https://assets.coincap.io/assets/icons/{symbol.upper()}@2x.png")
        print(f"  - https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{symbol}.png")
