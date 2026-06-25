import ccxt
import pandas as pd
import os
from dotenv import load_dotenv
from datetime import datetime

class BinanceClient:
    def __init__(self):
        load_dotenv(override=True)
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.secret = os.getenv('BINANCE_SECRET')
        
        if not self.api_key or not self.secret:
            raise ValueError("Binance API credentials not found in .env")
            
        self.exchange = ccxt.binance({
            'apiKey': self.api_key,
            'secret': self.secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': False, # Disabled to use manual offset
                'recvWindow': 60000 
            }
        })
        
        # FIX: Force clock rewind by 5 seconds to prevent "Timestamp ahead of server" error
        # Binance allows requests from the past (up to recvWindow), but NOT from the future (>1000ms).
        # If local clock is ahead, we MUST subtract time.
        original_milliseconds = self.exchange.milliseconds
        self.exchange.milliseconds = lambda: original_milliseconds() - 40000
        
        # Testnet check
        if os.getenv('USE_TESTNET') == 'true':
            self.exchange.set_sandbox_mode(True)

        # Load markets early to cache instrument info (including max leverage)
        self.leverage_cache = {}
        try:
            self.exchange.load_markets()
            self._load_leverage_brackets()
        except Exception as e:
            print(f"Warning: Failed to load markets on init: {e}")

    def _load_leverage_brackets(self):
        """Load all leverage brackets efficiently"""
        try:
            if self.exchange.has['fetchLeverageTiers']:
                tiers = self.exchange.fetch_leverage_tiers()
                for symbol, brackets in tiers.items():
                    if brackets and len(brackets) > 0:
                        self.leverage_cache[symbol] = int(brackets[0]['maxLeverage'])
                print(f"[OK] Loaded leverage limits for {len(self.leverage_cache)} symbols")
        except Exception as e:
            print(f"Warning: Failed to load leverage brackets: {e}")

    def get_top_gainers(self, limit=50):
        """
        Fetch top gainers from Binance Futures.
        Returns list of (symbol, ticker_data) tuples sorted by percentage change.
        """
        try:
            tickers = self.exchange.fetch_tickers()
            # Filter for USDT pairs and valid volume
            valid_tickers = []
            for symbol, data in tickers.items():
                if symbol.endswith('/USDT:USDT') or (symbol.endswith('USDT') and 'info' in data):
                    # Calculate 24h change percentage
                    if 'percentage' in data and data['percentage'] is not None:
                        valid_tickers.append((symbol, data))
            
            # Sort by percentage change desc
            valid_tickers.sort(key=lambda x: float(x[1]['percentage']) if x[1].get('percentage') is not None else -999.0, reverse=True)
            return valid_tickers[:limit]
        except Exception as e:
            print(f"Error fetching top gainers: {e}")
            return []

    def get_usdt_tickers(self):
        """
        Fetch ALL USDT futures tickers without limit.
        Used for establishing global volume ranking.
        """
        try:
            tickers = self.exchange.fetch_tickers()
            valid_tickers = []
            for symbol, data in tickers.items():
                if symbol.endswith('/USDT:USDT') or (symbol.endswith('USDT') and 'info' in data):
                     valid_tickers.append((symbol, data))
            return valid_tickers
        except Exception as e:
            print(f"Error fetching tickers: {e}")
            return []

    def get_ticker(self, symbol):
        """
        Get current ticker data for a symbol
        """
        try:
             return self.exchange.fetch_ticker(symbol)
        except Exception as e:
             # print(f"Error fetching ticker for {symbol}: {e}")
             return None

    def get_historical_klines(self, symbol, timeframe='15m', limit=100):
        """
        Fetch OHLCV data.
        Returns DataFrame with columns: timestamp, open, high, low, close, volume
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"Error fetching klines for {symbol}: {e}")
            return pd.DataFrame()

    def get_balance(self):
        """
        Get USDT balance.
        """
        try:
            balance = self.exchange.fetch_balance()
            return float(balance['USDT']['total'])
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return 0.0

    def get_max_leverage(self, symbol):
        """
        Get max leverage for a symbol.
        """
        # 1. Check Cache
        if symbol in self.leverage_cache:
            return self.leverage_cache[symbol]

        try:
            # 2. Try fetching specific tier if not in cache
            if self.exchange.has['fetchLeverageTiers']:
                tiers = self.exchange.fetch_leverage_tiers([symbol])
                if symbol in tiers and tiers[symbol]:
                     val = tiers[symbol][0]['maxLeverage']
                     self.leverage_cache[symbol] = int(val)
                     return int(val)

            # 3. Fallback to market info
            market = self.exchange.market(symbol)
            if 'limits' in market and 'leverage' in market['limits']:
                 val = market['limits']['leverage']['max']
                 return int(val) if val is not None else 20
            
            return 20 # Conservative Default
        except Exception as e:
            # print(f"Error fetching max leverage for {symbol}: {e}")
            return 20
