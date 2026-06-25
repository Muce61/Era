"""
简化版交易流程验证工具
直接从 .env 文件读取配置，避免 dotenv 加载问题
"""
import os
import ccxt
import pandas as pd
from datetime import datetime

def print_section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def load_env_manual():
    """手动加载 .env 文件"""
    env_vars = {}
    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key] = value
        return env_vars
    except FileNotFoundError:
        print("❌ 未找到 .env 文件")
        return {}

def main():
    print("\n" + "█"*60)
    print(" "*12 + "交易流程验证工具 (简化版)")
    print(" "*10 + f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("█"*60)
    
    # 1. 加载环境变量
    print_section("1. 配置加载")
    env = load_env_manual()
    api_key = env.get('BINANCE_API_KEY', '')
    secret = env.get('BINANCE_SECRET', '')
    testnet = env.get('BINANCE_TESTNET', 'False').lower() == 'true'
    
    print(f"   API Key: {api_key[:10]}...{api_key[-10:] if api_key else 'None'}")
    print(f"   Secret: {secret[:10]}...{secret[-10:] if secret else 'None'}")
    print(f"   Testnet: {testnet}")
    
    if not api_key or not secret:
        print("\n❌ API 凭证缺失，验证终止")
        return False
    
    # 2. 测试 API 连接
    print_section("2. API 连接测试")
    try:
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret,
            'options': {'defaultType': 'future'},
            'enableRateLimit': True
        })
        
        if testnet:
            print("   ⚠️  测试网模式已启用（Binance 合约测试网已停用）")
        
        balance_info = exchange.fetch_balance()
        balance = balance_info['total'].get('USDT', 0)
        
        print(f"✅ API 连接成功")
        print(f"   账户余额: {balance:.2f} USDT")
        
        if balance < 10:
            print(f"   ⚠️  余额不足 10 USDT，可能无法正常交易")
    except Exception as e:
        print(f"❌ API 连接失败: {e}")
        print("   请检查:")
        print("   1. API Key 和 Secret 是否正确")
        print("   2. API 是否启用了合约交易权限")
        print("   3. 是否设置了IP白名单限制")
        return False
    
    # 3. 测试市场数据获取
    print_section("3. 市场数据测试")
    try:
        tickers = exchange.fetch_tickers()
        usdt_tickers = {
            symbol: data for symbol, data in tickers.items()
            if '/USDT' in symbol and data['percentage'] is not None
        }
        
        sorted_tickers = sorted(
            usdt_tickers.items(),
            key=lambda x: x[1]['percentage'],
            reverse=True
        )[:10]
        
        print(f"✅ 成功获取市场数据")
        print(f"   USDT 合约币种数: {len(usdt_tickers)}")
        print(f"   前10名涨幅:")
        for i, (symbol, data) in enumerate(sorted_tickers, 1):
            print(f"   {i}. {symbol}: +{data['percentage']:.2f}%")
        
        # 筛选符合条件的币种(5%-20%)
        qualified = [
            (symbol, data) for symbol, data in sorted_tickers
            if 5.0 <= data['percentage'] <= 20.0
        ]
        
        print(f"\n   符合条件的币种 (5%-20%): {len(qualified)}")
        if qualified:
            for symbol, data in qualified[:5]:
                print(f"   - {symbol}: +{data['percentage']:.2f}%")
        else:
            print("   ⚠️  当前无符合条件的币种")
            
    except Exception as e:
        print(f"❌ 市场数据获取失败: {e}")
        return False
    
    # 4. 测试 K 线数据获取
    print_section("4. K线数据测试")
    test_symbol = sorted_tickers[0][0] if sorted_tickers else 'BTC/USDT:USDT'
    try:
        print(f"   测试币种: {test_symbol}")
        ohlcv = exchange.fetch_ohlcv(test_symbol, '15m', limit=50)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        print(f"✅ K线数据获取成功")
        print(f"   数据行数: {len(df)}")
        print(f"   最新收盘价: {df['close'].iloc[-1]:.6f}")
        print(f"   最新成交量: {df['volume'].iloc[-1]:.2f}")
        
        # 简单检查连续阳线
        bullish_count = 0
        for i in range(len(df)-3, len(df)):
            if df['close'].iloc[i] > df['open'].iloc[i]:
                bullish_count += 1
        
        print(f"   最近3根K线阳线数: {bullish_count}/3")
        
    except Exception as e:
        print(f"❌ K线数据获取失败: {e}")
        return False
    
    # 5. 风险参数检查
    print_section("5. 风险参数配置")
    leverage = 20
    margin_percent = 0.90
    max_positions = 1
    
    print(f"   杠杆倍数: {leverage}x")
    print(f"   保证金比例: {margin_percent*100}%")
    print(f"   最大持仓数: {max_positions}")
    
    # 模拟仓位计算
    if balance > 0:
        margin = balance * margin_percent
        position_value = margin * leverage
        
        print(f"\n   示例仓位计算 (以当前余额):")
        print(f"   - 账户余额: {balance:.2f} USDT")
        print(f"   - 保证金: {margin:.2f} USDT")
        print(f"   - 仓位价值: {position_value:.2f} USDT")
        
        if position_value < 5:
            print(f"   ❌ 仓位价值过小，低于币安最小订单要求(通常5-10 USDT)")
        elif balance < 50:
            print(f"   ⚠️  余额较小，建议充值至50-100 USDT以确保稳定交易")
        else:
            print(f"   ✅ 仓位配置合理")
    
    # 总结
    print_section("验证总结")
    print("✅ 所有核心功能验证通过")
    print("\n建议:")
    if balance < 50:
        print("  1. 充值至少 50-100 USDT")
    if testnet:
        print("  2. 将 BINANCE_TESTNET 设置为 False (实盘模式)")
    if len(qualified) == 0:
        print("  3. 当前市场无符合条件币种，机器人将持续监控")
    
    print("\n✅ 交易流程验证完成，机器人可以启动")
    return True

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  验证已中断")
        exit(1)
    except Exception as e:
        print(f"\n\n❌ 验证异常: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
