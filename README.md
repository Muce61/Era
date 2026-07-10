# Era 100x

Era 是一个面向 BTC/ETH 永续合约的事件驱动研究项目。目标不是追求传统稳定年化，而是研究：在严格风险隔离和执行约束下，是否存在少量值得使用高杠杆参与的短期价格扩张窗口。

> 当前状态：**阶段 0/1，工程与研究地基**。仓库中的参数是 V1 预注册起点，不代表已被证明有效，也不构成交易建议。

## 核心原则

- 只研究可复现、可回放、可审计的规则。
- 研究、回测、模拟盘和实盘尽量复用同一套纯逻辑。
- 开仓后必须存在交易所原生保护单；保护失败则立即退出。
- 逐仓、单仓、禁止补仓、禁止马丁、禁止放宽止损。
- 先证明事件优势，再开发复杂持仓模型或机器学习。

## 技术栈

- Python 3.12+
- Polars + Parquet：数据处理和事件研究
- Pydantic：配置与领域模型
- NautilusTrader：正式事件回测、模拟盘和实盘执行（`execution` extra）
- pytest / Hypothesis / Ruff / mypy：质量门禁

## 快速开始

```bash
uv sync
uv run ruff check .
uv run mypy src
uv run pytest
uv run era100x doctor
uv run era100x show-config configs/research.yaml
```

安装正式执行引擎：

```bash
uv sync --extra execution
```

## 当前可运行能力

- 读取并严格校验 V1 YAML 配置；
- 计算逐仓合约数量并向下取整；
- 估算手续费/滑点对保证金收益率的侵蚀；
- 执行单调移动保护阶梯；
- 对价格路径生成 MFE、MAE 和竞争屏障标签；
- 校验交易状态机转换是否合法。

## 当前阶段完成定义

只有在以下条件同时满足后，阶段 1 才算完成：

1. 配置、收益口径、费用和仓位计算均有测试；
2. 秒级数据可标准化为统一 Parquet schema；
3. 多周期聚合无未来泄漏；
4. 候选事件可以输出逐秒路径、MFE/MAE和首次触及标签；
5. CI 在干净环境中通过。

详细约束见 `docs/V1_SPEC.md`。
