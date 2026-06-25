
import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import pytz

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

def verify_data_integrity():
    # Configuration
    data_dir = Path("E:/ALIXZ/new_backtest_data_1year_1m")
    target_end_time = datetime(2025, 12, 12, 20, 0, 0, tzinfo=pytz.UTC) # 2025-12-13 04:00 Beijing
    threshold_mins = 60 # Allow 60 mins gap from target time
    
    print(f"Verifying data in: {data_dir}")
    print(f"Target End Time: {target_end_time} (UTC)")
    
    # Load Expected Symbols
    try:
        from all_symbols import ALL_SYMBOLS
        expected_symbols = set(ALL_SYMBOLS)
        print(f"Loaded {len(expected_symbols)} expected symbols from all_symbols.py")
    except ImportError:
        # Fallback to reading the text file directly if import fails
        try:
            with open(project_root / 'all_symbols.txt', 'r', encoding='utf-8') as f:
                content = f.read()
                # Simple parsing for the list format
                import ast
                start = content.find('[')
                end = content.find(']') + 1
                if start != -1 and end != -1:
                    expected_symbols = set(ast.literal_eval(content[start:end]))
                    print(f"Loaded {len(expected_symbols)} expected symbols from all_symbols.txt")
                else:
                    raise ValueError("Could not parse symbol list")
        except Exception as e:
            print(f"Warning: Could not load expected symbols list: {e}")
            expected_symbols = set()

    if not data_dir.exists():
        print(f"Error: Directory {data_dir} does not exist.")
        return

    files = list(data_dir.glob("*.csv"))
    print(f"Found {len(files)} data files.")
    
    valid_count = 0
    missing_data_count = 0
    outdated_count = 0
    corrupt_count = 0
    
    missing_symbols = []
    outdated_symbols = []
    corrupt_files = []
    
    # Check existing files
    print("\nChecking files...")
    for i, file_path in enumerate(files):
        if i % 50 == 0:
            print(f"processed {i}/{len(files)}...", end='\r')
            
        symbol_name = file_path.stem # e.g., BTCUSDT
        # Clean symbol name formatting to match ALL_SYMBOLS if needed
        # Our files are like 'BTCUSDT.csv' or '1000SHIBUSDT.csv'
        # ALL_SYMBOLS are like 'BTCUSDT', '1000SHIBUSDT'
        # fetch script uses: symbol.replace('/', '').replace(':', '')
        # So 'BTC/USDT:USDT' -> 'BTCUSDTUSDT' in file name?
        # WAIT, let's check file naming convention in fetch script
        # filename = data_dir / f"{symbol.replace('/', '').replace(':', '')}.csv"
        # If symbol is 'BTC/USDT:USDT', file is 'BTCUSDTUSDT.csv'
        
        # We need to map file names back to expected symbols or vice versa
        # Expected symbols list seems to be base symbols or full symbols?
        # ALL_SYMBOLS content: 'BTCUSDT', 'ETHUSDT'
        # Real file names seen in logs: 'BTCUSDTUSDT.csv', '1000SHIBUSDTUSDT.csv'
        # It seems the file names have extra 'USDT' appended compared to ALL_SYMBOLS if ALL_SYMBOLS are just 'BTCUSDT'
        
        try:
            # Smart reading: read only last few lines to check timestamp
            # But plain CSV read validation is safer for corruption check
            # We'll read headers and last few rows
            with open(file_path, 'rb') as f:
                f.seek(0, 2) # Seek to end
                file_size = f.tell()
                if file_size < 100: # Empty or too small
                    corrupt_count += 1
                    corrupt_files.append(file_path.name)
                    continue
                    
            df = pd.read_csv(file_path)
            
            if 'timestamp' not in df.columns or df.empty:
                corrupt_count += 1
                corrupt_files.append(file_path.name)
                continue
                
            # Parse last timestamp
            last_ts_str = df.iloc[-1]['timestamp']
            last_ts = pd.to_datetime(last_ts_str)
            
            if last_ts.tz is None:
                last_ts = last_ts.tz_localize('UTC')
            else:
                last_ts = last_ts.tz_convert('UTC')
                
            # Check if outdated
            if last_ts < target_end_time - timedelta(minutes=threshold_mins):
                outdated_count += 1
                outdated_symbols.append(f"{file_path.name} (Last: {last_ts})")
            else:
                valid_count += 1
                
        except Exception as e:
            corrupt_count += 1
            corrupt_files.append(f"{file_path.name} ({str(e)})")

    print(f"\n\nVerification Results:")
    print(f"{'='*30}")
    print(f"Total Files Found: {len(files)}")
    print(f"Valid (Up-to-date): {valid_count}")
    print(f"Outdated: {outdated_count}")
    print(f"Corrupt/Empty: {corrupt_count}")
    
    if expected_symbols:
        # Check for missing symbols
        # Map filenames back to symbols
        # Assumption: Filename is SYMBOL + 'USDT' ? 
        # Actually logic is: symbol.replace('/', '').replace(':', '')
        # checking ALL_SYMBOLS again.. 'BTCUSDT'
        # Filename 'BTCUSDTUSDT.csv'
        # So we construct expected filenames from ALL_SYMBOLS
        
        # Heuristic: verify if expected symbol appears in filenames
        # Because mapping might be complex ('BTC/USDT:USDT' -> 'BTCUSDTUSDT')
        # while ALL_SYMBOLS uses 'BTCUSDT' (spot-like) or 'BTCUSDT' (contract?)
        
        # Let's try to normalize valid filenames
        # If filename starts with expected symbol?
        
        found_symbols = set()
        for f in files:
            name = f.stem
            found_symbols.add(name)
            
        # We need to guess the mapping. 
        # If ALL_SYMBOLS has 'BTCUSDT', and file is 'BTCUSDTUSDT', then mapping is sym + 'USDT'.
        # Let's check missing by checking if (sym + 'USDT') in found_symbols OR sym in found_symbols
        
        missing = []
        for sym in expected_symbols:
            # Common patterns for backtest data files based on fetch script
            candidates = [
                sym, 
                sym + 'USDT', 
                sym.replace('USDT', 'USDTUSDT') # if sym already has USDT
            ]
            
            if not any(c in found_symbols for c in candidates):
                # Try more fuzzy match?
                # or just Report
                missing.append(sym)
                
        if missing:
            print(f"\nMissing Symbols ({len(missing)}):")
            print(", ".join(missing[:50]))
            if len(missing) > 50: print("... and more")
            
    if outdated_symbols:
        print(f"\nOutdated Files ({len(outdated_symbols)}):")
        for s in outdated_symbols[:20]:
            print(s)
            
    if corrupt_files:
        print(f"\nCorrupt Files ({len(corrupt_files)}):")
        for s in corrupt_files:
            print(s)
            
    print(f"{'='*30}")

if __name__ == "__main__":
    verify_data_integrity()
