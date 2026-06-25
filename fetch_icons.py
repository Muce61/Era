import os
import requests
import ccxt
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Setup directory
ICON_DIR = 'static/icons'
if not os.path.exists(ICON_DIR):
    os.makedirs(ICON_DIR)

# Initialize Binance to get list of symbols
exchange = ccxt.binance({
    'options': {'defaultType': 'future'}
})
markets = exchange.load_markets()

print(f"Found {len(markets)} markets. Downloading icons...")

count = 0
for symbol in markets:
    if '/USDT:USDT' not in symbol:
        continue
        
    base_currency = symbol.split('/')[0].lower()
    
    # Handle 1000 prefix (e.g. 1000SHIB -> shib)
    if base_currency.startswith('1000'):
        base_currency = base_currency[4:]
        
    # Skip if already exists
    file_path = os.path.join(ICON_DIR, f"{base_currency}.png")
    if os.path.exists(file_path):
        continue
        
    # Try Source 1: CoinCap (Lowercase)
    url1 = f"https://assets.coincap.io/assets/icons/{base_currency}@2x.png"
    # Try Source 2: SpotHQ (GitHub) (Lowercase)
    url2 = f"https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{base_currency}.png"
    # Try Source 3: CoinCap (Uppercase) - Some might be case sensitive?
    url3 = f"https://assets.coincap.io/assets/icons/{base_currency.upper()}@2x.png"
    
    downloaded = False
    for url in [url1, url2, url3]:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                print(f"Downloaded {base_currency}.png from {url}")
                downloaded = True
                count += 1
                break
        except:
            continue
    
    if not downloaded:
        print(f"Failed to download {base_currency}")
        # Create a placeholder if needed? 
        # Better to let frontend handle fallback to generic

print(f"Download complete. {count} new icons saved.")
