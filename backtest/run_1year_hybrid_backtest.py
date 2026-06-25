import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.run_1m_freq_backtest import MinuteFreqBacktestEngine

def main():
    print("="*60)
    print("Running 1-Year Hybrid Backtest (Dec 2024 - Dec 2025)")
    print("Mode: 1 Minute Execution + 15 Minute Signal Resampling")
    print("="*60)
    
    start_date = "2024-12-09 00:00:00"
    end_date = "2025-12-09 23:59:59"
    
    print(f"Start Date (UTC): {start_date}")
    print(f"End Date (UTC):   {end_date}")
    
    engine = MinuteFreqBacktestEngine(initial_balance=100)
    engine.run(start_date=start_date, end_date=end_date, days=None) 

if __name__ == "__main__":
    main()
