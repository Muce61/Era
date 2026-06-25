import os
import requests
import time

ICON_DIR = 'static/icons'
GENERIC_ICON = 'generic.png'

def ensure_icon_dir():
    """Ensure the icon directory exists"""
    if not os.path.exists(ICON_DIR):
        os.makedirs(ICON_DIR)

def download_icon(symbol, retries=3):
    """
    Download icon for a symbol, trying multiple sources and case variants.
    Returns the filename if successful, None otherwise.
    
    Args:
        symbol: Base currency symbol (e.g., 'btc', 'eth')
        retries: Number of retry attempts
    
    Returns:
        str: Filename if downloaded, None if failed
    """
    ensure_icon_dir()
    
    # Clean symbol (remove 1000 prefix if exists)
    clean_symbol = symbol.lower()
    if clean_symbol.startswith('1000'):
        clean_symbol = clean_symbol[4:]
    
    file_path = os.path.join(ICON_DIR, f"{clean_symbol}.png")
    
    # Skip if already exists
    if os.path.exists(file_path):
        return f"{clean_symbol}.png"
    
    # Try multiple sources and case variants
    sources = [
        # Source 1: CoinCap (lowercase)
        f"https://assets.coincap.io/assets/icons/{clean_symbol}@2x.png",
        # Source 2: CoinCap (uppercase)
        f"https://assets.coincap.io/assets/icons/{clean_symbol.upper()}@2x.png",
        # Source 3: CoinCap (title case)
        f"https://assets.coincap.io/assets/icons/{clean_symbol.capitalize()}@2x.png",
        # Source 4: SpotHQ GitHub (lowercase)
        f"https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{clean_symbol}.png",
        # Source 5: SpotHQ GitHub (uppercase)
        f"https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{clean_symbol.upper()}.png",
    ]
    
    for attempt in range(retries):
        for url in sources:
            try:
                response = requests.get(url, timeout=3)
                if response.status_code == 200:
                    with open(file_path, 'wb') as f:
                        f.write(response.content)
                    print(f"✓ Downloaded icon for {clean_symbol} from {url}")
                    return f"{clean_symbol}.png"
            except Exception as e:
                # Silently continue to next source
                pass
        
        if attempt < retries - 1:
            time.sleep(0.5)  # Brief pause before retry
    
    print(f"✗ Failed to download icon for {clean_symbol}")
    return None

def get_icon_path(symbol):
    """
    Get the icon path for a symbol, downloading if necessary.
    
    Args:
        symbol: Symbol string (e.g., 'BTC/USDT:USDT' or 'btc')
    
    Returns:
        str: Relative path to icon (e.g., '/static/icons/btc.png')
    """
    # Extract base currency
    if '/' in symbol:
        base_currency = symbol.split('/')[0].lower()
    else:
        base_currency = symbol.lower()
    
    # Remove 1000 prefix
    if base_currency.startswith('1000'):
        base_currency = base_currency[4:]
    
    # Check if icon exists
    icon_file = f"{base_currency}.png"
    icon_full_path = os.path.join(ICON_DIR, icon_file)
    
    if os.path.exists(icon_full_path):
        return f"/static/icons/{icon_file}"
    
    # Try to download
    downloaded = download_icon(base_currency)
    if downloaded:
        return f"/static/icons/{downloaded}"
    
    # Fallback to generic
    return f"/static/icons/{GENERIC_ICON}"

def batch_download_all_icons():
    """Download icons for all Binance futures contracts"""
    import ccxt
    from dotenv import load_dotenv
    
    load_dotenv(override=True)
    
    print("Fetching all Binance Futures markets...")
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    markets = exchange.load_markets()
    
    usdt_symbols = [s for s in markets if '/USDT:USDT' in s]
    print(f"Found {len(usdt_symbols)} USDT-M contracts.")
    
    success_count = 0
    fail_count = 0
    
    for symbol in usdt_symbols:
        base_currency = symbol.split('/')[0].lower()
        if base_currency.startswith('1000'):
            base_currency = base_currency[4:]
        
        # Skip if exists
        if os.path.exists(os.path.join(ICON_DIR, f"{base_currency}.png")):
            continue
        
        # Download
        if download_icon(base_currency):
            success_count += 1
        else:
            fail_count += 1
        
        # Rate limit protection
        time.sleep(0.1)
    
    print(f"\n=== Batch Download Complete ===")
    print(f"✓ Success: {success_count}")
    print(f"✗ Failed: {fail_count}")
