import pandas as pd
import numpy as np

def analyze_monthly_returns(csv_path):
    print(f"Analyzing monthly returns from: {csv_path}")
    
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Convert timestamps
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    
    # Sort by exit time
    df = df.sort_values('exit_time')
    
    # Add month column
    df['month'] = df['exit_time'].dt.to_period('M')
    
    # Calculate cumulative balance if not present, but we have balance_after
    # We need to reconstruct the starting balance for each month
    # The balance_after of the last trade of the previous month is the start balance of current month
    # For the first month, we need to infer. 
    # If the first trade has balance_after X and pnl Y, then start was X - Y (approx, minus fees)
    # But better to just take the first balance_after of the month as "close enough" to start?
    # No, we need precise returns.
    
    # Let's use balance_after.
    # Start Balance of Month M = Balance After of Last Trade of Month M-1
    
    monthly_stats = []
    
    # Get all unique months
    months = df['month'].unique()
    months = sorted(months)
    
    # Initial Balance (User said 100u)
    current_balance = 100.0 
    
    # Check if the first trade implies a different start?
    # first_trade = df.iloc[0]
    # implied_start = first_trade['balance_after'] - first_trade['pnl'] # roughly
    # if abs(implied_start - 100) > 10:
    #     current_balance = implied_start
        
    print(f"{'Month':<10} | {'Start Bal':<10} | {'End Bal':<10} | {'Return':<8} | {'Trades':<6} | {'Win Rate':<8} | {'Max DD':<8}")
    print("-" * 80)
    
    for month in months:
        month_trades = df[df['month'] == month]
        
        if len(month_trades) == 0:
            continue
            
        # End Balance of this month
        end_balance = month_trades.iloc[-1]['balance_after']
        
        # Net Profit for this month
        net_pnl = month_trades['pnl'].sum()
        
        # Start Balance = End Balance - Net PnL (Exact?)
        # balance_after includes fees. PnL in CSV usually is Net PnL (after fees)?
        # Let's check real_engine.py: 
        # net_pnl = pnl - fee
        # self.balance += net_pnl
        # So yes, balance_after = prev_balance + net_pnl
        # So prev_balance = balance_after - net_pnl
        
        # But this is cumulative.
        # Start Balance of Month = Balance before first trade of month
        first_trade_idx = month_trades.index[0]
        # We need the balance *before* this trade.
        # It is trade['balance_after'] - trade['pnl']
        start_balance = month_trades.iloc[0]['balance_after'] - month_trades.iloc[0]['pnl']
        
        # If this is not the very first month, it should match previous month end
        # But let's trust the calculation derived from the first trade of the month
        
        # Return %
        return_pct = ((end_balance - start_balance) / start_balance) * 100
        
        # Win Rate
        wins = len(month_trades[month_trades['pnl'] > 0])
        total = len(month_trades)
        win_rate = (wins / total) * 100
        
        # Max Drawdown within the month
        # We need to reconstruct the balance curve for the month
        balances = [start_balance]
        for _, trade in month_trades.iterrows():
            balances.append(trade['balance_after'])
            
        balances = np.array(balances)
        peak = np.maximum.accumulate(balances)
        drawdowns = (peak - balances) / peak
        max_dd = np.max(drawdowns) * 100
        
        print(f"{str(month):<10} | ${start_balance:<9.2f} | ${end_balance:<9.2f} | {return_pct:>7.2f}% | {total:<6} | {win_rate:>7.2f}% | {max_dd:>7.2f}%")
        
        monthly_stats.append({
            'month': str(month),
            'return': return_pct,
            'max_dd': max_dd,
            'trades': total
        })
        
    # Total stats
    total_return = ((df.iloc[-1]['balance_after'] - 100) / 100) * 100
    print("-" * 80)
    print(f"Total Return: {total_return:.2f}%")

if __name__ == "__main__":
    analyze_monthly_returns('backtest_results/csv/backtest_trades_november.csv')
