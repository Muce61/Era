import os
from pathlib import Path
from dotenv import load_dotenv

# Explicitly find and load .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

class Config:
    # API Configuration
    API_KEY = os.getenv("BINANCE_API_KEY")
    SECRET = os.getenv("BINANCE_SECRET")
    TESTNET = os.getenv("BINANCE_TESTNET", "False").lower() == "true"
    
    TIMEFRAME = '15m'  # Signal timeframe (Optimized: 15m Signal + 1m Execution)
    LOOKBACK_WINDOW = 50 # For indicators
    TOP_GAINER_COUNT = 50
    CHANGE_THRESHOLD_MIN = 2.0   # Min 2% 24h change (widened from 5%)
    CHANGE_THRESHOLD_MAX = 200.0 # Max 200% 24h change (widened from 20%)
    CHANGE_THRESHOLD_MAX = 200.0 # Max 200% 24h change (widened from 20%)
    BULLISH_CANDLES_COUNT = 2    # Reduced to 2 for faster entry
    
    # Execution Mode
    # If True: Executes trades on ANY 1m candle close (Intra-bar for 15m). "Repainting" risk but faster entry.
    # If False: Executes only on confirmed 15m candle close. Safer but slower.
    ALLOW_DEVELOPING_SIGNALS = False 
    
    # Risk Management - OPTIMIZED CONFIG (10×10% 50x)
    LEVERAGE = 50                     # 50x leverage for maximum returns
    RISK_PER_TRADE = 0.02             # 2% risk per trade (Legacy)
    TRADE_MARGIN_PERCENT = 0.10       # 10% position size per trade
    MAX_OPEN_POSITIONS = 10           # 10 concurrent positions for high frequency
    
    # Risk Limits
    ATR_PERIOD = 14
    ATR_MULTIPLIER = 2.5              # ATR × 2.5 for stop loss calculation
    STOP_LOSS_CAP_PERCENT = 0.014     # 1.4% hard cap (MUST be below 1.5% liquidation for 50x)
    TRAILING_ACTIVATION = 0.15        # 15% ROE to activate trailing (matched to backtest)
    TRAILING_CALLBACK = 0.01          # 1% pullback to close
    
    # Data Paths
    DATA_DIR = "data/storage"
