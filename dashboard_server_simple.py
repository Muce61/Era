"""
Simple dashboard server that returns empty history for testing frontend
"""
from flask import Flask, render_template, jsonify, send_from_directory, send_file
from flask_cors import CORS
import pandas as pd
import os

app = Flask(__name__)
CORS(app)

CSV_PATH = 'logs/market_status.csv'

@app.route('/api/market-status')
def get_market_status():
    try:
        if not os.path.exists(CSV_PATH):
            return jsonify({'error': 'CSV file not found'}), 404
        
        df = pd.read_csv(CSV_PATH)
        data = df.to_dict('records')
        
        for row in data:
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
    return jsonify({
        'total_trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0,
        'max_profit': 0, 'min_profit': 0, 'avg_profit': 0,
        'max_loss': 0, 'min_loss': 0, 'avg_loss': 0
    })

@app.route('/api/account-balance')
def get_account_balance():
    from dotenv import load_dotenv
    import ccxt
    load_dotenv(override=True)
    
    try:
        exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_SECRET'),
            'options': {'defaultType': 'future'}
        })
        
        if os.getenv('BINANCE_TESTNET', 'false').lower() == 'true':
            exchange.set_sandbox_mode(True)
            
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
    return jsonify({'positions': [], 'count': 0})

@app.route('/api/position-history')
def get_position_history():
    return jsonify({'history': [], 'count': 0})

@app.route('/static/icons/<path:filename>')
def serve_icon(filename):
    return send_from_directory('static/icons', filename)

@app.route('/')
def index():
    return send_file('dashboard.html')

if __name__ == '__main__':
    print("Starting Simple Dashboard Server...")
    print("Open http://localhost:5001 in your browser")
    app.run(host='0.0.0.0', port=5001, debug=False)
