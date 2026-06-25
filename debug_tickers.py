import sys
from pathlib import Path
import ccxt

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from data.binance_client import BinanceClient

def main():
    print("="*60)
    print("Debugging Binance Ticker Fetch")
    print("="*60)
    
    try:
        client = BinanceClient()
        print("Fetching tickers...")
        tickers = client.exchange.fetch_tickers()
        print(f"Raw tickers count: {len(tickers)}")
        
        usdt_count = 0
        valid_tickers = []
        
        sample_keys = list(tickers.keys())[:5]
        print(f"Sample Keys: {sample_keys}")
        
        for symbol, data in tickers.items():
            if symbol.endswith('/USDT:USDT'):
                usdt_count += 1
                valid_tickers.append(symbol)
                
        print(f"Matched '/USDT:USDT' count: {usdt_count}")
        
        if usdt_count == 0:
            print("Trying alternative suffixes...")
            alt_count = 0
            for symbol in tickers:
                if 'USDT' in symbol:
                    alt_count += 1
            print(f"Contains 'USDT' count: {alt_count}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
