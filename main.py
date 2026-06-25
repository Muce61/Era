import sys
import io
# FORCE UTF-8 for Windows Console to support Emojis
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import time
import threading
from datetime import datetime, timezone, timedelta
from config.settings import Config
from data.binance_client import BinanceClient
from data.websocket_monitor import MarketMonitor
from strategy.momentum import MomentumStrategy
from strategy.quality_filter import QualityFilterModule as QualityFilter
from risk.manager import RiskManager
from risk.trend_reversal_detector import TrendReversalDetector
from strategy.smart_exit import SmartExitModule
from execution.executor import Executor
from monitor.logger import setup_logger
import logging
import pandas as pd
from monitor.universe_recorder import UniverseRecorder

# 动态杠杆策略模块
from leverage_strategies.signal_confidence import SignalConfidenceModule

class TradingBot:
    def __init__(self):
        self.logger = setup_logger()
        setup_logger('market_monitor', 'main.log') # Ensure WS logs are captured
        self.config = Config()
        
        self.client = BinanceClient()
        self.executor = Executor()
        self.strategy = MomentumStrategy()
        self.universe_recorder = UniverseRecorder()
        
        # Universe Consistency (Daily Update)
        self.last_universe_update_date = None
        
        # 初始化信号置信度模块 (动态杠杆)
        self.leverage_strategy = SignalConfidenceModule()
        self.logger.info("已启用: 信号置信度驱动动态杠杆策略")
        self.risk_manager = RiskManager()
        
        # 初始化趋势反转检测器 (熔断机制)
        self.trend_detector = TrendReversalDetector()
        self.logger.info("已启用: 趋势反转熔断机制 (三层防御)")
        
        # 初始化智能离场模块 (对齐回测逻辑)
        self.smart_exit = SmartExitModule()
        self.logger.info("已启用: 智能离场模块 (动态追踪 + 保本止损)")
        
        self.quality_filter = QualityFilter() # New: Backtest Alignment
        
        self.active_symbols = set() # Symbols we are monitoring/trading
        self.positions = {} # {symbol: position_data}
        self.paper_positions = {} # {symbol: position_data} (虚拟持仓)
        
        self.monitor = MarketMonitor(kline_callback=self.on_kline_update) # Event-Driven Callback
    
        self.lock = threading.Lock() # Thread safety for shared resources
        # self.trade_logger = setup_logger('trade_logger', 'trades.log') # Disabled per user request
        self.trade_logger = logging.getLogger('trade_logger_null')
        self.trade_logger.addHandler(logging.NullHandler())
        
        from monitor.trade_recorder import TradeRecorder
        self.recorder = TradeRecorder()

        # Cache for volume ranking
        self.coin_volume_ranking = {}
        self.TOP_N_COINS = 200
        
    def start(self):
        self.logger.info("正在启动交易机器人...")
        self.trade_logger.info("交易机器人启动 - 交易日志")
        
        # 0. Self-Diagnostic Test (User Request)
        self.run_self_diagnostic()
        
        # 1. Sync Existing Positions (Recovery Mode)
        self.sync_existing_positions()

    def run_self_diagnostic(self):
        """
        Start-up Test: Buy min BTC, check SL, close immediately.
        Abort if SL fails.
        """
        symbol = 'ETHUSDT' if not self.config.TESTNET else 'ETH/USDT:USDT' 
        # Ensure mapping matches system
        if 'ETH/USDT:USDT' in self.active_symbols or True: # Force check
             symbol_internal = 'ETH/USDT:USDT'
             
        self.logger.info(f"🧪 [自检程序] 启动: 尝试使用最小单位做多 {symbol_internal} 测试止损...")
        
        try:
            # 1. Buy Min Quantity (0.01 ETH => ~40 USDT > 20 USDT Min. Margin ~2U. Safe)
            qty = 0.01
            
            # Explicitly set leverage for test
            self.executor.set_leverage(symbol_internal, 20)
            
            # Place Order
            self.logger.info(f"🧪 [自检程序] 1. 开仓 (Market Buy {qty} ETH)...")
            order = self.executor.place_order(symbol_internal, 'BUY', qty, 'MARKET')
            if not order or 'id' not in order:
                self.logger.error("❌ [自检失败] 开仓订单失效，终止程序")
                import sys; sys.exit(1)
            
            # Helper to get entry price
            entry_price = float(order.get('average', 0))
            if entry_price == 0:
                # Fallback if average not returned immediately, fetch ticker
                ticker = self.client.get_ticker(symbol_internal)
                entry_price = float(ticker['last'])
            
            # Place Stop Loss (1% below)
            stop_price = entry_price * 0.99
            self.logger.info(f"🧪 [自检程序] 1.1 设置止损 (Algo) @ {stop_price}...")
            self.executor.place_stop_loss(symbol_internal, 'BUY', qty, stop_price)
                
            time.sleep(3) # Wait for callbacks/SL placement
            
            # 2. Verify Stop Loss
            self.logger.info(f"🧪 [自检程序] 2. 验证止损单 (Algo/Standard)...")
            
            # Check Standard Orders first
            orders = self.client.exchange.fetch_open_orders(symbol_internal)
            sl_found = False
            for o in orders:
                if o['type'] in ['STOP', 'STOP_MARKET']:
                    self.logger.info(f"   ✅ [普通接口] 发现止损单: ID {o['id']} @ {o.get('stopPrice')}")
                    sl_found = True
                    break
            
            # Check Algo Orders if not found (Retry Mechanism)
            if not sl_found:
                for attempt in range(3):
                    algo_orders = self.executor.fetch_open_algo_orders(symbol_internal)
                    # self.logger.info(f"🔍 [Debug] Raw Algo Orders: {algo_orders}") 
                    
                    found_in_loop = False
                    for o in algo_orders:
                        # Algo order structure might differ
                        o_type = o.get('algoType') or o.get('type')
                        if o_type in ['CONDITIONAL', 'STOP_MARKET']: 
                            self.logger.info(f"   ✅ [Algo接口] 发现止损单: ID {o.get('clientAlgoId') or o.get('algoId')} @ {o.get('triggerPrice')}")
                            sl_found = True
                            found_in_loop = True
                            break
                    
                    if found_in_loop:
                        break
                    else:
                        if attempt < 2:
                            self.logger.warning(f"   ⚠️ 未检测到Algo单，等待重试 ({attempt+1}/3)...")
                            time.sleep(2)

            if not sl_found:
                self.logger.error("❌ [自检失败] 未检测到止损单! 系统将紧急平仓并退出")
                # Attempt Close
                self.executor.cancel_all_orders(symbol_internal)
                self.executor.place_order(symbol_internal, 'SELL', qty, 'MARKET')
                import sys; sys.exit(1)
            else:
                self.logger.info("✅ [自检成功] 止损功能正常")
            
            # 3. Logic Simulation (Smart Exit)
            self.logger.info(f"🧪 [自检程序] 3. 模拟移动止盈逻辑 (Code Logic Verification)...")
            try:
                # Mock Position
                mock_pos = {
                    'symbol': 'MOCK/USDT',
                    'entry_price': 2000.0,
                    'quantity': 1.0,
                    'highest_price': 2000.0,
                    'entry_time': datetime.now(),
                    'leverage': 20,
                    'side': 'BUY'
                }
                
                # A. Simulate Pump (2000 -> 3000, +50%)
                # This should update highest_price but NOT exit yet (unless pullback)
                self.smart_exit.check_exit(mock_pos, 3000.0, datetime.now())
                
                if mock_pos['highest_price'] == 3000.0:
                     self.logger.info("   ✅ 逻辑验证 A: 最高价更新正常 (2000 -> 3000)")
                else:
                     self.logger.error(f"   ❌ 逻辑验证 A 失败: highest_price = {mock_pos['highest_price']}")
                
                # B. Simulate Pullback (3000 -> 2600, -13% from high, still +30% ROI)
                # Max ROE = 50% * 20 = 1000% !!
                # Trailing activation is 30% ROE. Callback is 5-10%.
                # Here pullback is large. Should trigger.
                should_exit, reason, price = self.smart_exit.check_exit(mock_pos, 2600.0, datetime.now())
                
                if should_exit:
                    self.logger.info(f"   ✅ 逻辑验证 B: 移动止盈触发正常 ({reason})")
                else:
                    self.logger.error("   ❌ 逻辑验证 B 失败: 未触发移动止盈")
                    
            except Exception as logic_e:
                 self.logger.error(f"   ❌ 逻辑模拟异常: {logic_e}")

            # 4. Always Close (Real Trade)
            self.logger.info(f"🧪 [自检程序] 4. 平仓清理 (Closing Real Trade)...")
            self.executor.cancel_all_orders(symbol_internal) # Cancel SL first
            self.executor.place_order(symbol_internal, 'SELL', qty, 'MARKET')
            
            # 5. Final Cleanup of Algo Orders (Iterative)
            self.executor.cancel_all_algo_orders(symbol_internal)
            
            self.logger.info(f"✅ [自检完成] 交易功能 & 核心逻辑验证通过")
            
        except Exception as e:
            self.logger.error(f"❌ [自检异常] {e}")
            # Emergency Close Attempt
            try:
                self.executor.place_order(symbol_internal, 'SELL', qty, 'MARKET')
            except:
                pass
            import sys; sys.exit(1)

        
        # 2. Initial Top Gainers Scan
        self.scan_top_gainers()
        
        # 3. Initial Historical Check (New Feature)
        # DISABLE FOR STRICT CONSISTENCY (Avoid Late Entry on Startup)
        # self.check_historical_signals()
        
        # 4. Start WebSocket
        self.monitor.symbols = self.active_symbols
        self.monitor.start()
        
        # 5. Main Loop (Periodic Scan & Position Management)
        # 5. Main Loop (Periodic Scan & Position Management)
        # 5. Main Loop (Periodic Scan & Position Management)
        # 5. Main Loop (Periodic Scan & Position Management)
        try:
            last_scan_time = 0
            while True:
                current_time = time.time()
                
                # A. High Frequency: Manage Positions (Every 0.1s)
                # This ensures "Soft Logic" (Smart Exit) checks price frequently so we don't miss peaks.
                self.manage_positions()
                
                # B. Low Frequency: Scan & Strategy (Every 60s)
                if current_time - last_scan_time >= 60:
                    self.logger.info(f"🔄 [周期扫描] 执行分钟级扫描任务...")
                    self.scan_top_gainers()
                    
                    # NOTE: Strategy execution is now EVENT-DRIVEN via WebSocket (on_kline_update)
                    # We NO LONGER poll 'process_strategy_safe' here.
                    # This eliminates latency and aligns perfectly with Backtest (Candle Close).
                        
                    self.log_market_status() # New logging function
                    
                    last_scan_time = current_time
                    
                time.sleep(0.1) # 100ms Tickefly to prevent CPU spinning, but fast enough for sub-second checks
                time.sleep(0.1)

        except KeyboardInterrupt:
            self.stop()

    def sync_existing_positions(self):
        """
        Recover active positions from the exchange on startup.
        """
        self.logger.info("🔄 正在从交易所同步持仓信息...")
        try:
            # We need to access the exchange directly or verify if client has get_positions
            # using internal ccxt object for now as client wrapper might not have it
            positions = self.client.exchange.fetch_positions()
            active_list = [p for p in positions if float(p['contracts']) > 0]
            
            for p in active_list:
                symbol = p['symbol']
                # CCXT symbol might differ, ensure format matches internal
                # internal: usually 'ETH/USDT:USDT' or 'ETH/USDT' depending on usage.
                # logs show 'RIVER/USDT:USDT'.
                
                qty = float(p['contracts'])
                entry_price = float(p['entryPrice'])
                leverage = int(p.get('leverage') or 20)
                
                self.logger.info(f"🔍 发现交易所持仓: {symbol} x {qty} @ {entry_price}")
                
                # Check for existing Open Orders (Stop Loss)
                # 1. Check Standard Orders first (Legacy/Exchange dependent)
                orders = self.client.exchange.fetch_open_orders(symbol)
                stop_loss_price = 0
                sl_order_id = None
                
                for o in orders:
                    # Look for STOP orders
                    if o['type'] in ['STOP', 'STOP_MARKET']:
                        stop_loss_price = float(o.get('stopPrice', o.get('price', 0)))
                        sl_order_id = o['id']
                        self.logger.info(f"   -> 发现关联止损单 (Standard): ID {sl_order_id} @ {stop_loss_price}")
                        break
                
                # 2. Check Algo Orders if not found (CRITICAL FIX for Zombie Orders)
                if stop_loss_price == 0:
                    self.logger.info(f"   -> Standard SL not found, scanning Algo Orders for {symbol}...")
                    try:
                        # Use Executor's method which handles auth/signing manualy if needed
                        algo_orders = self.executor.fetch_open_algo_orders(symbol)
                        for o in algo_orders:
                             # Algo order structure might differ (clientAlgoId vs algoId)
                            o_type = o.get('algoType') or o.get('type')
                            if o_type in ['CONDITIONAL', 'STOP_MARKET']: 
                                 # Check if it's a STOP LOSS (reduceOnly or triggered by price)
                                 trigger_price = float(o.get('triggerPrice', 0))
                                 if trigger_price > 0:
                                    stop_loss_price = trigger_price
                                    sl_order_id = o.get('clientAlgoId') or o.get('algoId')
                                    self.logger.info(f"   ✅ [Algo接口] 发现关联止损单: ID {sl_order_id} @ {stop_loss_price}")
                                    break
                    except Exception as e:
                        self.logger.warning(f"   ⚠️ Algo Order scan failed for {symbol}: {e}")
                
                # If no SL found, we calculate a default one based on current config/ATR?
                # For safety, if no SL, we mark it. manage_positions might set one if logic permits,
                # or we just rely on Smart Exit.
                # Let's set a wide emergency SL if none found, to trigger management?
                # Actually, if we set 0, manage_positions need to handle it.
                if stop_loss_price == 0:
                    # Fallback: 10% below entry for safety until managed?
                    # Or better: let smart strategies handle it.
                    # But structure requires 'stop_loss'.
                    stop_loss_price = entry_price * 0.9  # Loose safety net
                    self.logger.warning(f"   ⚠️ 未找到止损单, 设置临时安全止损: {stop_loss_price}")

                position_data = {
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'quantity': qty,
                    'stop_loss': stop_loss_price,
                    'highest_price': entry_price, # Reset tracking
                    'entry_time': datetime.now(), # Reset time
                    'leverage': leverage,
                    'is_paper': False,
                    'side': 'BUY'
                }
                
                with self.lock:
                    self.positions[symbol] = position_data
                    self.active_symbols.add(symbol)
            
            if not active_list:
                self.logger.info("✅ 无现有持仓需要恢复")
            else:
                self.logger.info(f"✅ 已恢复 {len(self.positions)} 个持仓")
                
        except Exception as e:
            self.logger.error(f"❌ 同步持仓失败: {e}")

    def process_strategy_safe(self, symbol):
        """
        Safely fetch data and process strategy for a symbol.
        """
        try:
            # Fetch recent klines (enough for strategy)
            # Strategy needs ~50 candles, but ADX/EMA needs warmup (200+)
            df = self.client.get_historical_klines(symbol, timeframe=self.config.TIMEFRAME, limit=300)
            
            # FIX: Drop the last candle if it's incomplete (active)
            # Binance API usually returns the incomplete candle as the last row
            if not df.empty:
                # Ensure timestamps are localized to UTC for comparison
                if df['timestamp'].dt.tz is None:
                     df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
                
                # USER REQUEST (2025-12-09): Enable minute-level opening (Intra-bar execution)
                # Do NOT drop the last candle. Use the developing candle for signals.
                pass
            
            if not df.empty:
                self.process_strategy(symbol, df)
        except Exception as e:
            self.logger.error(f"策略处理失败 {symbol}: {e}")

    def check_historical_signals(self):
        """
        Check for signals immediately upon startup using recent history.
        """
        self.logger.info("正在执行启动时历史数据检查...")
        for symbol in self.active_symbols:
            try:
                df = self.client.get_historical_klines(symbol, timeframe=self.config.TIMEFRAME, limit=50)
                if not df.empty:
                    self.process_strategy(symbol, df)
            except Exception as e:
                self.logger.error(f"历史检查 {symbol} 失败: {e}")
        self.logger.info("启动时检查完成")

    def log_market_status(self):
        """
        Log detailed status of top 20 coins to CSV (Snapshot).
        """
        # self.logger.info("正在更新市场状态CSV...")
        csv_file = "logs/market_status.csv"
        
        data_rows = []
        for symbol in self.active_symbols:
            try:
                # Fetch latest data (small limit for check)
                df = self.client.get_historical_klines(symbol, timeframe=self.config.TIMEFRAME, limit=25)
                if df.empty:
                    continue
                    
                metrics = self.strategy.calculate_signal_score(df)
                
                price = df['close'].iloc[-1]
                
                change = 0.0
                if hasattr(self, 'top_gainers_data'):
                    for t in self.top_gainers_data:
                        if t[0] == symbol:
                            change = float(t[1]['percentage'])
                            break
                            
                volume = df['volume'].iloc[-1]
                pattern_str = "看涨" if metrics.get('pattern') else "震荡/跌"
                status_str = metrics.get('status', '未知')
                
                data_rows.append({
                    "币种": symbol,
                    "价格": price,
                    "涨幅%": change,
                    "成交量": volume,
                    "K线形态": pattern_str,
                    "状态": status_str,
                    "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
            except Exception as e:
                self.logger.error(f"获取 {symbol} 状态失败: {e}")
        
        # Write to CSV (Overwrite)
        if data_rows:
            df_status = pd.DataFrame(data_rows)
            df_status.to_csv(csv_file, index=False, encoding='utf-8-sig')

    def stop(self):
        self.logger.info("正在停止交易机器人...")
        self.monitor.stop()

    def calculate_momentum_96m(self, symbol):
        """
        Fetch 1m Klines and calculate change over 96 steps.
        Matches Backtest Logic: df.iloc[-1] vs df.iloc[-96].
        """
        try:
            # We need 97 candles to compare index "0" vs index "-1" (steps=96)
            # Fetch 100 to be safe
            # Use '1m' explicitly, distinct from config.TIMEFRAME
            df = self.client.get_historical_klines(symbol, timeframe='1m', limit=100)
            
            if df.empty or len(df) < 97:
                return None
                
            # Current Close (Last closed candle or developing? Backtest uses df.iloc[row_loc] which is current)
            # Note: client.get_historical_klines returns completed candles + developing candle usually?
            # Actually, standard impl returns closed candles mostly unless configured.
            # Assuming dataframe tail is "Now".
            
            current_close = df['close'].iloc[-1]
            prev_close = df['close'].iloc[-97] # -1 is current, -97 is 96 steps ago. 
            # Logic: (Current - Prev) / Prev
            # e.g. [0, 1, 2] -> (2-0)/0 is 2 step change. iloc[-1] vs iloc[-3].
            
            if prev_close == 0:
                return 0.0
                
            change_pct = (current_close - prev_close) / prev_close * 100
            return change_pct
            
        except Exception:
            return None


    def scan_top_gainers(self):
        """
        Fetch top gainers and update active symbols.
        Now includes Quality Filter and Volume Ranking (Backtest Alignment).
        """
        try:
            # 1. Fetch ALL tickers for Global Ranking
            tickers = self.client.get_usdt_tickers()
            
            # 2. Update Volume Ranking (Global) - The "Rolling Universe"
            # 2. Update Universe (Volume Ranking) - STRICT BACKTEST ALIGNMENT
            # Backtest updates Universe DAILY (at 00:00).
            # Live Bot was updating Minutely. This caused discrepancy (Live catching intra-day pumps Backtest missed).
            # Fix: Only update ranking if Date changes (00:00 UTC).
            
            current_date = datetime.now(timezone.utc).date()
            
            # Initialize if empty (First Run) or New Day
            if not self.coin_volume_ranking or self.last_universe_update_date != current_date:
                 self.logger.info(f"🔄 每日列表更新 (UTC {current_date}): 重新计算 Top 200 成交量排名...")
                 
                 # Calculate Volume for all tickers
                 all_volumes = []
                 for t in tickers:
                     symbol = t[0]
                     vol = float(t[1].get('quoteVolume', 0))
                     all_volumes.append((symbol, vol))
                 
                 all_volumes.sort(key=lambda x: x[1], reverse=True)
                 self.coin_volume_ranking = {sym: rank+1 for rank, (sym, _) in enumerate(all_volumes)}
                 
                 self.last_universe_update_date = current_date
                 self.logger.info(f"✅ 列表更新完成: {len(self.coin_volume_ranking)} 个币种已排名")
            else:
                 # Use Cached Ranking
                 pass
                 # self.logger.debug("使用今日已缓存的成交量排名 (与回测一致)")
            
            # 3. Filter Candidates (Must be in Top 200 Universe using FROZEN ranking)
            # Filter by Rank first
            universe_candidates = [t for t in tickers if self.coin_volume_ranking.get(t[0], 999) <= self.TOP_N_COINS]
            
            # Then Filter by Change % (Top Gainers Logic)
            gainer_candidates = [t for t in universe_candidates if self.config.CHANGE_THRESHOLD_MIN <= float(t[1].get('percentage', 0)) <= self.config.CHANGE_THRESHOLD_MAX]
            
            # Sort by Change % Descending
            gainer_candidates.sort(key=lambda x: float(x[1].get('percentage', 0)), reverse=True)
            
            # Cache for logging (Top 50)
            self.top_gainers_data = gainer_candidates[:50]
            
            new_symbols = set()
            
            # Limit to checking top N candidates (aligned with Backtest)
            # Match Backtest limit (Top 50)
            check_limit = self.config.TOP_GAINER_COUNT
            for t in gainer_candidates[:check_limit]:
                symbol = t[0]
                
                # Rank Check
                rank = self.coin_volume_ranking.get(symbol, 999)
                if rank > self.TOP_N_COINS:
                    # self.logger.debug(f"Skipping {symbol}: Rank {rank} > {self.TOP_N_COINS}")
                    continue
                    
                # Quality Check (Needs History)
                try:
                    # Fetch enough data for EMA96 (24h) and Volume MA
                    df = self.client.get_historical_klines(symbol, timeframe=self.config.TIMEFRAME, limit=120)
                    if df.empty: continue
                    
                    # STRICT ALIGNMENT: Drop Developing Candle
                    # Binance API returns the current (incomplete) candle as the last row.
                    # Backtest uses [row_loc - 96 : row_loc], which excludes the current developing candle.
                    # We must drop the last row to match.
                    df = df.iloc[:-1]
                    
                    if df.empty: continue
                    
                    # Calculate 24h Volume
                    # Approximate by summing last 96 candles (15m * 96 = 24h)
                    volume_24h_slice = df.iloc[-96:]
                    volume_24h_usd = (volume_24h_slice['close'] * volume_24h_slice['volume']).sum()
                    
                    is_good, reason = self.quality_filter.check_quality(symbol, volume_24h_slice, volume_24h_usd)
                    
                    if is_good:
                        new_symbols.add(symbol)
                    else:
                        pass
                        # self.logger.debug(f"Skipping {symbol}: {reason}")
                        
                except Exception as e:
                    self.logger.error(f"Error checking quality for {symbol}: {e}")
            
            # Update Active Symbols
            with self.lock:
                # Add new symbols
                for s in new_symbols:
                    if s not in self.active_symbols:
                        self.active_symbols.add(s)
                        self.monitor.subscribe(s) # Subscribe to BookTicker (Price)
                        # ALIGNMENT FIX: Always subscribe to 1m execution stream
                        # We need 1m events to drive the "Developing Candle" strategy (15m logic updated every 1m)
                        self.monitor.subscribe_kline(s, '1m') 
                        self.logger.info(f"新增监控: {s} (Price + Kline 1m)")
                
                # Remove old symbols (if not in position)
                # Keep symbols if we have a position or if they are still in top gainers
                to_remove = []
                for s in self.active_symbols:
                    if s not in new_symbols and s not in self.positions and s not in self.paper_positions:
                        to_remove.append(s)
                        
                for s in to_remove:
                    self.active_symbols.remove(s)
                    self.monitor.unsubscribe(s) # Unsubscribe from BookTicker
                    self.monitor.unsubscribe_kline(s, '1m') # Unsubscribe from Kline 1m
                    self.logger.info(f"移除监控: {s}")
                
            # Record Universe for Backtest Alignment
            try:
                self.universe_recorder.record_universe(self.active_symbols)
            except Exception as e:
                self.logger.error(f"记录监控列表失败: {e}")
                    
            self.logger.info(f"当前监控列表 ({len(self.active_symbols)}): {list(self.active_symbols)}")
            
        except Exception as e:
            self.logger.error(f"扫描涨幅榜失败: {e}")

    def on_ticker_update(self, data):
        # Handle ticker updates if needed (e.g. for real-time top gainer check)
        pass

    def on_kline_update(self, data):
        """
        Callback for K-line updates from WebSocket.
        Trigger strategy ONLY on candle close.
        """
        try:
            # Parse data
            # Format: 's': symbol, 'k': { 'x': is_closed, ... }
            symbol_ws = data['s'].lower()
            kline = data['k']
            is_closed = kline['x']
            
            # Find internal symbol mapping
            # (Simple reverse lookup optimization for now)
            symbol_internal = None
            with self.lock:
                for s in self.active_symbols:
                    # Fix Symbol Matching (CCXT vs Binance WS)
                    # CCXT: BEAT/USDT:USDT -> beatusdt
                    # WS: beatusdt
                    normalized_s = s.split(':')[0].replace('/', '').lower()
                    
                    if normalized_s == symbol_ws:
                        symbol_internal = s
                        break
            
            if not symbol_internal:
                return

            # CRITICAL LOGIC ALIGNMENT: 
            # Only trigger strategy when candle is CLOSED.
            # This matches Backtest logic exactly.
            if is_closed:
                # CRITICAL ALIGNMENT 2.0: Only trigger on 15m Boundaries
                # If TIMEFRAME is 15m, we only want to process when the 15m candle ACTUALLY closes.
                # The 1m stream sends 'closed' every minute.
                # A 15m candle closes when the 14th, 29th, 44th, 59th minute candle closes.
                
                trigger_strategy = True
                
                if self.config.TIMEFRAME == '15m':
                    # Parse Open Time of this 1m candle
                    try:
                        kline_open_time = kline['t'] # ms timestamp
                        # Convert to Minute index (UTC)
                        # We don't need full datetime, just (timestamp / 60000)
                        minutes_since_epoch = int(kline_open_time / 60000)
                        
                        # Logic: If this is the 12:14 candle, next min is 12:15 (a 15m boundary).
                        # So (current_min + 1) % 15 == 0
                        is_15m_boundary = (minutes_since_epoch + 1) % 15 == 0
                        
                        # AGGRESSIVE MODE: If enabled, we trigger on ANY 1m close.
                        # CONSERVATIVE MODE: Only trigger on 15m boundary.
                        if not self.config.ALLOW_DEVELOPING_SIGNALS:
                            if not is_15m_boundary:
                                trigger_strategy = False
                                # self.logger.debug(f"忽略非15m收盘: {symbol_internal} (TS: {kline_open_time})")
                        else:
                            # In aggressive mode, we might want to log that we are checking intra-bar
                            pass
                            
                    except Exception:
                        pass # Fallback to triggering if calc fails
                
                if trigger_strategy:
                    # Log the event for verification
                    event_type = "15m Kline Closed" if (self.config.TIMEFRAME=='15m' and not self.config.ALLOW_DEVELOPING_SIGNALS) else "1m Update (Aggressive)"
                    self.logger.info(f"[Event] {event_type} for {symbol_internal}. Triggering Strategy...")
                    
                    # Fetch fresh history (SAFE)
                    self.process_strategy_safe(symbol_internal)
                
        except Exception as e:
            self.logger.error(f"K-line callback error: {e}")

    def process_strategy(self, symbol, df_ignored):
        # 1. Check Circuit Breaker
        current_balance = float(self.client.get_balance())
        if not hasattr(self, 'peak_balance'): self.peak_balance = current_balance
        self.peak_balance = max(self.peak_balance, current_balance)
        
        should_pause = self.trend_detector.should_pause_trading(current_balance, self.peak_balance)
        is_paper_trade = should_pause

        # Check for Entry - Early Exit
        with self.lock:
            if is_paper_trade:
                if symbol in self.paper_positions: return 
            else:
                if symbol in self.positions: return

        # === DATA FETCHING & RESAMPLING ===
        signal = None
        strategy_df = None
        
        try:
            # Needs enough data for 50x 15m candles
            # FIX: 1000 lines of 1m data = 66x 15m candles. Too short for EMA200 or complex indicators.
            # Increased to 4500 (3 days = 4320 mins) -> ~300x 15m candles.
            limit = 4500 if self.config.TIMEFRAME != '1m' else 210
            df_1m = self.client.get_historical_klines(symbol, timeframe='1m', limit=limit)
            
            if df_1m.empty: return

            # FIX: Ensure DatetimeIndex for Resampling
            if 'timestamp' in df_1m.columns:
                df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'])
                df_1m.set_index('timestamp', inplace=True)

            # MODE A: 15m Resampling (Developing Candle Logic)
            if self.config.TIMEFRAME == '15m':
                agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
                strategy_df = df_1m.resample('15min').agg(agg_dict).dropna()
                
                # STRICT ALIGNMENT: Drop Developing Candle if present (UNLESS Aggressive Mode is ON)
                # If the last row of strategy_df is the current (just started) 15m candle, it only has 1m of data.
                # We must trade on the PREVIOUS (Fully Closed) candle.
                # Example: At 14:00:05, we fetch data. df_1m has 14:00 row. Resample creates 14:00 bucket.
                # We want 13:45 bucket.
                if not strategy_df.empty:
                    last_ts = strategy_df.index[-1]
                    # Check if this candle is "in the future" relative to full closure
                    # Simple heuristic: If last_ts is within 14 mins of now, it's developing.
                    if last_ts > (datetime.now() - timedelta(minutes=15)):
                        # If Aggressive Mode is ON, we KEEP the developing candle (simulating intra-bar signal)
                        if not self.config.ALLOW_DEVELOPING_SIGNALS:
                             strategy_df = strategy_df.iloc[:-1]
                        else:
                             pass # Keep it! Trade on current state.

            # MODE B: Raw 1m
            else:
                strategy_df = df_1m
                
            if len(strategy_df) < self.config.LOOKBACK_WINDOW: return
            
            signal = self.strategy.check_signal(symbol, strategy_df)
            
        except Exception as e:
            self.logger.error(f"Strategy processing failed for {symbol}: {e}")
            return

        # === EXECUTION LOGIC ===
        if signal:
            if signal.get('status') == 'REJECTED':
                self.logger.info(f"[Refuse] 信号拒绝: {symbol} | {signal['reason']}")
            elif signal.get('side') == 'LONG':
                self.logger.info(f"[Accept] 信号检测: {symbol} 满足条件")
                
                # Check Max Positions (Real only)
                if not is_paper_trade:
                    if len(self.positions) >= self.config.MAX_OPEN_POSITIONS:
                        self.logger.info(f"跳过信号 {symbol}: 已有持仓 (上限 {self.config.MAX_OPEN_POSITIONS})")
                        return
                
                self.logger.info(f"发现信号: {symbol} 做多 (虚拟交易: {is_paper_trade})")
                self.execute_entry(symbol, strategy_df, signal=signal, is_paper_trade=is_paper_trade)
    
    # Check for Exit (Trailing Stop handled in manage_positions or here?)
    # Better here with real-time price, but we need current price.
    # df.iloc[-1]['close'] is the close of the JUST closed candle.
    # For trailing stop, we might want real-time price from ticker.
    pass

    def execute_entry(self, symbol, df, signal=None, is_paper_trade=False):
        """执行开仓 (已集成信号置信度动态杠杆)"""
        mode_str = "虚拟交易" if is_paper_trade else "实盘交易"
        self.logger.info(f"[开仓流程] 开始执行 {symbol} 开仓 ({mode_str})...")
        
        try:
            price = df['close'].iloc[-1]
            self.logger.info(f"[开仓流程] {symbol} 入场价格: {price}")
            
            balance = float(self.client.get_balance())
            self.logger.info(f"[开仓流程] 账户余额: {balance} USDT")
            
            # PAPER TRADING EXECUTION
            if is_paper_trade:
                # For paper trade, use real balance to simulate realistic size
                # Calculate Stop Loss (ATR-based)
                if len(df) >= 14:
                    import pandas_ta as ta
                    atr = ta.atr(df['high'], df['low'], df['close'], length=14).iloc[-1]
                    sl_distance = atr * 2.5
                    stop_loss_price = price - sl_distance
                else:
                    # Fallback to fixed 1.4% for safety
                    stop_loss_price = price * (1 - 0.014)

                # For paper trade, use a fixed leverage for size calculation
                paper_leverage = self.config.LEVERAGE # Or a default like 20x
                quantity = self.risk_manager.calculate_position_size(balance, price, stop_loss_price, leverage=paper_leverage)
                
                if quantity <= 0:
                    self.logger.warning(f"计算仓位为0，跳过虚拟开仓")
                    return

                position_data = {
                    'symbol': symbol,
                    'entry_price': price,
                    'quantity': quantity,
                    'stop_loss': stop_loss_price,
                    'highest_price': price,
                    'entry_time': datetime.now(),
                    'is_paper': True,
                    'side': 'BUY'
                }
                self.paper_positions[symbol] = position_data
                self.logger.info(f"📝 [虚拟交易] 开仓成功: {symbol} @ {price}")
                return

            # 1. Set Margin Mode to ISOLATED (Safety First)
            self.executor.set_margin_mode(symbol, 'ISOLATED')
            
            # 2. DYNAMIC LEVERAGE (Tier-based - Aligned with Backtest)
            # Calculate leverage FIRST so we can use it for stop loss cap
            coin_rank = self.coin_volume_ranking.get(symbol, 999)
            
            if coin_rank <= 50:
                target_leverage = 50  # Top 50 coins
            elif coin_rank <= 200:
                target_leverage = 20  # Mid-tier coins
            else:
                target_leverage = 10  # Fallback
            
            # Check Max Leverage supported by Binance
            max_leverage = self.client.get_max_leverage(symbol)
            if max_leverage is None:
                max_leverage = 20 # Fallback safety
                
            leverage = min(target_leverage, max_leverage)
            
            if leverage < target_leverage:
                self.logger.info(f"⚠️ {symbol} 杠杆被限制: 目标 {target_leverage}x -> 实际 {leverage}x (最大支持)")

            # CRITICAL FIX: Explicitly set leverage on exchange
            try:
                self.executor.set_leverage(symbol, leverage)
            except Exception as e:
                self.logger.error(f"❌ 设置杠杆失败 {symbol} {leverage}x: {e}")
            
            # Log the final leverage used
            if coin_rank <= 50:
                self.logger.info(f"[开仓流程] {symbol} 使用 {leverage}x 杠杆 (Top 50 主流币, 排名: {coin_rank})")
            elif coin_rank <= 200:
                self.logger.info(f"[开仓流程] {symbol} 使用 {leverage}x 杠杆 (Top 51-200 中型币, 排名: {coin_rank})")
            else:
                self.logger.info(f"[开仓流程] {symbol} 使用 {leverage}x 杠杆 (非Top200币种, 排名: {coin_rank})")
            
            # 3. Calculate Stop Loss with leverage-based cap
            # Use ATR for dynamic stop, but cap it at 1.4% (same as backtest)
            if len(df) >= 14:
                import pandas_ta as ta
                atr = ta.atr(df['high'], df['low'], df['close'], length=14).iloc[-1]
                sl_distance = atr * 2.5
                
                # CRITICAL: Cap stop loss at 1.4% to match backtest (all leverages)
                # For 50x leverage: liquidation at ~1.5%, so 1.4% is safe
                # For 20x/10x leverage: 1.4% is conservative but aligns with backtest
                max_stop_distance = price * 0.014
                sl_distance = min(sl_distance, max_stop_distance)
                stop_loss_price = price - sl_distance
                self.logger.info(f"[开仓流程] 动态止损: ATR={atr:.6f}, SL距离={sl_distance:.6f}, 上限=1.4%")
            else:
                # Fallback to fixed 1.4% for safety
                stop_loss_price = price * (1 - 0.014)
                self.logger.info(f"[开仓流程] 固定止损: 1.4%")
            
            # 4. Calculate Quantity using Risk Manager (pass leverage)
            quantity = self.risk_manager.calculate_position_size(balance, price, stop_loss_price, leverage=leverage)
            
            if quantity <= 0:
                self.logger.warning(f"计算仓位为0，跳过开仓")
                return
            

            # 5. Record Position (Optimistic, will verify SL next)
            position_data = {
                'symbol': symbol,
                'entry_price': price,
                'quantity': quantity,
                'stop_loss': stop_loss_price,
                'highest_price': price,
                'entry_time': datetime.now(),
                'leverage': leverage,
                'is_paper': False,
                'side': 'BUY'
            }
            self.positions[symbol] = position_data
            
            # 6. Place Order (Primary)
            order = self.executor.place_order(symbol, 'BUY', quantity, 'MARKET')
            # Update precise entry price if possible
            if order and 'average' in order and order['average']:
                self.positions[symbol]['entry_price'] = float(order['average'])
            
            self.logger.info(f"✅ [实盘交易] 开仓成功: {symbol} @ {price} (订单: {order['id']})")
            
            # 7. Place Stop Loss (Secondary - Fail Safe)
            try:
                self.executor.place_stop_loss(symbol, 'BUY', quantity, stop_loss_price)
                self.logger.info(f"🛡️ 止损单设置成功: {symbol} @ {stop_loss_price}")
            except Exception as sl_error:
                self.logger.error(f"⚠️ 止损单设置失败 {symbol}: {sl_error} (请手动设置!)")
                # We do NOT remove the position, we keep it managed so we can retry or close it
                
        except Exception as e:
            # If Primary Order failed, we can safely assume no position
            self.logger.error(f"开仓失败 {symbol}: {e}")
            # Clean up if we recorded it prematurely (unlikely with this flow, but safe)
            if symbol in self.positions:
                del self.positions[symbol]

    def manage_positions(self):
        """
        Manage open positions (Real and Paper).
        """
        # LOCKING: Protect access to positions
        with self.lock:
            # 1. Manage Real Positions
            for symbol in list(self.positions.keys()):
                try:
                    self.manage_single_position(symbol, is_paper=False)
                except Exception as e:
                    self.logger.error(f"管理实盘仓位 {symbol} 出错: {e}")
                    
            # 2. Manage Paper Positions
            for symbol in list(self.paper_positions.keys()):
                try:
                    self.manage_single_position(symbol, is_paper=True)
                except Exception as e:
                    self.logger.error(f"管理虚拟仓位 {symbol} 出错: {e}")

    def manage_single_position(self, symbol, is_paper=False):
        if is_paper:
            pos = self.paper_positions[symbol]
        else:
            pos = self.positions[symbol]
            
        # Get current price
        # Optimization: Use Local WS Cache for Speed!
        current_price = self.monitor.get_price(symbol)
        
        if current_price is None:
            # Fallback to REST API if WS not ready
            try:
                ticker = self.client.get_ticker(symbol)
                current_price = float(ticker['last'])
            except Exception as e:
                self.logger.error(f"获取价格失败 {symbol}: {e}")
                return
        
        # Check Exit Conditions
        
        # 1. Hard Stop Loss (Safety Net)
        # For real Positions: We rely on the Algo Order (Conditional Order) on Binance.
        # We DO NOT close via code to avoid race conditions or double closing.
        # For Paper Positions: We must close via code.
        if is_paper and current_price <= pos['stop_loss']:
            pnl = (pos['stop_loss'] - pos['entry_price']) * pos['quantity']
            reason = "Stop Loss (Paper)"
            self.close_position(symbol, pos['stop_loss'], reason, is_paper)
            return
        elif not is_paper and current_price <= pos['stop_loss']:
             # Polling Fix for UserDataStream absence
             now_ts = time.time()
             # Throttle check to every 3 seconds to avoid API spam
             if now_ts - pos.get('last_sl_check', 0) > 3:
                 pos['last_sl_check'] = now_ts
                 self.logger.warning(f"🛡️ [监控中] {symbol} 触发止损价 {pos['stop_loss']}! 检查线上状态...")
                 
                 try:
                     # 1. Check if Algo Order Exists
                     open_algos = self.executor.fetch_open_algo_orders(symbol)
                     has_sl = False
                     if open_algos:
                         expected_side = 'SELL' # Hardcoded for Longs as we only do Longs
                         for o in open_algos:
                             if o.get('side', '').upper() == expected_side:
                                 has_sl = True
                                 break
                     
                     if not has_sl:
                         # SL Order Gone -> Check Position (Did it fill?)
                         params = {'type': 'future'} # optimize fetch
                         # Note: fetch_positions usually returns all
                         all_pos = self.client.exchange.fetch_positions(params=params)
                         
                         contracts = 0
                         found_on_chain = False
                         for p in all_pos:
                             # Symbol matching (ccxt standardizes to 'BASE/QUOTE:SETTLE')
                             if p['symbol'] == symbol:
                                 contracts = float(p['contracts'])
                                 found_on_chain = True
                                 break
                         
                         if found_on_chain and contracts == 0:
                             self.logger.info(f"✅ 线上仓位已关闭 (Algo Triggered). 同步本地状态.")
                             exit_price = pos['stop_loss']
                             pnl = (exit_price - pos['entry_price']) * pos['quantity']
                             self.trade_logger.info(f"同步平仓: {symbol} | 价格: {exit_price} | PnL: {pnl} | 原因: Stop Loss (Algo Verified)")
                             self.trend_detector.add_trade_result(symbol, pnl, datetime.now())
                             self.recorder.log_trade({
                                 'symbol': symbol,
                                 'entry_price': pos['entry_price'],
                                 'exit_price': exit_price,
                                 'quantity': pos['quantity'],
                                 'pnl': pnl,
                                 'reason': "Stop Loss (Algo Verified)",
                                 'entry_time': pos['entry_time'],
                                 'exit_time': datetime.now(),
                                 'leverage': pos.get('leverage', 1)
                             })
                             del self.positions[symbol]
                             return
                         elif found_on_chain and contracts > 0:
                             self.logger.warning(f"⚠️ Algo SL 消失但仓位仍存在! 强制平仓.")
                             self.close_position(symbol, current_price, "Stop Loss (Force)", is_paper)
                             return
                         elif not found_on_chain:
                             # Weird case, maybe symbol format mismatch? Assume closed or error.
                             # If we can't find it, safer to keep local open or force check?
                             # Let's assume closed if we can't find it in "Active Positions" usually
                             # checking 'contracts' > 0 covers the active list assumption.
                             # If fetch_positions returns ALL symbols (including 0 pos), then not found is weird.
                             pass
                     else:
                         self.logger.info("ℹ️ Algo SL 挂单正常，等待成交...")
                 except Exception as check_e:
                     self.logger.error(f"检查线上状态失败: {check_e}")
        else:
             # Transient Debug
             if not is_paper and symbol == 'LUNA2/USDT:USDT':
                  self.logger.info(f"🛡️ [监控中] {symbol} 现价: {current_price} > 止损价: {pos['stop_loss']} (差距: {(current_price - pos['stop_loss'])/current_price*100:.2f}%)")

        # 2. Smart Exit (Dynamic Trailing / Break-even / Time Stop)
        # Using the same logic as backtest
        should_exit, exit_reason, exit_price = self.smart_exit.check_exit(
            position=pos,
            current_price=current_price,
            current_time=datetime.now()
            # current_atr=None # We don't have ATR here yet, optional
        )
        
        # 2.1 On-Chain Trailing Stop Update (Safety Feature)
        # USER REQUEST: Use Code Logic Soft TP to match backtest.
        # So we DISABLE the automatic hard SL update. The Hard SL remains fixed as a safety net.
        # The Code Logic (smart_exit) will handle trailing take profit via Market Sell.
        """
        if not is_paper:
            try:
                theoretical_stop = self.smart_exit.get_current_trailing_stop(pos)
                if theoretical_stop:
                    current_hard_stop = pos.get('stop_loss', 0)
                    # Filter: Only update if improvement is significant (> 0.5%) to avoid spamming orders
                    if theoretical_stop > current_hard_stop * 1.005:
                        self.logger.info(f"🔄 移动止损触发 {symbol}: {current_hard_stop:.4f} -> {theoretical_stop:.4f}")
                        
                        # 1. Cancel Old SL
                        self.executor.cancel_all_orders(symbol)
                        
                        # 2. Place New SL (Stop Limit)
                        # For Longs, SL is SELL.
                        self.executor.place_stop_loss(symbol, 'SELL', pos['quantity'], theoretical_stop)
                        
                        # 3. Update State
                        pos['stop_loss'] = theoretical_stop
                        
            except Exception as e:
                self.logger.error(f"⚠️ 更新移动止损失败 {symbol}: {e}")
        """

        if should_exit:
            # Use current_price for execution if exit_price is not specified or different
            # check_exit returns the trigger price, but we execute at market (current_price)
            self.close_position(symbol, current_price, exit_reason, is_paper)
            return

    def close_position(self, symbol, price, reason, is_paper=False):
        if is_paper:
            if symbol in self.paper_positions:
                pos = self.paper_positions[symbol]
                pnl = (price - pos['entry_price']) * pos['quantity']
                del self.paper_positions[symbol]
                self.logger.info(f"📝 [虚拟交易] 平仓 {symbol} @ {price} | PnL: ${pnl:.2f} | 原因: {reason}")
                
                # Feed result to detector
                self.trend_detector.add_trade_result(symbol, pnl, datetime.now())
                
                # Check recovery
                if self.trend_detector.check_recovery():
                    self.logger.info("✅ 虚拟交易表现良好，准备恢复实盘交易")
                
        else:
            if symbol in self.positions:
                pos = self.positions[symbol]
                quantity = pos['quantity']
                
                self.logger.info(f"正在平仓 {symbol} ({reason})...")
                
                # Keep the exchange stop in place until the market close has succeeded.
                order = self.executor.place_order(
                    symbol,
                    'SELL',
                    quantity,
                    'MARKET',
                    params={'reduceOnly': True}
                )

                exit_price = price
                if order and 'average' in order and order['average']:
                    exit_price = float(order['average'])
                
                # Position is closed; now remove any residual stop/algo orders.
                self.executor.cancel_all_orders(symbol)
                
                pnl = (exit_price - pos['entry_price']) * quantity
                self.logger.info(f"✅ [实盘交易] 平仓完成 {symbol} @ {exit_price} | PnL: ${pnl:.2f}")
                self.trade_logger.info(f"平仓: {symbol} | 价格: {exit_price} | PnL: {pnl} | 原因: {reason}")
                
                del self.positions[symbol]
                
                # Feed result to detector (Real trades also count for stats)
                self.trend_detector.add_trade_result(symbol, pnl, datetime.now())
                
                # Log Trade
                self.recorder.log_trade({
                    'symbol': symbol,
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_price,
                    'quantity': quantity,
                    'pnl': pnl,
                    'reason': reason,
                    'entry_time': pos['entry_time'],
                    'exit_time': datetime.now(),
                    'leverage': pos.get('leverage', 1)
                })



if __name__ == "__main__":
    bot = TradingBot()
    bot.start()
