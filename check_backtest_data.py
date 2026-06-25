"""
检查回测数据时间分布
"""
import pandas as pd

print("="*80)
print("回测数据时间分布分析")
print("="*80)

# 读取CSV
df_30 = pd.read_csv('backtest_trades_30d.csv')
df_90 = pd.read_csv('backtest_trades_90d.csv')

# 转换时间
df_30['entry_time'] = pd.to_datetime(df_30['entry_time'])
df_90['entry_time'] = pd.to_datetime(df_90['entry_time'])

print("\n📊 30天回测 (最近30天):")
print(f"   最早交易: {df_30['entry_time'].min()}")
print(f"   最晚交易: {df_30['entry_time'].max()}")
print(f"   总交易数: {len(df_30)}")
print(f"   时间跨度: {(df_30['entry_time'].max() - df_30['entry_time'].min()).days}天")

print("\n📊 90天回测 (最近90天):")
print(f"   最早交易: {df_90['entry_time'].min()}")
print(f"   最晚交易: {df_90['entry_time'].max()}")
print(f"   总交易数: {len(df_90)}")
print(f"   时间跨度: {(df_90['entry_time'].max() - df_90['entry_time'].min()).days}天")

# 找出额外的交易
print("\n🔍 额外的3笔交易 (90天比30天多的):")
# 使用entry_time比较
extra_mask = ~df_90['entry_time'].isin(df_30['entry_time'])
extra_trades = df_90[extra_mask]

if len(extra_trades) > 0:
    print(f"   共{len(extra_trades)}笔")
    for idx, row in extra_trades.iterrows():
        print(f"   - {row['entry_time']}: {row['symbol']} PnL=${row['pnl']:.2f}")
else:
    print("   (无额外交易,所有交易都在30天范围内)")

# 月份分布
print("\n📅 90天回测 - 按月份分组:")
df_90['month'] = df_90['entry_time'].dt.to_period('M')
monthly = df_90.groupby('month').size()
for month, count in monthly.items():
    print(f"   {month}: {count}笔交易")

print("\n" + "="*80)
print("结论: 如果额外3笔都在9-10月,说明9-10月数据稀疏/不完整")
print("="*80)
