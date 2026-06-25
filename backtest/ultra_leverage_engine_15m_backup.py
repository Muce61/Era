#!/usr/bin/env python3
"""
超高杠杆回测引擎
Ultra-High Leverage Backtest Engine

支持:
- 多周期数据 (15m, 1h, 4h)
- 动态杠杆 50x-125x
- 极严格止损 0.3%
- 信号强度评分
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.ultra_leverage import MultiTimeframeStrategy
from config import ultra_leverage_config as config

class UltraLeverageBacktest:
    """超高杠杆回测引擎"""
    
    def __init__(self):
        # 加载杠杆信息
        self.leverage_map = self.load_leverage_brackets()
        
        self.strategy = MultiTimeframeStrategy(leverage_map=self.leverage_map)
        self.balance = config.INITIAL_BALANCE
        self.initial_balance = config.INITIAL_BALANCE
        self.positions = {}  # {symbol: position_dict}
        self.trades = []
        self.daily_stats = []
        
        # 加载多周期数据
        self.data_15m = {}
        self.data_1h = {}
        self.data_4h = {}
        
        max_lev = max(self.leverage_map.values()) if self.leverage_map else 0
        print("初始化超高杠杆回测引擎...")
        print(f"起始资金: ${self.balance}")
        print(f"最大杠杆: {max_lev}x (BTC/ETH)")
        print(f"硬止损: {config.STOP_LOSS_PERCENT}%")
        print(f"可用币种: {len(self.leverage_map)}个")
        
    def load_multiframe_data(self, symbols=None):
        """加载多周期数据 (从预处理目录) - 仅加载Top 50活跃币种"""
        print("\n加载多周期数据...")
        
        dir_15m = Path(config.DATA_DIR)
        dir_1h = Path("/Users/muce/1m_data/processed_1h_data")
        dir_4h = Path("/Users/muce/1m_data/processed_4h_data")
        
        if not dir_15m.exists() or not dir_1h.exists() or not dir_4h.exists():
            print(f"❌ 数据目录不完整")
            return
        
        # 获取所有可用币种
        files = list(dir_15m.glob("*USDT.csv"))
        temp_data = []
        
        print(f"扫描 {len(files)} 个币种并计算成交量...")
        
        for file in files:
            symbol = file.stem
            if symbol in config.EXCLUDED_COINS:
                continue
            
            # 仅加载有杠杆信息的币种
            if symbol not in self.leverage_map:
                continue
                
            try:
                # 预读计算成交量 (只读最后1000行以加速)
                df_preview = pd.read_csv(file)
                if len(df_preview) < 1000:
                    continue
                    
                avg_vol = (df_preview['close'] * df_preview['volume']).mean() # 美元成交量
                
                if avg_vol > 100000: # 最小日均成交量过滤
                    temp_data.append({
                        'symbol': symbol,
                        'file': file,
                        'avg_vol': avg_vol
                    })
                
            except Exception:
                continue
        
        # 按成交量排序，取Top 50
        temp_data.sort(key=lambda x: x['avg_vol'], reverse=True)
        top_coins = temp_data[:50]
        
        print(f"选取 Top {len(top_coins)} 活跃币种 (Vol > $100k)")
        
        loaded = 0
        for item in top_coins:
            symbol = item['symbol']
            file = item['file']
            
            try:
                # 1. 加载15m
                df_15m = pd.read_csv(file)
                df_15m['timestamp'] = pd.to_datetime(df_15m['timestamp'])
                df_15m = df_15m.set_index('timestamp').sort_index()
                self.data_15m[symbol] = df_15m
                
                # 2. 加载1h
                file_1h = dir_1h / f"{symbol}.csv"
                if file_1h.exists():
                    df_1h = pd.read_csv(file_1h)
                    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'])
                    df_1h = df_1h.set_index('timestamp').sort_index()
                    self.data_1h[symbol] = df_1h
                
                # 3. 加载4h
                file_4h = dir_4h / f"{symbol}.csv"
                if file_4h.exists():
                    df_4h = pd.read_csv(file_4h)
                    df_4h['timestamp'] = pd.to_datetime(df_4h['timestamp'])
                    df_4h = df_4h.set_index('timestamp').sort_index()
                    self.data_4h[symbol] = df_4h
                
                loaded += 1
                print(f"已加载: {symbol} (Vol: ${item['avg_vol']/1000:.0f}k)")
                
            except Exception as e:
                print(f"加载失败 {symbol}: {e}")
                continue
        
        print(f"✅ 成功加载 {loaded} 个活跃币种")
    
    def load_leverage_brackets(self):
        """加载杠杆信息 from leverage_brackets.csv"""
        leverage_file = Path('leverage_brackets.csv')
        if not leverage_file.exists():
            print("⚠️ leverage_brackets.csv not found, using default leverage")
            return {}
        
        df = pd.read_csv(leverage_file)
        leverage_map = {}
        
        # Symbol格式转换: BTCUSDT -> BTCUSDTUSDT
        for _, row in df.iterrows():
            symbol_raw = row['symbol']  # e.g., "BTCUSDT"
            symbol_data = symbol_raw + "USDT"  # e.g., "BTCUSDTUSDT" (匹配数据文件)
            leverage_map[symbol_data] = int(row['max_leverage'])
        
        print(f"\n💪 杠杆信息加载完成:")
        print(f"  总币种: {len(leverage_map)}")
        top_lev = sorted(leverage_map.items(), key=lambda x: x[1], reverse=True)[:3]
        for sym, lev in top_lev:
            print(f"  {sym}: {lev}x")
        
        return leverage_map
        
    def calculate_position_size(self, symbol, entry_price, stop_loss, leverage):
        """
        计算仓位大小 (高杠杆下)
        
        风险固定模型: 每笔风险 = 账户的 RISK_PER_TRADE%
        """
        risk_amount = self.balance * (config.RISK_PER_TRADE / 100)
        price_risk = abs(entry_price - stop_loss)
        
        if price_risk == 0:
            return 0
        
        # 计算合约数量
        quantity = risk_amount / price_risk
        
        # 考虑杠杆，实际占用保证金很小
        margin_required = (entry_price * quantity) / leverage
        
        # 确保不超过余额
        if margin_required > self.balance * 0.9:  # 最多用90%保证金
            quantity = (self.balance * 0.9 * leverage) / entry_price
        
        return quantity
    
    def open_position(self, symbol, side, entry_price, stop_loss, leverage, timestamp, strength, breakdown):
        """开仓"""
        quantity = self.calculate_position_size(symbol, entry_price, stop_loss, leverage)
        
        if quantity <= 0:
            return False
        
        # 计算需要的保证金
        notional = entry_price * quantity
        margin = notional / leverage
        fee = notional * config.BACKTEST_FEE
        
        # 检查余额
        if margin + fee > self.balance:
            return False
        
        # 扣除保证金和手续费
        self.balance -= (margin + fee)
        
        # 记录仓位
        self.positions[symbol] = {
            'side': side,
            'entry_price': entry_price,
            'quantity': quantity,
            'stop_loss': stop_loss,
            'leverage': leverage,
            'entry_time': timestamp,
            'margin': margin,
            'highest_price': entry_price if side == 'LONG' else entry_price,
            'lowest_price': entry_price if side == 'SHORT' else entry_price,
            'strength': strength,
            'breakdown': breakdown
        }
        
        print(f"[{timestamp}] 🚀 OPEN {side} {symbol} @ {entry_price:.4f}")
        print(f"  杠杆: {leverage}x | 数量: {quantity:.2f} | 止损: {stop_loss:.4f}")
        print(f"  信号强度: {strength}分 | 保证金: ${margin:.2f}")
        
        return True
    
    def close_position(self, symbol, exit_price, timestamp, reason):
        """平仓"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        
        # 计算PnL (考虑杠杆)
        if pos['side'] == 'LONG':
            price_change = exit_price - pos['entry_price']
        else:  # SHORT
            price_change = pos['entry_price'] - exit_price
        
        pnl_before_fee = price_change * pos['quantity']
        
        # 手续费
        notional = exit_price * pos['quantity']
        fee = notional * config.BACKTEST_FEE
        
        # 净PnL
        net_pnl = pnl_before_fee - fee
        
        # 更新余额 (释放保证金 + PnL)
        self.balance += pos['margin'] + net_pnl
        
        # ROI = PnL / Margin
        roi = (net_pnl / pos['margin']) * 100
        
        # 记录交易
        self.trades.append({
            'symbol': symbol,
            'side': pos['side'],
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'entry_time': pos['entry_time'],
            'exit_time': timestamp,
            'quantity': pos['quantity'],
            'leverage': pos['leverage'],
            'pnl': net_pnl,
            'roi': roi,
            'reason': reason,
            'duration': (timestamp - pos['entry_time']),
            'signal_strength': pos['strength'],
            'balance_after': self.balance
        })
        
        print(f"[{timestamp}] ❌ CLOSE {symbol} @ {exit_price:.4f}")
        print(f"  PnL: ${net_pnl:.2f} | ROI: {roi:.1f}% | 原因: {reason}")
        print(f"  余额: ${self.balance:.2f}")
        
        # 实时保存交易记录
        pd.DataFrame(self.trades).to_csv('ultra_leverage_backtest.csv', index=False)
        
        # 删除仓位
        del self.positions[symbol]
    
    def manage_positions(self, current_time):
        """管理持仓 - 极严格止损"""
        to_close = []
        
        for symbol, pos in self.positions.items():
            # 获取当前价格
            if symbol not in self.data_15m:
                print(f"DEBUG: {symbol} not in data_15m")
                continue
            
            df = self.data_15m[symbol]
            if current_time not in df.index:
                # 尝试容错：找最近的前一个时间点
                idx = df.index.asof(current_time)
                if pd.isna(idx):
                    continue
                candle = df.loc[idx]
            else:
                candle = df.loc[current_time]
            
            high = candle['high']
            low = candle['low']
            close = candle['close']
            
            # print(f"DEBUG: Managing {symbol} at {current_time} | Close: {close}")
            
            # === Layer 1: 硬止损 (0.3%) ===
            if pos['side'] == 'LONG':
                if low <= pos['stop_loss']:
                    to_close.append((symbol, pos['stop_loss'], 'Hard Stop Loss'))
                    continue
            else:  # SHORT
                if high >= pos['stop_loss']:
                    to_close.append((symbol, pos['stop_loss'], 'Hard Stop Loss'))
                    continue
            
            # === Layer 2: 时间止损 (15分钟) ===
            holding_minutes = (current_time - pos['entry_time']).total_seconds() / 60
            if holding_minutes > config.TIME_STOP_MINUTES:
                # 计算当前PnL
                if pos['side'] == 'LONG':
                    pnl_pct = (close - pos['entry_price']) / pos['entry_price'] * 100
                else:
                    pnl_pct = (pos['entry_price'] - close) / pos['entry_price'] * 100
                
                if pnl_pct < 0:
                    to_close.append((symbol, close, f'Time Stop ({int(holding_minutes)}min)'))
                    continue
            
            # === 追踪止盈 ===
            if pos['side'] == 'LONG':
                if high > pos['highest_price']:
                    pos['highest_price'] = high
                
                # 计算最高点PnL
                max_pnl_pct = (pos['highest_price'] - pos['entry_price']) / pos['entry_price'] * 100
                
                # 如果达到快速止盈目标
                if max_pnl_pct >= config.TAKE_PROFIT_QUICK:
                    # 回撤超过阈值就止盈
                    current_pnl_pct = (close - pos['entry_price']) / pos['entry_price'] * 100
                    drawdown = max_pnl_pct - current_pnl_pct
                    
                    if drawdown >= config.TRAILING_CALLBACK_PERCENT:
                        to_close.append((symbol, close, f'Trailing TP (Max {max_pnl_pct:.1f}%)'))
                        continue
            
            else:  # SHORT
                if low < pos['lowest_price']:
                    pos['lowest_price'] = low
                
                max_pnl_pct = (pos['entry_price'] - pos['lowest_price']) / pos['entry_price'] * 100
                
                if max_pnl_pct >= config.TAKE_PROFIT_QUICK:
                    current_pnl_pct = (pos['entry_price'] - close) / pos['entry_price'] * 100
                    drawdown = max_pnl_pct - current_pnl_pct
                    
                    if drawdown >= config.TRAILING_CALLBACK_PERCENT:
                        to_close.append((symbol, close, f'Trailing TP (Max {max_pnl_pct:.1f}%)'))
                        continue
        
        # 执行平仓
        for symbol, price, reason in to_close:
            self.close_position(symbol, price, current_time, reason)
    
    def run(self, start_date, end_date):
        """运行回测"""
        print(f"\n开始回测: {start_date} 到 {end_date}")
        print("="*60)
        
        # 生成时间序列 (15分钟)
        current = start_date
        iterations = 0
        
        while current <= end_date:
            iterations += 1
            
            # 1. 管理现有持仓
            self.manage_positions(current)
            
            # 2. 检查新信号 (如果未满仓)
            if len(self.positions) < config.MAX_OPEN_POSITIONS:
                self.scan_and_open(current)
            
            # 进度显示
            if iterations % 96 == 0:  # 每天打印一次
                print(f"⏳ {current} | 余额: ${self.balance:.2f} | 持仓: {len(self.positions)}")
            
            # 下一个时间点
            current += timedelta(minutes=15)
        
        # 强制平掉所有剩余仓位
        for symbol in list(self.positions.keys()):
            if symbol in self.data_15m:
                final_price = self.data_15m[symbol].iloc[-1]['close']
                self.close_position(symbol, final_price, end_date, 'End of Backtest')
        
        self.generate_report()
    
    def scan_and_open(self, current_time):
        """扫描并开仓"""
        # 扫描所有已加载数据的币种 (已在加载时过滤Top 50)
        symbols = list(self.data_15m.keys())
        
        for symbol in symbols:
            # 跳过已有仓位
            if symbol in self.positions:
                continue
            
            # 获取多周期数据
            if symbol not in self.data_15m or symbol not in self.data_1h or symbol not in self.data_4h:
                continue
            
            df_15m = self.data_15m[symbol].loc[:current_time]
            df_1h = self.data_1h[symbol].loc[:current_time]
            df_4h = self.data_4h[symbol].loc[:current_time]
            
            if len(df_15m) < 300 or len(df_1h) < 300 or len(df_4h) < 300:
                continue
            
            # 检查信号
            signal = self.strategy.check_signal(
                symbol,
                {'15m': df_15m.tail(300), '1h': df_1h.tail(300), '4h': df_4h.tail(300)},
                current_time
            )
            
            if signal is None:
                continue
            
            # 开仓
            entry_price = df_15m.iloc[-1]['close']
            
            # 计算止损
            if signal['side'] == 'LONG':
                stop_loss = entry_price * (1 - config.STOP_LOSS_PERCENT / 100)
            else:
                stop_loss = entry_price * (1 + config.STOP_LOSS_PERCENT / 100)
            
            # 执行开仓
            success = self.open_position(
                symbol,
                signal['side'],
                entry_price,
                stop_loss,
                signal['leverage'],
                current_time,
                signal['strength'],
                signal['breakdown']
            )
            
            if success:
                break  # 每次只开一个新仓
    
    def generate_report(self):
        """生成报告"""
        print("\n" + "="*60)
        print("📊 超高杠杆回测报告")
        print("="*60)
        
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        
        print(f"\n💰 资金表现:")
        print(f"  起始: ${self.initial_balance:.2f}")
        print(f"  最终: ${self.balance:.2f}")
        print(f"  收益率: {total_return:.2f}%")
        
        if not self.trades:
            print("\n⚠️ 无交易记录")
            return
        
        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] <= 0]
        
        print(f"\n📈 交易统计:")
        print(f"  总交易: {len(self.trades)}")
        print(f"  盈利: {len(wins)} ({len(wins)/len(self.trades)*100:.1f}%)")
        print(f"  亏损: {len(losses)} ({len(losses)/len(self.trades)*100:.1f}%)")
        print(f"  **胜率: {len(wins)/len(self.trades)*100:.1f}%**")
        
        if wins:
            avg_win_roi = np.mean([t['roi'] for t in wins])
            print(f"  平均盈利ROI: {avg_win_roi:.1f}%")
        if losses:
            avg_loss_roi = np.mean([t['roi'] for t in losses])
            print(f"  平均亏损ROI: {avg_loss_roi:.1f}%")
        
        # 按杠杆分组
        print(f"\n⚡ 杠杆使用分布:")
        df_trades = pd.DataFrame(self.trades)
        for lev in sorted(df_trades['leverage'].unique()):
            lev_trades = df_trades[df_trades['leverage'] == lev]
            lev_wins = len(lev_trades[lev_trades['pnl'] > 0])
            print(f"  {lev}x: {len(lev_trades)}笔 (胜率{lev_wins/len(lev_trades)*100:.0f}%)")
        
        # 保存结果
        df_trades.to_csv('ultra_leverage_backtest.csv', index=False)
        print(f"\n✅ 详细结果已保存至: ultra_leverage_backtest.csv")

if __name__ == "__main__":
    backtest = UltraLeverageBacktest()
    backtest.load_multiframe_data()
    
    # 运行11月回测 (最近一个月)
    backtest.run(
        start_date=datetime(2025, 11, 1),
        end_date=datetime(2025, 11, 30)
    )
