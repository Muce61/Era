import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

# Set style
plt.style.use('bmh') # Use a built-in style that looks decent

def plot_equity_curve(csv_path='backtest_trades.csv', output_path='equity_curve.png'):
    print(f"Reading {csv_path}...")
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Parse dates
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df.sort_values('exit_time', inplace=True)
    
    # Calculate Drawdown
    df['peak_balance'] = df['balance_after'].cummax()
    df['drawdown'] = (df['balance_after'] - df['peak_balance']) / df['peak_balance'] * 100
    
    # Prepare Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)
    
    # Plot 1: Equity Curve (Log Scale usually better for 44,000% returns)
    ax1.plot(df['exit_time'], df['balance_after'], label='Balance', color='#00aaff', linewidth=1.5)
    ax1.set_title(f'Equity Curve: 50x Rolling Universe (Sept-Dec 2025)', fontsize=14, pad=15)
    ax1.set_ylabel('Balance ($)', fontsize=12)
    ax1.legend(loc='upper left')
    ax1.grid(True, which="both", ls="-", alpha=0.3)
    
    # Use Log Scale if growth is massive
    if df['balance_after'].max() / df['balance_after'].min() > 10:
        ax1.set_yscale('log')
        ax1.set_ylabel('Balance ($) [Log Scale]', fontsize=12)

    # Plot 2: Drawdown
    ax2.fill_between(df['exit_time'], df['drawdown'], 0, color='#ff4444', alpha=0.3, label='Drawdown')
    ax2.plot(df['exit_time'], df['drawdown'], color='#ff4444', linewidth=1)
    ax2.set_ylabel('Drawdown (%)', fontsize=12)
    ax2.set_xlabel('Date', fontsize=12)
    ax2.legend(loc='lower left')
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(bottom=df['drawdown'].min() * 1.1, top=5) # Show mostly existing drawdown range
    
    # Format X Axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax2.xaxis.set_major_locator(mdates.DayLocator(interval=7)) # Every week
    plt.xticks(rotation=45)
    
    # Save
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    print(f"Saved plot to {output_path}")

if __name__ == "__main__":
    plot_equity_curve()
