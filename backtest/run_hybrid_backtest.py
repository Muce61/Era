import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.hybrid_engine import HybridBacktestEngine

if __name__ == "__main__":
    engine = HybridBacktestEngine(initial_balance=100)
    engine.run()
