
import pandas as pd
from pathlib import Path
import sys

def compare_backtests():
    file_3month = Path("e:/dikong/eth/backtest_trades.csv")
    file_3day = Path("e:/dikong/eth/backtest_trades copy 2.csv") # 3-day result
    
    # Target Range (UTC)
    start_time = pd.Timestamp("2025-12-12 10:00:00", tz='UTC')
    end_time = pd.Timestamp("2025-12-12 20:00:00", tz='UTC')
    
    print(f"Comparing trades from {start_time} to {end_time} UTC")
    
    # Load Dataframe
    # We need to handle potential missing headers or confirm headers
    # Let's try loading first row to check
    try:
        df1 = pd.read_csv(file_3month)
        df2 = pd.read_csv(file_3day)
        
        # Check if first column looks like a header or data
        # If 'symbol' or 'entry_time' is in columns, we are good.
        # If columns are '0', '1', etc, or numbers, we might need names.
        
        print(f"3-Month File Columns: {df1.columns.tolist()[:3]}...")
        print(f"3-Day File Columns: {df2.columns.tolist()[:3]}...")
        
        # Ensure timestamp columns are parsed
        # Usually RealBacktestEngine saves: 
        # index, symbol, entry_price, exit_price, entry_time, exit_time, pnl, balance, exit_reason, duration...
        
        # We need to identify the time column. Usually 'entry_time'.
        time_col = 'entry_time'
        if time_col not in df1.columns:
            # Fallback: maybe it's unnamed or different?
            # Let's look for a column that parses to datetime
            pass
            
        df1[time_col] = pd.to_datetime(df1[time_col], utc=True)
        df2[time_col] = pd.to_datetime(df2[time_col], utc=True)
        
        # Filter
        df1_copy = df1[(df1[time_col] >= start_time) & (df1[time_col] <= end_time)].copy()
        df2_copy = df2[(df2[time_col] >= start_time) & (df2[time_col] <= end_time)].copy()
        
        # Sort to ensure alignment
        # Sort by entry_time, then symbol
        df1_sorted = df1_copy.sort_values(by=[time_col, 'symbol']).reset_index(drop=True)
        df2_sorted = df2_copy.sort_values(by=[time_col, 'symbol']).reset_index(drop=True)
        
        print(f"\nTrades in 3-Month Backtest (in range): {len(df1_sorted)}")
        print(f"Trades in 3-Day Backtest (in range): {len(df2_sorted)}")
        
        # Compare
        if len(df1_sorted) != len(df2_sorted):
            print("\n❌ Mismatch in number of trades!")
            # Find diff
            # We can merge outer to see differences
            merged = pd.merge(df1_sorted, df2_sorted, on=[time_col, 'symbol'], how='outer', indicator=True, suffixes=('_3m', '_3d'))
            only_3m = merged[merged['_merge'] == 'left_only']
            only_3d = merged[merged['_merge'] == 'right_only']
            
            if not only_3m.empty:
                print(f"Trades ONLY in 3-Month ({len(only_3m)}):")
                print(only_3m[[time_col, 'symbol']].head())
            if not only_3d.empty:
                print(f"Trades ONLY in 3-Day ({len(only_3d)}):")
                print(only_3d[[time_col, 'symbol']].head())
        else:
            # Deep comparison
            # Check key columns: symbol, entry_price, exit_price, pnl
            cols_to_compare = ['symbol', 'entry_price', 'exit_price', 'pnl']
            # Only compare columns that exist
            cols = [c for c in cols_to_compare if c in df1_sorted.columns]
            
            diff_count = 0
            for i in range(len(df1_sorted)):
                row1 = df1_sorted.iloc[i]
                row2 = df2_sorted.iloc[i]
                
                match = True
                reason = ""
                for c in cols:
                    val1 = row1[c]
                    val2 = row2[c]
                    
                    # Float comparison
                    if isinstance(val1, float) and isinstance(val2, float):
                        if abs(val1 - val2) > 1e-6: # Tolerance
                            match = False
                            reason = f"{c} mismatch: {val1} vs {val2}"
                            break
                    elif val1 != val2:
                        match = False
                        reason = f"{c} mismatch: {val1} vs {val2}"
                        break
                
                if not match:
                    diff_count += 1
                    print(f"Diff at index {i} ({row1['symbol']} @ {row1[time_col]}): {reason}")
                    
            if diff_count == 0:
                print("\n✅ PERFECT MATCH: Trades are identical.")
            else:
                print(f"\n❌ FOUND {diff_count} DIFFERENCES within matching trades.")

    except Exception as e:
        print(f"Error during comparison: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    compare_backtests()
