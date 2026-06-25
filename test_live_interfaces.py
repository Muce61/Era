import sys
import logging
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[0]))

from data.binance_client import BinanceClient
from execution.executor import Executor
from config.settings import Config
from main import TradingBot

# Setup simple logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("InterfaceTest")

def test_binance_connectivity():
    print("\n" + "="*50)
    print("Testing Binance Connectivity & Data Interfaces")
    print("="*50)
    
    try:
        client = BinanceClient()
        
        # 1. Test Balance
        balance = client.get_balance()
        logger.info(f"✅ Balance Check: {balance:.2f} USDT")
        
        # 2. Test Tickers (USDT Only)
        tickers = client.get_usdt_tickers()
        logger.info(f"✅ Tickers Check: Fetched {len(tickers)} USDT pairs")
        if len(tickers) > 0:
            top_vol = max(tickers, key=lambda x: float(x[1].get('quoteVolume', 0)))
            logger.info(f"   Max Volume Pair: {top_vol[0]} ({float(top_vol[1]['quoteVolume']):,.0f} USDT)")
            
        # 3. Test Klines
        symbol = "BTC/USDT:USDT"
        klines = client.get_historical_klines(symbol, limit=5)
        logger.info(f"✅ Klines Check ({symbol}): Fetched {len(klines)} candles")
        if not klines.empty:
            logger.info(f"   Last Close: {klines['close'].iloc[-1]}")
            
        return True
    except Exception as e:
        logger.error(f"❌ Connectivity Test Failed: {e}")
        return False

def test_executor_config():
    print("\n" + "="*50)
    print("Testing Executor & Risk Config Interfaces")
    print("="*50)
    
    try:
        executor = Executor()
        symbol = "ETH/USDT:USDT" # Use a major pair for testing config
        
        # 1. Test Set Leverage
        logger.info(f"Testing Set Leverage for {symbol}...")
        # Try setting to default 20x
        executor.set_leverage(symbol, 20)
        logger.info(f"✅ Set Leverage (20x) Successful")
        
        # 2. Test Margin Mode
        # Only log success/fail, some accounts can't change this easily if positions open
        try:
            executor.set_margin_mode(symbol, 'ISOLATED')
            logger.info(f"✅ Set Margin Mode (ISOLATED) Successful")
        except Exception as e:
            logger.warning(f"⚠️ Set Margin Mode Check: {e}")
            
        return True
    except Exception as e:
        logger.error(f"❌ Executor Test Failed: {e}")
        return False

def test_logic_consistency():
    print("\n" + "="*50)
    print("Testing Trading Bot Logic Interfaces (Scan & Rank)")
    print("="*50)
    
    try:
        # Initialize Bot (Mocking logger to avoid file writes if needed, but main logger is fine)
        bot = TradingBot()
        
        # 1. Test scan_top_gainers Logic
        logger.info("Running scan_top_gainers (Global Volume Scan)...")
        bot.scan_top_gainers()
        
        # Check if ranking populated
        ranking_size = len(bot.coin_volume_ranking)
        logger.info(f"✅ Global Ranking Populated: {ranking_size} coins")
        
        if ranking_size > 0:
            # Check a known top coin
            btc_rank = bot.coin_volume_ranking.get("BTC/USDT:USDT", 999)
            logger.info(f"   BTC Rank: {btc_rank}")
            if btc_rank > 10:
                logger.warning(f"⚠️ BTC Rank seems low ({btc_rank}), check volume data source")
            else:
                logger.info("✅ BTC Rank looks reasonable")
                
        # 2. Check Active Symbols (Top 200 candidates)
        active_count = len(bot.active_symbols)
        logger.info(f"✅ Active Monitoring Symbols: {active_count}")
        logger.info(f"   Sample: {list(bot.active_symbols)[:5]}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Logic Test Failed: {e}")
        return False

def main():
    print("Starting Comprehensive Live Interface Test...")
    
    c1 = test_binance_connectivity()
    c2 = test_executor_config()
    c3 = test_logic_consistency()
    
    if c1 and c2 and c3:
        print("\n" + "="*50)
        print("✅ ALL SYSTEMS GO! Live Interfaces are functioning correctly.")
        print("="*50)
    else:
        print("\n" + "="*50)
        print("❌ SOME TESTS FAILED. CHECK LOGS ABOVE.")
        print("="*50)

if __name__ == "__main__":
    main()
