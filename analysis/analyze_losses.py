"""
亏损单特征深度分析脚本 (Loss Pattern Analysis)

功能:
1. 读取 backtest_trades_october.csv 中的亏损交易
2. 重新加载对应币种的 15m K线数据
3. 计算开仓时刻的各项指标 (RSI, EMA, Volume, ATR, Candle Pattern)
4. 统计亏损单的共性特征
"""

import sys
from pathlib import Path
import pandas as pd
import pandas_ta as ta
import numpy as np

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from config.settings import Config

def load_data_for_symbol(symbol, data_dir):
    """Load and resample data for a specific symbol"""
    file_path = data_dir / f"{symbol}.csv"
    if not file_path.exists():
        return None
        
    try:
        df = pd.read_csv(file_path, parse_dates=['timestamp'], index_col='timestamp')
        
        # Resample to 15m
        agg_dict = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }
        
        # Handle column names
        available_cols = df.columns.tolist()
        final_agg = {}
        for col, func in agg_dict.items():
            if col in available_cols:
                final_agg[col] = func
            elif col.capitalize() in available_cols:
                final_agg[col.capitalize()] = func
                
        if not final_agg:
            return None
            
        df_15m = df.resample('15min').agg(final_agg).dropna()
        df_15m.columns = [c.lower() for c in df_15m.columns]
        return df_15m
    except Exception:
        return None

def calculate_indicators(df):
    """Calculate technical indicators"""
    # RSI
    df['rsi'] = ta.rsi(df['close'], length=14)
    
    # EMA
    df['ema20'] = ta.ema(df['close'], length=20)
    df['ema50'] = ta.ema(df['close'], length=50)
    df['ema200'] = ta.ema(df['close'], length=200)
    
    # ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    # Volume MA
    df['vol_ma'] = ta.sma(df['volume'], length=20)
    
    return df

def analyze_losses():
    print("="*80)
    print("🔍 亏损单特征深度分析")
    print("="*80)
    
    # 1. Load Trades
    trades_path = Path('backtest_results/csv/backtest_trades_october.csv')
    if not trades_path.exists():
        print(f"Error: {trades_path} not found.")
        return
        
    trades = pd.read_csv(trades_path)
    losing_trades = trades[trades['pnl'] < 0].copy()
    winning_trades = trades[trades['pnl'] > 0].copy()
    
    print(f"总交易: {len(trades)}")
    print(f"亏损单: {len(losing_trades)}")
    print(f"盈利单: {len(winning_trades)}")
    
    data_dir = Path('/Users/muce/1m_data/new_backtest_data_1year_1m')
    
    loss_stats = {
        'rsi': [],
        'price_vs_ema20': [],
        'price_vs_ema200': [],
        'vol_vs_ma': [],
        'atr_pct': [],
        'hour': []
    }
    
    win_stats = {
        'rsi': [],
        'price_vs_ema20': [],
        'price_vs_ema200': [],
        'vol_vs_ma': [],
        'atr_pct': [],
        'hour': []
    }
    
    # Helper to process trades
    def process_trade_list(trade_list, stats_dict):
        for _, trade in trade_list.iterrows():
            symbol = trade['symbol']
            entry_time = pd.Timestamp(trade['entry_time'])
            
            # Load data
            df = load_data_for_symbol(symbol, data_dir)
            if df is None:
                continue
                
            # Calculate indicators
            df = calculate_indicators(df)
            
            # Get data at entry time
            if entry_time not in df.index:
                # Try to find nearest previous index
                idx_loc = df.index.get_indexer([entry_time], method='pad')[0]
                if idx_loc == -1:
                    continue
                row = df.iloc[idx_loc]
            else:
                row = df.loc[entry_time]
                
            # Collect stats
            if pd.notna(row['rsi']):
                stats_dict['rsi'].append(row['rsi'])
            
            if pd.notna(row['ema20']):
                stats_dict['price_vs_ema20'].append((row['close'] - row['ema20']) / row['ema20'])
                
            if pd.notna(row['ema200']):
                stats_dict['price_vs_ema200'].append((row['close'] - row['ema200']) / row['ema200'])
                
            if pd.notna(row['vol_ma']) and row['vol_ma'] > 0:
                stats_dict['vol_vs_ma'].append(row['volume'] / row['vol_ma'])
                
            if pd.notna(row['atr']):
                stats_dict['atr_pct'].append(row['atr'] / row['close'])
                
            stats_dict['hour'].append(entry_time.hour)

    print("\n正在分析亏损单数据 (可能需要几分钟)...")
    process_trade_list(losing_trades, loss_stats)
    
    print("正在分析盈利单数据 (作为对比)...")
    process_trade_list(winning_trades, win_stats)
    
    # Analysis Report
    print("\n" + "="*60)
    print("📊 分析报告: 亏损单 vs 盈利单")
    print("="*60)
    
    def print_stat(name, key, is_pct=False):
        l_vals = np.array(loss_stats[key])
        w_vals = np.array(win_stats[key])
        
        if len(l_vals) == 0 or len(w_vals) == 0:
            print(f"{name}: 数据不足")
            return
            
        l_mean = np.mean(l_vals)
        w_mean = np.mean(w_vals)
        
        fmt = "{:.2%}" if is_pct else "{:.2f}"
        print(f"{name}:")
        print(f"  亏损单均值: {fmt.format(l_mean)}")
        print(f"  盈利单均值: {fmt.format(w_mean)}")
        print(f"  差异: {fmt.format(l_mean - w_mean)}")
        
    print_stat("RSI (相对强弱)", 'rsi')
    print_stat("价格 vs EMA20 (短期乖离)", 'price_vs_ema20', True)
    print_stat("价格 vs EMA200 (长期乖离)", 'price_vs_ema200', True)
    print_stat("成交量倍数 (Volume Ratio)", 'vol_vs_ma')
    print_stat("波动率 (ATR%)", 'atr_pct', True)
    
    print("\n🕒 亏损高发时段 (Top 3):")
    from collections import Counter
    loss_hours = Counter(loss_stats['hour'])
    for h, count in loss_hours.most_common(3):
        print(f"  {h}点: {count}笔")
        
    print("\n💡 关键发现:")
    # Simple heuristic analysis
    l_rsi = np.mean(loss_stats['rsi'])
    w_rsi = np.mean(win_stats['rsi'])
    if l_rsi > w_rsi + 5:
        print("- 亏损单倾向于在 RSI 较高时开仓 (追高风险)")
    elif l_rsi < w_rsi - 5:
        print("- 亏损单倾向于在 RSI 较低时开仓 (抄底失败)")
        
    l_vol = np.mean(loss_stats['vol_vs_ma'])
    w_vol = np.mean(win_stats['vol_vs_ma'])
    if l_vol < w_vol * 0.8:
        print("- 亏损单的成交量显著小于盈利单 (假突破)")
        
    l_trend = np.mean(loss_stats['price_vs_ema200'])
    if l_trend < 0:
        print("- 亏损单平均处于 EMA200 下方 (逆势操作)")

if __name__ == "__main__":
    analyze_losses()
