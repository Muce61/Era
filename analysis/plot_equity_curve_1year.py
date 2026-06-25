import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np

# Set style
plt.style.use('bmh')

def plot_multi_period_equity(csv_path='backtest_trades.csv', output_prefix='equity_curve_1year'):
    print(f"Reading {csv_path}...")
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Parse dates
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df.sort_values('exit_time', inplace=True)
    
    # Create a time series of balance (we need to resample properly)
    # We take the LAST balance available in each period
    df.set_index('exit_time', inplace=True)
    
    # Resample frequencies
    periods = {
        'Daily': 'D',
        'Weekly': 'W',
        'Monthly': 'M'
    }
    
    for name, freq in periods.items():
        print(f"Generating {name} plot...")
        
        # Resample: Take the last balance of the period
        # If no trades in a period, forward fill the previous balance
        equity_series = df['balance_after'].resample(freq).last().ffill()
        
        # Calculate Drawdown based on this series
        peak = equity_series.cummax()
        drawdown = (equity_series - peak) / peak * 100
        
        # Plot
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)
        
        # Equity
        ax1.plot(equity_series.index, equity_series.values, label=f'Balance ({name})', color='#00aaff', linewidth=2)
        ax1.set_title(f'1-Year Equity Curve ({name} View) - Nov 2024 to Dec 2025', fontsize=14)
        ax1.set_ylabel('Balance ($)', fontsize=12)
        ax1.legend(loc='upper left')
        ax1.grid(True, which="both", ls="-", alpha=0.3)
        
        # Log scale if huge growth
        if equity_series.max() / (equity_series.min() + 1e-9) > 10:
             ax1.set_yscale('log')
             ax1.set_ylabel('Balance ($) [Log Scale]', fontsize=12)

        # Drawdown
        ax2.fill_between(drawdown.index, drawdown.values, 0, color='#ff4444', alpha=0.3, label='Drawdown')
        ax2.plot(drawdown.index, drawdown.values, color='#ff4444', linewidth=1)
        ax2.set_ylabel('Drawdown (%)', fontsize=12)
        ax2.set_xlabel('Date', fontsize=12)
        ax2.legend(loc='lower left')
        ax2.grid(True, alpha=0.3)
        
        # Format X Axis
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        if freq == 'D':
            ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        elif freq == 'W':
            ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        else:
             ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
             
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        filename = f"{output_prefix}_{name.lower()}.png"
        plt.savefig(filename, dpi=300)
        print(f"Saved {filename}")
        plt.close()

if __name__ == "__main__":
    plot_multi_period_equity()
