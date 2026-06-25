#!/usr/bin/env python3
"""
Standalone script to fetch Binance Futures trading history and save to JSON
"""
import ccxt
import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time

def fetch_and_save_history():
    """Fetch trading history from Binance and save to JSON file"""
    print("=" * 60)
    print("Binance History Fetcher")
    print("=" * 60)
    
    # Load credentials
    load_dotenv(override=True)
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_SECRET')
    use_testnet = os.getenv('BINANCE_TESTNET', 'false').lower() == 'true'
    
    print(f"\n[1/4] Initializing Binance client (Testnet: {use_testnet})...")
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'options': {'defaultType': 'future'}
    })
    
    if use_testnet:
        exchange.set_sandbox_mode(True)
    
    # Step 1: Discover active symbols via Income History
    print("\n[2/4] Discovering active symbols (scanning 90 days of income history)...")
    end_time = datetime.now()
    start_time_limit = end_time - timedelta(days=90)
    start_ts = int(start_time_limit.timestamp() * 1000)
    current_end_ts = int(end_time.timestamp() * 1000)
    
    active_raw_symbols = set()
    page_count = 0
    
    try:
        while current_end_ts > start_ts and page_count < 100:
            params = {'endTime': current_end_ts, 'limit': 1000}
            income = exchange.fapiPrivateGetIncome(params)
            
            if not income:
                break
            
            min_ts = current_end_ts
            for item in income:
                if item.get('symbol'):
                    active_raw_symbols.add(item['symbol'])
                if 'time' in item:
                    try:
                        ts = int(item['time'])
                        if ts < min_ts:
                            min_ts = ts
                    except ValueError:
                        pass
            
            if min_ts == current_end_ts:
                current_end_ts -= 1000
            else:
                current_end_ts = min_ts - 1
            
            time.sleep(0.1)
            page_count += 1
            
    except Exception as e:
        print(f"   Warning: Income discovery error: {e}")
    
    print(f"   Found {len(active_raw_symbols)} symbols: {list(active_raw_symbols)[:10]}{'...' if len(active_raw_symbols) > 10 else ''}")
    
    # Step 2: Convert to CCXT format
    ccxt_symbols = set()
    for raw_sym in active_raw_symbols:
        if raw_sym.endswith('USDT'):
            base = raw_sym[:-4]
            ccxt_symbols.add(f"{base}/USDT:USDT")
        elif raw_sym.endswith('USDC'):
            base = raw_sym[:-4]
            ccxt_symbols.add(f"{base}/USDC:USDC")
    
    print(f"   Converted to {len(ccxt_symbols)} CCXT symbols")
    
    # Step 3: Fetch trades for all symbols
    print(f"\n[3/4] Fetching trades for {len(ccxt_symbols)} symbols...")
    all_trades = []
    
    for idx, symbol in enumerate(ccxt_symbols, 1):
        print(f"   [{idx}/{len(ccxt_symbols)}] Fetching {symbol}...", end=' ')
        try:
            current_end = end_time
            symbol_trades = 0
            
            while current_end > start_time_limit:
                current_start = current_end - timedelta(days=7)
                if current_start < start_time_limit:
                    current_start = start_time_limit
                
                since_ts = int(current_start.timestamp() * 1000)
                params = {'endTime': int(current_end.timestamp() * 1000)}
                
                try:
                    trades = exchange.fetch_my_trades(symbol, since=since_ts, limit=100, params=params)
                    if trades:
                        all_trades.extend(trades)
                        symbol_trades += len(trades)
                except:
                    break
                
                current_end = current_start
                time.sleep(0.1)
            
            print(f"{symbol_trades} trades")
        except Exception as e:
            print(f"Error: {e}")
    
    print(f"\n   Total: {len(all_trades)} trades")
    
    # Step 4: Save to JSON
    print("\n[4/4] Saving to logs/binance_history.json...")
    
    # Deduplicate
    unique_trades = {t['id']: t for t in all_trades}.values()
    
    # Format for frontend
    history = []
    for trade in unique_trades:
        realized_pnl = 0
        if 'info' in trade and 'realizedPnl' in trade['info']:
            realized_pnl = float(trade['info']['realizedPnl'])
        
        history.append({
            'time': datetime.fromtimestamp(trade['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
            'timestamp': trade['timestamp'],
            'datetime': trade['datetime'],
            'symbol': trade['symbol'],
            'side': trade['side'],
            'price': trade['price'],
            'amount': trade['amount'],
            'cost': trade['cost'],
            'fee': trade.get('fee', {}).get('cost', 0),
            'pnl': realized_pnl,
            'icon': f"/static/icons/{trade['symbol'].split('/')[0].lower().replace('1000','')}.png"
        })
    
    # Sort by time desc
    history.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # Save
    os.makedirs('logs', exist_ok=True)
    output_path = 'logs/binance_history.json'
    with open(output_path, 'w') as f:
        json.dump({
            'history': history,
            'count': len(history),
            'last_updated': datetime.now().isoformat()
        }, f, indent=2)
    
    print(f"   Saved {len(history)} trades to {output_path}")
    print("\n" + "=" * 60)
    print(f"✓ Success! Found {len(history)} historical trades")
    print("=" * 60)
    
    return len(history)

if __name__ == "__main__":
    try:
        fetch_and_save_history()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
