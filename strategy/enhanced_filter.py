import pandas as pd
import pandas_ta as ta
from datetime import timedelta

class EnhancedSignalFilter:
    """
    Advanced signal filtering with multi-timeframe confirmation
    """
    
    @staticmethod
    def check_1h_trend(symbol, current_time, data_15m):
        """
        Check if 1-hour trend is bullish
        """
        try:
            # Resample 15m to 1h
            df = data_15m[symbol].copy()
            
            # Get data around current time
            mask = df.index <= current_time
            recent_data = df[mask].tail(100)
            
            if len(recent_data) < 20:
                return False
            
            # Resample to 1h
            df_1h = recent_data.resample('1H').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            if len(df_1h) < 20:
                return False
            
            # Check 1h EMA trend
            ema_20 = ta.ema(df_1h['close'], length=20)
            current_price = df_1h['close'].iloc[-1]
            
            # Bullish if price above 1h EMA20 or within -6% (relaxed from -4%)
            return current_price > ema_20.iloc[-1] * 0.94
            
        except Exception as e:
            return False
    
    @staticmethod
    def check_volume_persistence(df, row_loc):
        """
        Check if high volume is persistent (not just a spike)
        """
        try:
            # Get recent 3 candles volume
            recent_volumes = df.iloc[row_loc-2:row_loc+1]['volume']
            normal_volume = df.iloc[row_loc-50:row_loc-3]['volume'].mean()
            
            # Relaxed: Average volume > 1.0x normal (was 1.2x)
            # Still require at least one spike > 2.0x
            high_vol_count = sum(v > normal_volume * 2.0 for v in recent_volumes)
            avg_vol = recent_volumes.mean()
            
            return high_vol_count >= 1 and avg_vol > normal_volume * 1.0
            
        except Exception:
            return False
    
    @staticmethod
    def check_volatility_safe(df, row_loc):
        """
        Avoid trading in extreme volatility
        """
        try:
            # Calculate ATR
            history = df.iloc[max(0, row_loc-50):row_loc+1]
            atr_current = ta.atr(history['high'], history['low'], history['close'], length=14).iloc[-1]
            
            # Get average ATR
            atr_series = ta.atr(df.iloc[max(0, row_loc-100):row_loc+1]['high'],
                               df.iloc[max(0, row_loc-100):row_loc+1]['low'],
                               df.iloc[max(0, row_loc-100):row_loc+1]['close'], length=14)
            atr_avg = atr_series.tail(50).mean()
            
            # Skip if volatility is too extreme (>2.5x average)
            if atr_current > atr_avg * 2.5:
                return False
            
            return True
            
        except Exception:
            return True  # If can't calculate, don't filter out
    
    @staticmethod
    def check_momentum_strength(df, row_loc):
        """
        Verify momentum strength using RSI
        """
        try:
            history = df.iloc[max(0, row_loc-50):row_loc+1]
            rsi = ta.rsi(history['close'], length=14).iloc[-1]
            
            # RSI range widened to 45-90 (was 50-85)
            return 45 <= rsi <= 90
            
        except Exception:
            return True
    
    @staticmethod
    def apply_all_filters(symbol, df, row_loc, current_time, data_15m):
        """
        Apply all enhanced filters
        """
        filters = {
            '1h_trend': EnhancedSignalFilter.check_1h_trend(symbol, current_time, data_15m),
            'volume_persistence': EnhancedSignalFilter.check_volume_persistence(df, row_loc),
            'volatility_safe': EnhancedSignalFilter.check_volatility_safe(df, row_loc),
            'momentum_strength': EnhancedSignalFilter.check_momentum_strength(df, row_loc)
        }
        
        # All filters must pass
        all_passed = all(filters.values())
        
        return all_passed, filters
