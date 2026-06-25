import sys
from pathlib import Path
# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine

def run_test(days):
    print(f"\n\n{'#'*50}")
    print(f"STARTING {days}-DAY BACKTEST")
    print(f"{'#'*50}")
    
    # Re-initialize engine for each run to reset balance and positions
    engine = RealBacktestEngine(initial_balance=100)
    engine.run(days=days)

def main():
    # Run 30 days
    run_test(30)
    
    # Run 15 days
    run_test(15)
    
    # Run 7 days
    run_test(7)

if __name__ == "__main__":
    main()
