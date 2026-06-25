import time
import logging
import ccxt
import hmac
import hashlib
import urllib.parse
import json
import requests
from data.binance_client import BinanceClient
from config.settings import Config

class Executor(BinanceClient):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.logger = logging.getLogger('trading_bot')

    def place_order(self, symbol, side, quantity, order_type='MARKET', price=None, params=None):
        """
        Place an order on Binance Futures.
        """
        if params is None:
            params = {}
            
        self.logger.info(f"正在提交 {side} {order_type} 订单: {quantity} {symbol}...")
        
        # Let exception propagate to caller
        order = self.exchange.create_order(
            symbol=symbol,
            type=order_type,
            side=side,
            amount=quantity,
            price=price,
            params=params
        )
        self.logger.info(f"订单已提交: {order['id']}")
        return order

    def set_leverage(self, symbol, leverage):
        # Let exception propagate
        self.exchange.set_leverage(leverage, symbol)
        self.logger.info(f"{symbol} 杠杆设置为 {leverage}x")

    def set_margin_mode(self, symbol, margin_mode='ISOLATED'):
        try:
            self.exchange.set_margin_mode(margin_mode, symbol)
            self.logger.info(f"{symbol} 保证金模式设置为 {margin_mode}")
        except Exception as e:
            if "No need to change" in str(e):
                self.logger.info(f"{symbol} 保证金模式已经是 {margin_mode}")
            else:
                self.logger.warning(f"设置保证金模式失败 {symbol}: {e}")




    def place_stop_loss(self, symbol, side, quantity, stop_price):
        """
        Place a Stop Loss using the Algo Order Endpoint (Primary Strategy).
        We bypass the standard endpoint which often returns -4120.
        Fallback: Soft Stop (handled by caller if this returns None).
        """
        sl_side = 'sell' if side.lower() == 'buy' else 'buy'
        
        # Directly use Algo Order (The "Power Mode")
        # Standard Order failed with -4120, so we MUST use this.
        self.logger.info(f"[Shield] 设置强力链上止损 (Algo Endpoint): 触发价 {stop_price} (侧: {sl_side})")
        return self.place_algo_order(symbol, sl_side, quantity, stop_price)

    def fetch_open_algo_orders(self, symbol=None):
        """
        Fetch open Algo Orders (Conditional Orders) manually.
        CCXT fetch_open_orders does NOT cover these.
        """
        try:
            params = {
                'timestamp': self.exchange.milliseconds(),
                'recvWindow': 60000
            }
            if symbol:
                market = self.exchange.market(symbol)
                params['symbol'] = market['id']
                
            query_string = urllib.parse.urlencode(params)
            signature = hmac.new(
                self.exchange.secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            full_url = f"https://fapi.binance.com/fapi/v1/openAlgoOrders?{query_string}&signature={signature}"
            headers = {'X-MBX-APIKEY': self.exchange.apiKey}
            
            response = requests.get(full_url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                return data.get('orders', [])
            else:
                self.logger.error(f"[X] 获取 Algo Orders 失败: {response.text}")
                return []
        except Exception as e:
            self.logger.error(f"[X] 获取 Algo Orders 异常: {e}")
            return []

    def place_algo_order(self, symbol, side, quantity, stop_price):
        """
        Manually construct a signed request to /fapi/v1/algoOrder to bypass CCXT/API limitations.
        """
        try:
            # 1. Prepare Params (Standard)
            market = self.exchange.market(symbol)
            symbol_raw = market['id']
            
            # 1. Prepare Parameters (PRECISION FIX)
            qty_str = self.exchange.amount_to_precision(symbol, quantity)
            stop_price_str = self.exchange.price_to_precision(symbol, stop_price)
            
            params = {
                'symbol': symbol_raw,
                'side': side.upper(),
                'quantity': qty_str,
                'reduceOnly': 'true',
                'type': 'STOP_MARKET',
                'stopPrice': stop_price_str,
                'triggerPrice': stop_price_str, # Mandatory for Algo Endpoint
                'workingType': 'CONTRACT_PRICE',
                'algoType': 'CONDITIONAL', # Mandatory for Algo Endpoint
                'closePosition': 'false', # We specify quantity, so closePosition is false
                'priceProtect': 'true',
                'timestamp': self.exchange.milliseconds(),
                'recvWindow': 60000
            }
            
            # 2. Generate Signature (Manual HMAC SHA256)
            # This bypasses all CCXT Testnet/Sandbox confusion by implementing the raw auth protocol.
            query_string = urllib.parse.urlencode(params)
            signature = hmac.new(
                self.exchange.secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # 3. Construct Request
            final_query = f"{query_string}&signature={signature}"
            full_url = "https://fapi.binance.com/fapi/v1/algoOrder?" + final_query
            
            headers = {
                'X-MBX-APIKEY': self.exchange.apiKey,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            # 4. Execute Request
            self.logger.info(f"[SEND] 发送 Algo Order (Manual Sign): {symbol} {side} {quantity}")
            
            # We use a fresh requests call to avoid any middleware interference
            response = requests.post(full_url, headers=headers)
            
            # 5. Handle Response
            if response.status_code == 200:
                data = response.json()
                self.logger.info(f"[OK] Algo Order 成功: ID {data.get('clientAlgoId', 'Unknown')}")
                return data
            else:
                self.logger.error(f"[X] Algo Order 失败 (HTTP {response.status_code}): {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"[X] Algo Order 异常: {e}")
            return None
    def cancel_all_orders(self, symbol):
        try:
            # 1. Cancel Standard Orders
            self.exchange.cancel_all_orders(symbol)
            
            # 2. Cancel Algo Orders (Manual)
            self.cancel_all_algo_orders(symbol)
            
            self.logger.info(f"已撤销 {symbol} 所有挂单 (Standard + Algo)")
        except Exception as e:
            self.logger.warning(f"撤单失败: {e}")

    def cancel_all_algo_orders(self, symbol):
        """
        Manually cancel all open Algo Orders for a symbol by fetching and cancelling individually.
        This provides better compatibility than the batch endpoint which returns 404 sometimes.
        """
        try:
            # 1. Fetch Open Algo Orders
            orders = self.fetch_open_algo_orders(symbol)
            if not orders:
                return

            self.logger.info(f"正在撤销 {len(orders)} 个 Algo 订单...")
            
            # 2. Cancel Each Order
            for o in orders:
                try:
                    params = {
                        'symbol': o['symbol'], # Use symbol from order or passed symbol
                        'algoId': o['algoId'],
                        'timestamp': self.exchange.milliseconds(),
                        'recvWindow': 60000
                    }
                    
                    query_string = urllib.parse.urlencode(params)
                    signature = hmac.new(
                        self.exchange.secret.encode('utf-8'),
                        query_string.encode('utf-8'),
                        hashlib.sha256
                    ).hexdigest()
                    
                    full_url = f"https://fapi.binance.com/fapi/v1/algoOrder?{query_string}&signature={signature}"
                    headers = {'X-MBX-APIKEY': self.exchange.apiKey}
                    
                    resp = requests.delete(full_url, headers=headers)
                    if resp.status_code == 200:
                        self.logger.info(f"[OK] 撤销 Algo Order {o['algoId']} 成功")
                    else:
                        # Handle -2011 Unknown order sent (Already cancelled/filled)
                        try:
                            err_data = resp.json()
                            if err_data.get('code') == -2011:
                                self.logger.info(f"[Info] 撤销 Algo Order {o['algoId']} 跳过 (已不存在/已成交)")
                            else:
                                self.logger.warning(f"[Warn] 撤销 Algo Order {o['algoId']} 失败: {resp.text}")
                        except:
                            self.logger.warning(f"[Warn] 撤销 Algo Order {o['algoId']} 失败: {resp.text}")
                except Exception as inner_e:
                    self.logger.error(f"撤销单个 Algo 订单异常: {inner_e}")
                    
        except Exception as e:
            self.logger.error(f"[X] 批量撤销 Algo 订单异常: {e}")
