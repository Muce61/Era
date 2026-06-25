import sys
from pathlib import Path
import pandas as pd
import pandas_ta as ta

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from backtest.real_engine import RealBacktestEngine
from strategy.momentum import MomentumStrategy

class MultiTimeframeStrategy(MomentumStrategy):
    """
    多时间框架策略
    1. 先在1小时级别确认趋势
    2. 再在15分钟级别寻找入场点
    """
    
    def check_signal_1h(self, symbol, df_1h):
        """
        1小时级别信号确认 (仅作参考，不拦截)
        """
        if len(df_1h) < 50:
            return False
            
        # 只要数据足够，就返回True，不进行硬性过滤
        # 具体的1小时指标可以在15分钟信号中作为参考因子
        return True
    
    def check_signal(self, symbol, df):
        """
        15分钟级别入场信号 (主信号源)
        """
        if df.empty or len(df) < 20:
            return None
        
        # 使用预计算的指标
        # 注意：df是history_slice，最后一行是当前K线
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 获取timestamp
        timestamp = df['timestamp'].iloc[-1] if 'timestamp' in df.columns else df.index[-1]
        
        # 核心条件1: 突破确认 (Close > Previous High)
        if current['close'] <= prev['high']:
            return None
        
        # 核心条件2: 成交量确认 (使用预计算的均线)
        # avg_vol = df['volume'].iloc[-21:-1].mean() # 旧逻辑
        if 'vol_ma' not in current:
            return None
            
        avg_vol = current['vol_ma']
        if avg_vol == 0: return None
        
        if current['volume'] < 2.0 * avg_vol:
            return None
        
        # 核心条件3: RSI范围 (使用预计算值)
        if 'rsi' not in current: return None
        rsi = current['rsi']
        
        if not (55 <= rsi <= 90):
            return None
        
        # 获取其他预计算指标
        adx = current.get('adx', 0)
        vol_ratio = current['volume'] / avg_vol
        
        return {
            'symbol': symbol,
            'side': 'LONG',
            'entry_price': current['close'],
            'timestamp': timestamp,
            'metrics': {
                'rsi': rsi,
                'adx': adx,
                'volume_ratio': vol_ratio
            }
        }


