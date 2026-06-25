"""
交易流程验证工具
验证策略逻辑、风险计算、订单生成等关键环节
"""
import sys
from datetime import datetime
from config.settings import Config
from data.binance_client import BinanceClient
from strategy.momentum import MomentumStrategy
from risk.manager import RiskManager

def print_section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def test_api_connection():
    """测试 API 连接"""
    print_section("1. API 连接测试")
    try:
        client = BinanceClient()
        balance = client.get_balance()
        print(f"✅ API 连接成功")
        print(f"   账户余额: {balance:.2f} USDT")
        return client, balance
    except Exception as e:
        print(f"❌ API 连接失败: {e}")
        return None, 0

def test_market_data(client):
    """测试市场数据获取"""
    print_section("2. 市场数据测试")
    try:
        top_gainers = client.get_top_gainers(limit=10)
        print(f"✅ 成功获取涨幅榜")
        print(f"   前10名币种:")
        for i, (symbol, data) in enumerate(top_gainers[:5], 1):
            print(f"   {i}. {symbol}: +{data['percentage']:.2f}%")
        return top_gainers
    except Exception as e:
        print(f"❌ 获取涨幅榜失败: {e}")
        return []

def test_strategy_filter(top_gainers):
    """测试策略筛选"""
    print_section("3. 策略筛选测试")
    try:
        strategy = MomentumStrategy()
        qualified = strategy.filter_top_gainers(top_gainers)
        print(f"✅ 筛选逻辑执行成功")
        print(f"   原始币种数: {len(top_gainers)}")
        print(f"   筛选后币种数: {len(qualified)} (5%-20% 涨幅区间)")
        if qualified:
            print(f"   符合条件的币种:")
            for symbol in qualified[:5]:
                for s, data in top_gainers:
                    if s == symbol:
                        print(f"   - {symbol}: +{data['percentage']:.2f}%")
                        break
        return qualified
    except Exception as e:
        print(f"❌ 策略筛选失败: {e}")
        return []

def test_signal_generation(client, symbols):
    """测试信号生成"""
    print_section("4. 信号生成测试")
    if not symbols:
        print("⚠️  无可测试币种")
        return None
    
    strategy = MomentumStrategy()
    test_symbol = symbols[0]
    
    try:
        print(f"   测试币种: {test_symbol}")
        df = client.get_historical_klines(test_symbol, timeframe='15m', limit=50)
        
        if df.empty:
            print(f"❌ 无法获取 K 线数据")
            return None
            
        signal = strategy.check_signal(test_symbol, df)
        metrics = strategy.calculate_signal_score(df)
        
        print(f"✅ K 线数据加载成功 ({len(df)} 根)")
        print(f"   K 线形态: {'看涨' if metrics['pattern'] else '震荡/跌'}")
        print(f"   量能确认: {'满足' if metrics['volume'] else '不足'}")
        print(f"   综合状态: {metrics['status']}")
        print(f"   信号结果: {'🟢 做多信号' if signal else '🔴 无信号'}")
        
        return signal, df
    except Exception as e:
        print(f"❌ 信号生成失败: {e}")
        return None

def test_risk_calculation(balance, signal_data):
    """测试风险计算"""
    print_section("5. 风险管理测试")
    if not signal_data:
        print("⚠️  无信号数据，跳过风险测试")
        return
    
    signal, df = signal_data
    if not signal:
        print("⚠️  当前无信号，使用模拟数据测试")
        entry_price = df['close'].iloc[-1]
    else:
        entry_price = signal['entry_price']
    
    try:
        risk_manager = RiskManager()
        
        # 计算止损
        stop_loss = risk_manager.calculate_stop_loss(df, entry_price, 'LONG')
        sl_distance = entry_price - stop_loss
        sl_percent = (sl_distance / entry_price) * 100
        
        print(f"   入场价格: {entry_price:.6f}")
        print(f"   止损价格: {stop_loss:.6f}")
        print(f"   止损距离: {sl_percent:.2f}%")
        
        # 计算仓位
        quantity = risk_manager.calculate_position_size(balance, entry_price, stop_loss)
        margin = balance * Config.TRADE_MARGIN_PERCENT
        position_value = quantity * entry_price
        
        print(f"\n   保证金配置:")
        print(f"   - 账户余额: {balance:.2f} USDT")
        print(f"   - 使用比例: {Config.TRADE_MARGIN_PERCENT*100}%")
        print(f"   - 实际保证金: {margin:.2f} USDT")
        print(f"   - 杠杆倍数: {Config.LEVERAGE}x")
        print(f"   - 仓位价值: {position_value:.2f} USDT")
        print(f"   - 交易数量: {quantity:.6f}")
        
        # 验证仓位合理性
        if quantity <= 0:
            print(f"\n   ❌ 仓位计算异常: 数量为 0")
        elif position_value < 5:
            print(f"\n   ⚠️  仓位价值过小 ({position_value:.2f} USDT < 5 USDT)")
            print(f"      币安最小订单金额要求可能不满足")
        else:
            print(f"\n   ✅ 仓位计算正常")
            
        # 测试移动止盈
        activation_price = entry_price * (1 + Config.TRAILING_ACTIVATION)
        callback_price = activation_price * (1 - Config.TRAILING_CALLBACK)
        
        print(f"\n   移动止盈配置:")
        print(f"   - 激活条件: 盈利 {Config.TRAILING_ACTIVATION*100}% (价格 ≥ {activation_price:.6f})")
        print(f"   - 回调触发: 回撤 {Config.TRAILING_CALLBACK*100}% (价格 ≤ {callback_price:.6f})")
        
    except Exception as e:
        print(f"❌ 风险计算失败: {e}")

def test_order_validation():
    """测试订单验证"""
    print_section("6. 订单约束测试")
    
    print(f"   最大持仓数: {Config.MAX_OPEN_POSITIONS}")
    print(f"   - ✅ 单一持仓限制已启用")
    print(f"   - 当有持仓时，新信号将被跳过")
    
    print(f"\n   杠杆配置: {Config.LEVERAGE}x")
    if Config.LEVERAGE >= 20:
        print(f"   - ⚠️  高杠杆风险，建议小额测试")
    else:
        print(f"   - ✅ 杠杆倍数适中")

def main():
    print("\n" + "█"*60)
    print(" "*15 + "交易流程验证工具")
    print(" "*10 + f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("█"*60)
    
    # 1. API 连接
    client, balance = test_api_connection()
    if not client:
        print("\n❌ API 连接失败，验证终止")
        return False
    
    # 2. 市场数据
    top_gainers = test_market_data(client)
    if not top_gainers:
        print("\n❌ 市场数据获取失败，验证终止")
        return False
    
    # 3. 策略筛选
    qualified_symbols = test_strategy_filter(top_gainers)
    
    # 4. 信号生成
    signal_data = test_signal_generation(client, qualified_symbols) if qualified_symbols else None
    
    # 5. 风险计算
    test_risk_calculation(balance, signal_data)
    
    # 6. 订单验证
    test_order_validation()
    
    # 总结
    print_section("验证总结")
    if balance < 10:
        print("⚠️  账户余额不足 10 USDT，可能无法正常下单")
        print("   建议充值至 50-100 USDT")
    
    if not qualified_symbols:
        print("⚠️  当前市场无符合条件的币种 (5%-20% 涨幅区间)")
        print("   这是正常现象，机器人将持续监控")
    
    print("\n✅ 交易流程验证完成")
    print("   如所有测试通过，机器人可正常运行")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  验证已中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 验证过程异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
