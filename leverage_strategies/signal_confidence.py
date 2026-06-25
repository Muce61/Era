"""
信号置信度驱动动态杠杆策略

根据多指标共振程度评估信号质量:
- 高置信度 (80-100分): 30x杠杆
- 中置信度 (50-80分): 20x杠杆
- 低置信度 (0-50分): 10x杠杆

评分因素:
1. RSI范围 (0-30分)
2. 成交量爆发 (0-30分)
3. ADX强度 (0-20分)
4. 上影线比例 (0-20分)
"""


class SignalConfidenceModule:
    def __init__(self):
        """初始化信号置信度模块"""
        pass
        
    def calculate(self, symbol, signal, current_price, df):
        """
        计算基于信号置信度的动态杠杆
        
        Args:
            symbol: 交易对
            signal: 信号字典 (包含metrics)
            current_price: 当前价格
            df: 历史数据DataFrame
            
        Returns:
            int: 杠杆倍数 (10, 20, 或 30)
        """
        confidence_score = 0
        metrics = signal.get('metrics', {})
        
        # 指标1: RSI范围 (0-30分)
        rsi = metrics.get('rsi', 70)
        if 70 <= rsi <= 85:
            # 完美动量区间
            confidence_score += 30
        elif 60 <= rsi < 90:
            # 可接受区间
            confidence_score += 20
        else:
            # 边缘区间
            confidence_score += 10
            
        # 指标2: 成交量爆发 (0-30分)
        vol_ratio = metrics.get('volume_ratio', 3.5)
        if vol_ratio >= 5.0:
            # 极强成交量
            confidence_score += 30
        elif vol_ratio >= 3.5:
            # 强成交量
            confidence_score += 20
        else:
            # 一般成交量
            confidence_score += 10
            
        # 指标3: ADX趋势强度 (0-20分)
        adx = metrics.get('adx', 30)
        if adx >= 40:
            # 极强趋势
            confidence_score += 20
        elif adx >= 30:
            # 强趋势
            confidence_score += 15
        elif adx >= 20:
            # 中等趋势
            confidence_score += 10
        else:
            # 弱趋势
            confidence_score += 5
            
        # 指标4: 上影线比例 (0-20分)
        upper_wick_ratio = metrics.get('upper_wick_ratio', 0.1)
        if upper_wick_ratio < 0.05:
            # 极小上影线 (收盘极强)
            confidence_score += 20
        elif upper_wick_ratio < 0.15:
            # 可接受上影线
            confidence_score += 15
        else:
            # 较大上影线
            confidence_score += 5
        
        # 映射置信度分数到杠杆
        if confidence_score >= 80:
            # 高置信度
            return 30
        elif confidence_score >= 50:
            # 中等置信度
            return 20
        else:
            # 低置信度
            return 10
    
    def get_confidence_score(self, signal):
        """
        获取置信度分数 (用于调试和记录)
        
        Args:
            signal: 信号字典
            
        Returns:
            int: 置信度分数 (0-100)
        """
        confidence_score = 0
        metrics = signal.get('metrics', {})
        
        # 使用与calculate相同的逻辑
        rsi = metrics.get('rsi', 70)
        if 70 <= rsi <= 85:
            confidence_score += 30
        elif 60 <= rsi < 90:
            confidence_score += 20
        else:
            confidence_score += 10
            
        vol_ratio = metrics.get('volume_ratio', 3.5)
        if vol_ratio >= 5.0:
            confidence_score += 30
        elif vol_ratio >= 3.5:
            confidence_score += 20
        else:
            confidence_score += 10
            
        adx = metrics.get('adx', 30)
        if adx >= 40:
            confidence_score += 20
        elif adx >= 30:
            confidence_score += 15
        elif adx >= 20:
            confidence_score += 10
        else:
            confidence_score += 5
            
        upper_wick_ratio = metrics.get('upper_wick_ratio', 0.1)
        if upper_wick_ratio < 0.05:
            confidence_score += 20
        elif upper_wick_ratio < 0.15:
            confidence_score += 15
        else:
            confidence_score += 5
        
        return confidence_score