class MultiTimeframeEngine(RealBacktestEngine):
    """
    多时间框架回测引擎
    涨幅范围：5%-20%（更窄，减少极端币种）
    """
    def __init__(self, initial_balance=100):
        super().__init__(initial_balance)
        
        # 使用多时间框架策略
        self.strategy = MultiTimeframeStrategy()
        
        # 修改涨幅范围 (迭代3 - 进一步扩大)
        self.config.CHANGE_THRESHOLD_MIN = 0.0   # 0% (捕捉底部启动)
        self.config.CHANGE_THRESHOLD_MAX = 50.0  # 50% (捕捉强势延续)
        self.config.TOP_GAINER_COUNT = 100       # 扫描前100名
        
        # 20x杠杆 + 分批止盈
        self.config.LEVERAGE = 20
        self.risk_manager.config.LEVERAGE = 20
        
        # 存储1小时数据
        self.data_feed_1h = {}
        
        # 存储待入场的信号
        self.pending_entries = {}
        
        print(f"⚙️  策略: 多时间框架 (15M主导 + 1H参考)")
        print(f"📊 涨幅范围: 不限 (扫描全市场)")
        print(f"📈 1H条件: 仅作参考 (不拦截)")
        print(f"📉 15M条件: Vol>2x, RSI 55-90")
        print(f"⚙️  杠杆: 20x")
        print(f"💰 分批止盈: 15% (40%), 25% (30%), 40% (all)")
    
    def _open_position(self, symbol, price, timestamp, history_slice, metrics=None):
        """
        Override to force 20x leverage
        """
        leverage = 20
        self.risk_manager.config.LEVERAGE = 20
        
        if history_slice is not None and len(history_slice) >= 14:
            import pandas_ta as ta
            atr = ta.atr(history_slice['high'], history_slice['low'], history_slice['close'], length=14).iloc[-1]
            sl_distance = atr * 2.5
            max_stop_distance = price * 0.035
            sl_distance = min(sl_distance, max_stop_distance)
            stop_loss_pct = sl_distance / price
        else:
            stop_loss_pct = 0.035
        
        slippage = 0.0005
        entry_price_with_slippage = price * (1 + slippage)
        stop_loss = entry_price_with_slippage * (1 - stop_loss_pct)
        
        quantity = self.risk_manager.calculate_position_size(self.balance, entry_price_with_slippage, stop_loss)
        
        if quantity <= 0:
            return
        
        notional = price * quantity
        fee = notional * 0.0005
        self.balance -= fee
        
        self.positions[symbol] = {
            'entry_price': entry_price_with_slippage,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'highest_price': entry_price_with_slippage,
            'entry_time': timestamp,
            'leverage': leverage,
            'metrics': metrics or {}
        }
        
        print(f"[{timestamp}] OPEN LONG {symbol} @ {entry_price_with_slippage:.4f} | SL: {stop_loss:.4f} | Size: {quantity:.2f}")
    
    def load_data(self):
        """
        加载全市场597个币种的15分钟和1小时数据
        """
        data_dir = Path("/Users/muce/1m_data/new_backtest_data_1year_1m")
        self.data_feed = {}
        self.data_feed_1h = {}
        
        print(f"Loading ALL 597 coins from {data_dir}...")
        
        if not data_dir.exists():
            print(f"Error: {data_dir} does not exist!")
            return
        
        files = list(data_dir.glob("*.csv"))
        loaded_count = 0
        
        for file_path in files:
            try:
                symbol = file_path.stem
                
                # 读取1分钟数据
                df_1m = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
                
                # 重采样到15分钟
                df_15m = df_1m.resample('15min').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                })
                df_15m.dropna(inplace=True)
                
                # 重采样到1小时
                df_1h = df_1m.resample('1h').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                })
                df_1h.dropna(inplace=True)
                
                # === 性能优化: 预计算指标 ===
                # 1. 预计算技术指标 (RSI, ADX, VolMA)
                df_15m['rsi'] = ta.rsi(df_15m['close'], length=14)
                adx_df = ta.adx(df_15m['high'], df_15m['low'], df_15m['close'], length=14)
                df_15m['adx'] = adx_df['ADX_14']
                # 成交量均线 (20周期，模拟之前的 iloc[-21:-1].mean())
                df_15m['vol_ma'] = df_15m['volume'].rolling(window=20).mean().shift(1) # Shift 1 to exclude current candle
                
                # 预计算前高 (用于突破策略)
                df_15m['prev_high'] = df_15m['high'].shift(1)
                
                # 2. 预计算24小时涨幅 (处理数据缺失)
                # 创建完整的时间索引
                if not df_15m.empty:
                    full_idx = pd.date_range(start=df_15m.index[0], end=df_15m.index[-1], freq='15min')
                    # Reindex并前向填充价格，用于计算涨幅
                    df_full = df_15m.reindex(full_idx)
                    df_full['close_filled'] = df_full['close'].ffill()
                    
                    # 计算96周期(24h)涨幅
                    df_full['change_24h'] = df_full['close_filled'].pct_change(periods=96) * 100
                    
                    # 将计算结果映射回原始DataFrame
                    df_15m['change_24h'] = df_full.loc[df_15m.index, 'change_24h']
                
                # 清理NaN (指标计算初期会有NaN)
                df_15m.dropna(subset=['rsi', 'adx', 'vol_ma'], inplace=True)
                
                if len(df_15m) > 50 and len(df_1h) > 50:
                    self.data_feed[symbol] = df_15m
                    self.data_feed_1h[symbol] = df_1h
                    loaded_count += 1
                    
            except Exception as e:
                print(f"Error loading {file_path.name}: {e}")
        
        print(f"✅ Loaded {loaded_count} coins (15M + 1H data)")
    
    def _scan_market(self, current_time):
        """
        扫描市场，使用多时间框架确认
        """
        candidates = []
        
        for symbol, df_15m in self.data_feed.items():
            if symbol in self.positions:
                continue
            
            if symbol not in self.data_feed_1h:
                continue
            
            df_1h = self.data_feed_1h[symbol]
            
            # 确保有足够数据
            # available_15m = df_15m[df_15m.index <= current_time] # REMOVED SLICING
            # available_1h = df_1h[df_1h.index <= current_time]    # REMOVED SLICING
            
            # 直接检查当前时间点是否有数据
            if current_time not in df_15m.index:
                continue
                
            # 获取当前行
            current_row = df_15m.loc[current_time]
            
            # 检查是否有预计算的 change_24h
            if 'change_24h' not in current_row or pd.isna(current_row['change_24h']):
                continue
                
            change_pct = current_row['change_24h']
            
            # 涨幅筛选：已移除，直接扫描所有币种
            # if self.config.CHANGE_THRESHOLD_MIN <= change_pct <= self.config.CHANGE_THRESHOLD_MAX:
            
            # 直接检查1小时级别确认 (仅作参考)
            # 注意：这里我们仍然需要1小时的数据切片吗？
            # check_signal_1h 只需要 len(df_1h) > 50，而我们在 load_data 已经过滤了
            # 所以只要当前时间有1小时数据即可
            # 为了保持兼容性，我们可以传入一个伪造的df或者修改 check_signal_1h
            # 但最快的方法是：既然 check_signal_1h 总是返回 True (在当前策略中)，我们可以直接跳过它
            # 或者只检查当前时间点是否有1小时数据
            
            # 简化：假设1小时数据存在且足够（load_data已保证）
            confirmed_1h = True 
            
            if confirmed_1h:
                candidates.append({
                    'symbol': symbol,
                    'change_pct': change_pct,
                    'confirmed_1h': True,
                    'current_row': current_row # 传递当前行，避免再次查找
                })
        
        # 按涨幅排序
        candidates.sort(key=lambda x: x['change_pct'], reverse=True)
        # candidates = candidates[:self.config.TOP_GAINER_COUNT] # 移除Top N限制，扫描所有符合涨幅条件的币种
        
        # 对筛选出的候选进行15分钟信号检查
        for candidate in candidates:
            symbol = candidate['symbol']
            current_row = candidate['current_row']
            
            # 检查15分钟信号 (传入当前行而不是整个DataFrame切片)
            # 我们需要修改 check_signal 来接受 Series (单行) 或者我们构造一个只包含当前行的 DF
            # 但最好的方式是修改 check_signal 逻辑，让它支持直接传入 current_row
            
            # 为了不破坏继承结构，我们在 check_signal 内部做了适配
            # 但这里我们直接调用一个新的内部方法 _check_signal_fast
            signal = self._check_signal_fast(symbol, current_row)
            
            if signal and signal['side'] == 'LONG':
                # 添加1小时确认标记到metrics
                if 'metrics' not in signal:
                    signal['metrics'] = {}
                signal['metrics']['confirmed_1h'] = True
                signal['metrics']['change_24h'] = candidate['change_pct']
                
                # 标记下一根K线开盘入场
                next_candle_time = current_time + pd.Timedelta(minutes=15)
                if next_candle_time not in self.pending_entries:
                    self.pending_entries[next_candle_time] = []
                self.pending_entries[next_candle_time].append({
                    'symbol': symbol,
                    'signal': signal
                })

    def _check_signal_fast(self, symbol, row):
        """
        极速信号检查 (仅使用当前行数据，无DataFrame切片)
        """
        # 1. 突破确认
        if 'prev_high' not in row or pd.isna(row['prev_high']):
            return None
        if row['close'] <= row['prev_high']:
            return None
            
        # 2. 成交量确认
        if 'vol_ma' not in row or row['vol_ma'] == 0:
            return None
        if row['volume'] < 2.0 * row['vol_ma']:
            return None
            
        # 3. RSI范围
        if 'rsi' not in row or pd.isna(row['rsi']):
            return None
        if not (55 <= row['rsi'] <= 90):
            return None
            
        return {
            'symbol': symbol,
            'side': 'LONG',
            'entry_price': row['close'],
            'timestamp': row.name, # Series name is the index (timestamp)
            'metrics': {
                'rsi': row['rsi'],
                'adx': row.get('adx', 0),
                'volume_ratio': row['volume'] / row['vol_ma']
            }
        }

def main():
    print("="*60)
    print("多时间框架策略回测 (30天)")
    print("涨幅范围: 5% - 20%")
    print("确认: 1小时 + 15分钟")
    print("="*60)
    
    engine = MultiTimeframeEngine(initial_balance=100)
    engine.run(days=30)

if __name__ == "__main__":
    main()
