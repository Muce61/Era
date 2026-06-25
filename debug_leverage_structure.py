import sys
from pathlib import Path
import ccxt
import json
import os
from dotenv import load_dotenv

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from data.binance_client import BinanceClient

def main():
    print("Initialize BinanceClient...")
    client = BinanceClient()
    exchange = client.exchange
    
    # print("Loading markets...") # Done in init
    markets = exchange.markets
    
    # Symbols to check
    targets = ['ETH/USDT:USDT', 'LUNA2/USDT:USDT', '1000FLOKI/USDT:USDT']
    
    for symbol in targets:
        print(f"\n{'='*40}")
        print(f"Checking {symbol}")
        print(f"{'='*40}")
        
        if symbol not in markets:
            print(f"❌ Symbol {symbol} not found in markets!")
            # Try to find close matches
            matches = [m for m in markets if 'LUNA' in m or 'FLOKI' in m]
            print(f"Possible matches: {matches[:5]}")
            continue
            
        market = markets[symbol]
        
        # Check limits
        limits = market.get('limits', {})
        leverage_limits = limits.get('leverage', {})
        print(f"Market['limits']['leverage']: {leverage_limits}")
        
        # Check info (Raw Binance Response)
        info = market.get('info', {})
        print(f"Raw 'info' keys: {list(info.keys())}")
        
        # Try specific bracket endpoint if possible
        try:
            # For Future, usually fetch_leverage_brackets or specifically fapiPrivateGetLeverageBracket
            # Note: fetch_leverage_brackets might require authentication
            print("Attempting to fetch ALL leverage brackets...")
            if exchange.has['fetchLeverageTiers']:
                all_tiers = exchange.fetch_leverage_tiers()
                print(f"✅ Fetched tiers for {len(all_tiers)} symbols")
                
                # Check target symbols in bulk result
                for t_sym in targets:
                    if t_sym in all_tiers:
                        print(f"   {t_sym}: Max {all_tiers[t_sym][0]['maxLeverage']}")
                    else:
                        print(f"   {t_sym}: Not in bulk result")
                return # Exit after successful bulk test
            else:
                 print("❌ Exchange does not support fetchLeverageTiers")
                 
        except Exception as e:
            print(f"Error fetching tiers: {e}")

if __name__ == "__main__":
    main()
