
import os
import sys
import json
sys.path.append(os.getcwd())

from risk.trend_reversal_detector import TrendReversalDetector

def check():
    detector = TrendReversalDetector()
    print(f"Loaded State: {detector.state_file}")
    print(f"Pause Long: {detector.pause_long}")
    print(f"Recent Trades: {len(detector.recent_trades)}")
    
    is_rev, reason = detector.detect_trend_reversal()
    print(f"Is Reversal? {is_rev}")
    print(f"Reason: {reason}")
    
    # Calculate components manually to verify
    window = 5
    recent = detector.recent_trades[-window:]
    loss_count = sum(1 for t in recent if t['pnl'] < 0)
    print(f"Loss Count (last 5): {loss_count}")
    
    recent_wr = detector.calculate_recent_winrate(10)
    print(f"Winrate (last 10): {recent_wr}")
    
    if len(detector.recent_trades) >= 10:
        recent_pnl = sum(t['pnl'] for t in detector.recent_trades[-10:])
        print(f"Net PnL (last 10): {recent_pnl}")

if __name__ == "__main__":
    check()
