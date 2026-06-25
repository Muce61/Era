import sys
from pathlib import Path
import pandas as pd
from datetime import datetime
import pytz

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.run_1m_freq_backtest import MinuteFreqBacktestEngine

def main():
    print("="*60)
    print("Running 1-Month Minute-Level Backtest (Nov 11 - Dec 11, 2025)")
    print("Logic: Trade Checks every minute (High Frequency Simulation)")
    print("="*60)
    
    start_date = "2025-11-11 00:00:00"
    end_date = "2025-12-11 10:00:00"
    
    print(f"Start Date (UTC): {start_date}")
    print(f"End Date (UTC):   {end_date}")
    
    engine = MinuteFreqBacktestEngine(initial_balance=1000)
    engine.run(start_date=start_date, end_date=end_date, days=None) 

if __name__ == "__main__":
    main()
