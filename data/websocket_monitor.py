import threading
import time
import logging
import json
import websocket
import ssl

class MarketMonitor:
    def __init__(self, callbacks=None, kline_callback=None):
        """
        Real-Time WebSocket Monitor for Binance Futures.
        
        Args:
            callbacks: Optional dict of callbacks (not used heavily in this architecture, 
                       as main loop polls get_price)
            kline_callback: Function to call on K-line update (symbol, kline_data)
        """
        self.callbacks = callbacks or {}
        self.kline_callback = kline_callback
        self.active_symbols = set() # Internal set of symbols we want to monitor
        self.active_kline_symbols = set() # Symbols subscribed to K-line
        self.ws = None
        self.wst = None # Thread for WS run_forever
        self.keep_running = False
        self.logger = logging.getLogger('market_monitor')
        
        # Cache: symbol -> price (float)
        self.price_cache = {}
        self.lock = threading.Lock()
        
        self.base_url = "wss://fstream.binance.com/ws"
        
        # Connection state
        self.connected = False
        self._reconnect_delay = 1

    def start(self):
        """Start the WebSocket Monitor thread"""
        if self.keep_running:
            return
            
        self.keep_running = True
        self.logger.info("启动 WebSocket 监控模块 (Real-Time)...")
        
        # Start the WebSocket thread
        self.wst = threading.Thread(target=self._run_websocket_loop)
        self.wst.daemon = True
        self.wst.start()

    def stop(self):
        """Stop the WebSocket Monitor"""
        self.keep_running = False
        if self.ws:
            self.ws.close()
        self.logger.info("WebSocket 监控模块已停止")

    def subscribe(self, symbol):
        """
        Subscribe to a symbol's bookTicker (Real-time).
        Symbol format expected: 'ETH/USDT:USDT' -> 'ethusdt'
        """
        ws_symbol = self._to_ws_symbol(symbol)
        if not ws_symbol:
            return

        with self.lock:
            if symbol in self.active_symbols:
                return # Already subscribed
            self.active_symbols.add(symbol)
        
        # specific subscription if connected
        if self.connected and self.ws:
            self._send_subscription([ws_symbol], stream_type='bookTicker', subscribe=True)

    def unsubscribe(self, symbol):
        """Unsubscribe from a symbol"""
        ws_symbol = self._to_ws_symbol(symbol)
        if not ws_symbol:
            return

        with self.lock:
            if symbol not in self.active_symbols:
                return
            self.active_symbols.remove(symbol)
            # Remove from cache to avoid stale data usage? 
            # Better keep it as fallback, but maybe clear it if we want to be strict.
            # self.price_cache.pop(symbol, None)

        if self.connected and self.ws:
            self._send_subscription([ws_symbol], stream_type='bookTicker', subscribe=False)

    def subscribe_kline(self, symbol, interval='1m'):
        """Subscribe to K-line stream for a symbol"""
        ws_symbol = self._to_ws_symbol(symbol)
        if not ws_symbol:
            return

        with self.lock:
            if symbol in self.active_kline_symbols:
                return
            self.active_kline_symbols.add(symbol)
        
        if self.connected and self.ws:
            self._send_subscription([ws_symbol], stream_type=f'kline_{interval}', subscribe=True)

    def unsubscribe_kline(self, symbol, interval='1m'):
        """Unsubscribe from K-line stream"""
        ws_symbol = self._to_ws_symbol(symbol)
        if not ws_symbol:
            return

        with self.lock:
            if symbol not in self.active_kline_symbols:
                return
            self.active_kline_symbols.remove(symbol)
        
        if self.connected and self.ws:
            self._send_subscription([ws_symbol], stream_type=f'kline_{interval}', subscribe=False)

    def get_price(self, symbol):
        """
        Get the latest cached price for a symbol.
        Returns None if no data available.
        """
        with self.lock:
            return self.price_cache.get(symbol)

    # --- Internal Methods ---

    def _to_ws_symbol(self, symbol):
        """Convert internal symbol (ETH/USDT:USDT) to WS symbol (ethusdt)"""
        try:
            # Handle 'ETH/USDT:USDT' or 'ETH/USDT'
            clean = symbol.split(':')[0].replace('/', '').lower()
            return clean
        except Exception:
            return None

    def _run_websocket_loop(self):
        """Main loop ensuring connection logic and reconnection"""
        while self.keep_running:
            try:
                # websocket.enableTrace(True)
                self.ws = websocket.WebSocketApp(
                    self.base_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                
                self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=30, ping_timeout=10)
            except Exception as e:
                self.logger.error(f"WebSocket 异常: {e}")
            
            if self.keep_running:
                self.logger.info(f"WebSocket 连接断开，{self._reconnect_delay}秒后重连...")
                time.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60) # Exponential backoff

    def _on_open(self, ws):
        self.logger.info("[OK] WebSocket 已连接")
        self.connected = True
        self._reconnect_delay = 1
        
        # Resubscribe to all active symbols
        with self.lock:
            book_subs = [self._to_ws_symbol(s) for s in self.active_symbols]
            kline_subs = [self._to_ws_symbol(s) for s in self.active_kline_symbols]
        
        if book_subs:
            self._send_subscription(book_subs, stream_type='bookTicker', subscribe=True)
            
        if kline_subs:
            self._send_subscription(kline_subs, stream_type='kline_1m', subscribe=True)

    def _on_close(self, ws, close_status_code, close_msg):
        self.logger.warning(f"WebSocket 连接关闭: {close_msg}")
        self.connected = False

    def _on_error(self, ws, error):
        self.logger.error(f"WebSocket 错误: {error}")

    def _on_message(self, ws, message):
        """
        Handle incoming messages.
        """
        try:
            data = json.loads(message)
            
            # Handle stream response (subscription confirmation)
            if 'result' in data and data['result'] is None:
                return 
                
            # Handle Payload
            if 'e' in data:
                event_type = data['e']
                
                # 1. Book Ticker (Price Update)
                if event_type == 'bookTicker':
                    symbol_ws = data['s'].lower()
                    bid = float(data['b'])
                    ask = float(data['a'])
                    mid_price = (bid + ask) / 2
                    self._update_cache(symbol_ws, mid_price)
                    
                # 2. Kline Update (Strategy Trigger)
                elif event_type == 'kline':
                    self._log_data_trace(data) # Trace Log
                    if self.kline_callback:
                        self.kline_callback(data)

        except Exception as e:
            self.logger.error(f"消息处理错误: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def _update_cache(self, ws_symbol, price):
        """Update cache efficiently"""
        with self.lock:
             # We need to update the entry for the Internal Symbol corresponding to ws_symbol
             # Let's build a reverse map on the fly or maintain it.
             # Simple approach: active_symbols is ['ETH/USDT:USDT', ...]
             for sym in self.active_symbols:
                 if self._to_ws_symbol(sym) == ws_symbol:
                     self.price_cache[sym] = price
                     break

    def _send_subscription(self, ws_symbols, stream_type='bookTicker', subscribe=True):
        if not ws_symbols:
            return
            
        method = "SUBSCRIBE" if subscribe else "UNSUBSCRIBE"
        # CLEANUP: Filter Nones
        ws_symbols = [s for s in ws_symbols if s]
        if not ws_symbols: 
            return

        # Params: ["btcusdt@bookTicker", "ethusdt@kline_1m"]
        params = [f"{s}@{stream_type}" for s in ws_symbols]
        
        payload = {
            "method": method,
            "params": params,
            "id": int(time.time() * 1000)
        }
        
        try:
            self.ws.send(json.dumps(payload))
            self.logger.info(f"WebSocket {method}: {len(params)} streams ({stream_type})")
            
            # Traceability Log
            action_str = "START SUBSCRIPTION" if subscribe else "STOP SUBSCRIPTION"
            self._log_trace(ws_symbols, action_str, stream_type)
            
        except Exception as e:
            self.logger.error(f"WebSocket 发送订阅失败: {e}")

    # --- Traceability ---
    def _log_trace(self, ws_symbols, action, stream_type):
        """
        Log Start/Stop Subscription events to symbol-specific trace logs.
        """
        import os
        from datetime import datetime
        
        trace_dir = "logs/ws_trace"
        if not os.path.exists(trace_dir):
            os.makedirs(trace_dir, exist_ok=True)
            
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str = datetime.now().strftime("%Y-%m-%d")
        
        for ws_sym in ws_symbols:
            # Find internal symbol purely for filename friendliness (optional)
            # Actually just use ws_symbol is fine
            file_path = f"{trace_dir}/{ws_sym}_{date_str}.log"
            
            try:
                with open(file_path, "a", encoding="utf-8") as f:
                    msg = f"[{current_time_str}] {action} {stream_type.upper()}\n"
                    f.write(msg)
            except Exception:
                pass

    def _log_data_trace(self, data):
        """
        Log raw WebSocket data (Klines) to trace file.
        """
        import os
        from datetime import datetime
        
        if 'e' not in data or data['e'] != 'kline':
            return
            
        k = data['k']
        
        # OPTIMIZATION: Only log CLOSED candles (x=True)
        # This reduces log volume by ~98% and captures the exact data point used for strategy triggers.
        # User request: "1s logs are unnecessary"
        if not k['x']:
            return
            
        stream_type = 'kline'
        ws_symbol = data['s'].lower()
        
        trace_dir = "logs/ws_trace"
        if not os.path.exists(trace_dir):
            os.makedirs(trace_dir, exist_ok=True)
            
        date_str = datetime.now().strftime("%Y-%m-%d")
        file_path = f"{trace_dir}/{ws_symbol}_{date_str}.log"
        
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                # Format: [Time] [KLINE] Open: ... Close: ... Closed: ...
                is_closed = "CLOSED"
                msg = f"[{current_time_str}] [DATA] {is_closed} | T: {k['t']} | O: {k['o']} | C: {k['c']} | V: {k['v']}\n"
                f.write(msg)
        except Exception:
            pass
