from flask import Flask, render_template, jsonify, send_from_directory, send_file
from flask_cors import CORS
import pandas as pd
import os
import time
import threading
import re
from datetime import datetime, timedelta
from pathlib import Path
import ccxt
from utils.icon_helper import get_icon_path

app = Flask(__name__)
CORS(app)

CSV_PATH = 'logs/market_status.csv'
TRADES_CSV_PATH = 'logs/trades/trades.csv'

# Initialize Binance client
def get_binance_client():
    """Initialize Binance client with API keys from .env"""
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_SECRET')
    use_testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
    
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'options': {
            'defaultType': 'future',
            'adjustForTimeDifference': True
        }
    })
    
    if use_testnet:
        exchange.set_sandbox_mode(True)
    
    return exchange

@app.route('/api/market-status')
def get_market_status():
    """Return market status data as JSON"""
    try:
        if not os.path.exists(CSV_PATH):
            return jsonify({'error': 'CSV file not found'}), 404
        
        df = pd.read_csv(CSV_PATH)
        data = df.to_dict('records')
        
        # Add icon URL for each row (local only)
        for row in data:
            # Simple local path check, no download
            symbol_base = row['币种'].split('/')[0].lower()
            if symbol_base.startswith('1000'):
                symbol_base = symbol_base[4:]
            row['icon'] = f"/static/icons/{symbol_base}.png"
            
        mod_time = os.path.getmtime(CSV_PATH)
        
        return jsonify({
            'data': data,
            'last_updated': mod_time,
            'count': len(data)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trading-stats')
def get_trading_stats():
    """Read trades.csv and return detailed trading statistics"""
    try:
        if not os.path.exists(TRADES_CSV_PATH):
            return jsonify({
                'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
                'max_profit': 0, 'min_profit': 0, 'avg_profit': 0,
                'max_loss': 0, 'min_loss': 0, 'avg_loss': 0
            })
        
        df = pd.read_csv(TRADES_CSV_PATH)
        if df.empty:
            return jsonify({
                'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
                'max_profit': 0, 'min_profit': 0, 'avg_profit': 0,
                'max_loss': 0, 'min_loss': 0, 'avg_loss': 0
            })
            
        # Calculate metrics
        total_trades = len(df)
        wins = len(df[df['pnl'] > 0])
        losses = len(df[df['pnl'] <= 0])
        win_rate = round(wins / total_trades * 100, 2) if total_trades > 0 else 0
        
        profits = df[df['pnl'] > 0]['roe'].tolist()
        losses_list = df[df['pnl'] <= 0]['roe'].tolist()
        
        stats = {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'max_profit': round(max(profits), 4) if profits else 0,
            'min_profit': round(min(profits), 4) if profits else 0,
            'avg_profit': round(sum(profits) / len(profits), 4) if profits else 0,
            'max_loss': round(min(losses_list), 4) if losses_list else 0,
            'min_loss': round(max(losses_list), 4) if losses_list else 0,
            'avg_loss': round(sum(losses_list) / len(losses_list), 4) if losses_list else 0,
        }
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/account-balance')
def get_account_balance():
    """Get current account balance from Binance"""
    try:
        exchange = get_binance_client()
        balance = exchange.fetch_balance()
        
        usdt_balance = balance['USDT']['free'] + balance['USDT']['used']
        
        return jsonify({
            'balance': round(usdt_balance, 2),
            'free': round(balance['USDT']['free'], 2),
            'used': round(balance['USDT']['used'], 2)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/current-positions')
def get_current_positions():
    """Get current open positions from Binance"""
    try:
        exchange = get_binance_client()
        positions = exchange.fetch_positions()
        
        # Filter for positions with non-zero size
        open_positions = []
        for position in positions:
            contracts = float(position.get('contracts', 0))
            if contracts != 0:
                open_positions.append({
                    'symbol': position['symbol'],
                    'side': 'long' if contracts > 0 else 'short',
                    'size': abs(contracts),
                    'entry_price': float(position.get('entryPrice', 0)),
                    'mark_price': float(position.get('markPrice', 0)),
                    'unrealized_pnl': float(position.get('unrealizedPnl', 0)),
                    'leverage': float(position.get('leverage', 1)),
                    'leverage': float(position.get('leverage', 1)),
                    'liquidation_price': float(position.get('liquidationPrice', 0)),
                    'icon': f"/static/icons/{position['symbol'].split('/')[0].lower().replace('1000','')}.png"
                })
        
        return jsonify({'positions': open_positions, 'count': len(open_positions)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Global cache for history
history_cache = []
last_history_update = 0

def background_history_scanner():
    """Background thread to scan all symbols for history"""
    global history_cache, last_history_update
    print("Starting background history scanner...")
    
    while True:
        try:
            exchange = get_binance_client()
            markets = exchange.load_markets()
            symbols = [s for s in markets if '/USDT:USDT' in s]
            
            all_trades = []
            since = int((datetime.now() - timedelta(days=180)).timestamp() * 1000)
            
            # 1. Smart Discovery via Income History (The "Magic" API)
            # This gets all symbols with PnL/Commission activity without iterating
            active_symbols = set()
            try:
                # Fetch recent income history (limit 1000 covers a lot of trades)
                income_history = exchange.fapiPrivateGetIncome({'limit': 1000})
                for item in income_history:
                    if item['symbol']:
                        # Convert symbol format (e.g. BTCUSDT -> BTC/USDT:USDT)
                        # We need to map it back to CCXT format.
                        # Easiest is to just store the raw symbol and let fetch_my_trades handle it?
                        # No, fetch_my_trades needs CCXT symbol.
                        # We can try to find it in markets.
                        raw_sym = item['symbol']
                        # Find matching market
                        for m_sym, m_data in markets.items():
                            if m_data['id'] == raw_sym:
                                active_symbols.add(m_sym)
                                break
            except Exception as e:
                print(f"Income fetch failed: {e}")

            # 2. Add symbols from logs as backup
            if os.path.exists(TRADE_LOG_PATH):
                with open(TRADE_LOG_PATH, 'r') as f:
                    content = f.read()
                    matches = re.findall(r'([A-Z0-9]+/[A-Z0-9]+:[A-Z0-9]+)', content)
                    active_symbols.update(matches)
            
            print(f"Found active symbols: {active_symbols}")

            # 3. Fetch trades for these symbols with 7-day chunking
            # Binance Futures restricts history to 90 days and requests to 7-day windows
            max_days = 90
            chunk_size_days = 7
            end_time = datetime.now()
            start_time_limit = end_time - timedelta(days=max_days)
            
            for symbol in active_symbols:
                try:
                    # Loop backwards from now in 7-day chunks
                    current_end = end_time
                    while current_end > start_time_limit:
                        current_start = current_end - timedelta(days=chunk_size_days)
                        if current_start < start_time_limit:
                            current_start = start_time_limit
                            
                        since_ts = int(current_start.timestamp() * 1000)
                        params = {'endTime': int(current_end.timestamp() * 1000)}
                        
                        try:
                            trades = exchange.fetch_my_trades(symbol, since=since_ts, limit=100, params=params)
                            if trades:
                                all_trades.extend(trades)
                                # Optimization: If we found trades, maybe we don't need to go back forever if we just want recent?
                                # But user wants "all". We continue.
                        except Exception as e:
                            # print(f"Error fetching chunk for {symbol}: {e}")
                            pass
                            
                        current_end = current_start
                        time.sleep(0.1) # Rate limit protection
                        
                except Exception as e:
                    print(f"Error processing {symbol}: {e}")
            
            # Update cache immediately
            if all_trades:
                # Deduplicate trades based on id
                unique_trades = {t['id']: t for t in all_trades}.values()
                
                temp_history = []
                for trade in unique_trades:
                    icon_path = get_icon_path(trade['symbol'])
                    
                    realized_pnl = 0
                    if 'info' in trade and 'realizedPnl' in trade['info']:
                        realized_pnl = float(trade['info']['realizedPnl'])
                    
                    temp_history.append({
                        'timestamp': trade['timestamp'],
                        'datetime': trade['datetime'],
                        'symbol': trade['symbol'],
                        'side': trade['side'],
                        'price': trade['price'],
                        'amount': trade['amount'],
                        'cost': trade['cost'],
                        'fee': trade.get('fee', {}).get('cost', 0),
                        'pnl': realized_pnl,
                        'icon': icon_path
                    })
                temp_history.sort(key=lambda x: x['timestamp'], reverse=True)
                history_cache = temp_history
                print(f"History scan complete. Found {len(history_cache)} trades.")

            # Sleep for 1 minute (faster updates since it's efficient now)
            time.sleep(60)
            # We'll scan 10 symbols every 10 seconds? No, that's too slow.
            # Just scan all but sleep a bit
            for symbol in symbols:
                if symbol in priority_symbols: continue
                try:
                    # Only fetch if we suspect activity? 
                    # Optimization: Check open orders first? No.
                    # Just fetch trades. Rate limit is weight 5.
                    trades = exchange.fetch_my_trades(symbol, since=since, limit=50)
                    if trades:
                        all_trades.extend(trades)
                        priority_symbols.add(symbol) # Add to priority for next time
                    time.sleep(0.1) # Be gentle
                except: pass
            
            # Process and sort
            processed_history = []
            for trade in all_trades:
                base_currency = trade['symbol'].split('/')[0].lower()
                if base_currency.startswith('1000'):
                    base_currency = base_currency[4:]
                
                # Use local icon if exists, else fallback to CDN
                icon_path = f"/static/icons/{base_currency}.png"
                
                realized_pnl = 0
                if 'info' in trade and 'realizedPnl' in trade['info']:
                    realized_pnl = float(trade['info']['realizedPnl'])
                
                processed_history.append({
                    'timestamp': trade['timestamp'],
                    'datetime': trade['datetime'],
                    'symbol': trade['symbol'],
                    'side': trade['side'],
                    'price': trade['price'],
                    'amount': trade['amount'],
                    'cost': trade['cost'],
                    'fee': trade.get('fee', {}).get('cost', 0),
                    'pnl': realized_pnl,
                    'icon': icon_path
                })
            
            processed_history.sort(key=lambda x: x['timestamp'], reverse=True)
            history_cache = processed_history
            last_history_update = time.time()
            print(f"History scan complete. Found {len(history_cache)} trades.")
            
            # Sleep for 5 minutes before next full scan
            time.sleep(300)
            
        except Exception as e:
            print(f"Scanner Error: {e}")
            time.sleep(60)

# Start scanner thread
# threading.Thread(target=background_history_scanner, daemon=True).start()

@app.route('/static/icons/<path:filename>')
def serve_icon(filename):
    return send_from_directory('static/icons', filename)

@app.route('/api/refresh-history', methods=['POST'])
def refresh_history():
    """Trigger the standalone script to fetch Binance history"""
    import subprocess
    try:
        # Run the script in the background
        result = subprocess.run(
            ['python3', '/Users/muce/PycharmProjects/github/eth/fetch_binance_history.py'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            return jsonify({
                'status': 'success',
                'message': 'History refreshed successfully',
                'output': result.stdout
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Script failed',
                'error': result.stderr
            }), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({
            'status': 'error',
            'message': 'Script timed out (>5 minutes)'
        }), 500
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/position-history')
def get_position_history():
    """Get position history from JSON file (generated by fetch_binance_history.py)"""
    import json
    
    history_path = 'logs/binance_history.json'
    
    try:
        if os.path.exists(history_path):
            with open(history_path, 'r') as f:
                data = json.load(f)
            return jsonify(data)
        else:
            # Fallback to empty if file doesn't exist yet
            return jsonify({
                'history': [],
                'count': 0,
                'message': 'No history file found. Click "Refresh History" to fetch data.'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    """Serve the dashboard HTML"""
    return send_file('dashboard.html')

if __name__ == '__main__':
    print("Starting Enhanced Market Status Dashboard Server...")
    print("Open http://localhost:5001 in your browser")
    app.run(host='0.0.0.0', port=5001, debug=False)
