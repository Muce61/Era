"""
质量过滤器模块 (Quality Filter Module)

功能:
1. 黑名单机制: 过滤历史亏损严重的币种
2. 市值/成交量过滤: 剔除流动性差的币种
3. 波动率过滤: 剔除ATR过高(不可控)或过低(无利可图)的币种
"""

class QualityFilterModule:
    def __init__(self):
        # 硬编码黑名单 (基于历史回测亏损Top)
        self.blacklist = {
            'DASHUSDT', 'FILUSDT', 'TNSRUSDT', 'STRKUSDT', 
            'BEATUSDT', 'XRPUSDT', 'FARTCOINUSDT', 'BANANAS31USDT',
            'USELESSUSDT', 'MOODENGUSDT' # Meme coins
        }
        
        # 最小24小时成交量 (USDT)
        self.min_volume = 50_000_000 # 提高到5000万
        
    def check_quality(self, symbol, df_slice, volume_24h):
        """
        检查币种质量
        Returns: (is_good, reason)
        """
        # 1. 黑名单检查
        base_symbol = symbol.replace('USDT', '') # Handle BTCUSDT -> BTC
        if symbol in self.blacklist or base_symbol in self.blacklist:
            return False, "Blacklisted"
            
        # 2. 成交量检查
        if volume_24h < self.min_volume:
            return False, f"Low Volume (${volume_24h/1e6:.1f}M < $50M)"
            
        # 3. 波动率检查 (ATR/Price)
        # 需要最近14根K线
        if len(df_slice) >= 14:
            import pandas_ta as ta
            atr = ta.atr(df_slice['high'], df_slice['low'], df_slice['close'], length=14).iloc[-1]
            price = df_slice['close'].iloc[-1]
            volatility = atr / price
            
            # 剔除波动率极端的币种 (>5% per 15m candle is too risky)
            if volatility > 0.05:
                return False, f"Extreme Volatility ({volatility*100:.1f}%)"
                
        return True, "OK"
