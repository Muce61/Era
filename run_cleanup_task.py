
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from execution.executor import Executor

def run_cleanup():
    print("Initializing Executor...")
    executor = Executor()
    
    for symbol in ['ETH/USDT:USDT']:
        print(f"\n--- Testing Cleanup on {symbol} ---")
        try:
            # 1. Create Dummy Order
            print("1. Creating Test Order...")
            price = 3000.0 # Deep OTM
            executor.place_algo_order(symbol, 'sell', 0.01, price)
            
            import time
            time.sleep(1)
            
            # 2. Verify Existence
            print("2. Verifying Existence...")
            orders = executor.fetch_open_algo_orders(symbol)
            if not orders:
                print("❌ Failed to find created order!")
                continue
            print(f"✅ Found {len(orders)} orders.")
            
            # 3. Clean
            print("3. Executing Cleanup...")
            executor.cancel_all_algo_orders(symbol)
            
            time.sleep(1)
            
            # 4. Verify Empty
            print("4. verifying Cleanup...")
            orders_after = executor.fetch_open_algo_orders(symbol)
            if not orders_after:
                print("✅ Cleanup Successful (0 orders remaining)")
            else:
                print(f"❌ Cleanup Failed! {len(orders_after)} orders remain.")
                
        except Exception as e:
            print(f"Error cleaning {symbol}: {e}")

if __name__ == "__main__":
    run_cleanup()
