---
document_status: FINAL_BASELINE
document_version: V1.3.5
source_document: system_manual_v1.3.5_final.md
supersedes:
  - V1.2
  - V1.3
  - V1.3.1
  - V1.3.2
  - V1.3.3
  - V1.3.4
implementation_authority: true
---

# 100x 高确认赌博交易系统

## 最终研发手册 V1.3.5｜生命周期研究修订版

Research & Engineering Manual · V1.3.5

> 项目定义：使用隔离的小额实验票，在 Binance USDⓈ-M BTCUSDT/ETHUSDT 永续合约中，仅参与少数短期高位移事件；目标是构建可研究、可回放、可审计、具备交易所驻留灾难保护和确定性退出协调的高风险下注系统，而不是承诺稳定收益。

| 项目 | 内容 |
| --- | --- |
| 项目负责人 | Muce |
| 版本 | V1.3.5（生命周期研究修订版） |
| 发布日期 | 2026-07-23 |
| 目标市场 | Binance USDⓈ-M USDT 永续；BTC/ETH 分开研究 |
| 历史数据上限 | 既有数据 + Binance 逐笔成交；历史 Quote/秒级 Mark/L2/真实延迟/自有执行不可补齐 |
| 主技术路线 | Polars + Parquet + NautilusTrader（研究/回测）+ 独立 Binance Execution Adapter |
| 文档性质 | 研究规格、执行契约、状态机、阶段门槛与 Codex 开发依据 |

核心原则：先证明事件优势；用 H3 压力情景而非伪造执行数据；用 F1 前向事实验证执行；任何真实仓位必须有交易所驻留灾难保护或处于持久化紧急处理状态。

## 文档控制

### 版本目的

V1.3.5 以 V1.3.4 为正文基线，新增一个严格隔离的 Stage 2 条件 H3 生命周期研究入口，
用于比较“8 分钟退出”与“继续持有至理论完全平仓”的代理结果。它不改变真实执行、灾难
保护、PositionClosureProtocol、Stage 3 完整 H3 验收或任何 small-live 门。旧 T1～T4
事件路径、T2 Primary 和既有密封证据保持不可变。

### 规则状态

| 状态 | 含义 | 修改要求 |
| --- | --- | --- |
| FROZEN | 工程和实盘必须执行的硬约束 | 只能通过 ADR、测试和版本升级修改 |
| BASELINE | 首轮研究或联调的起始值 | 可通过预注册实验修改，不代表最优 |
| RESEARCH | 当前证据不足，只允许研究 | 不得直接进入实盘配置 |
| DEPRECATED | 已被事实否定或被新架构替代 | 不得换名恢复 |
| BLOCKED_BY_FORWARD_VALIDATION | 需要 F1 前向事实才能确定 | 在影子/测试/小额实盘前不得宣称成立 |

### 规则元数据

每条可执行规则必须携带：rule_id、status、source、owner、tests、effective_version、live_override=false。FROZEN 规则必须同时定义输入、检测时机、失败动作和测试编号。

### 目录

- 第一篇：项目定义与证据边界

- 第二篇：V1.3 系统与事件规格

- 第三篇：研究方法与评价指标

- 第四篇：执行契约与状态机

- 第五篇：工具链与工程规范

- 第六篇：阶段路线与验收门槛

- 第七篇：前向运行、极小实盘与单轮实验

- 第八篇：事故处理与研发治理

- 附录 A-N

## 第一篇　项目定义与证据边界

### 1. 项目使命

研发一套 BTCUSDT/ETHUSDT 永续事件驱动系统：大多数时间空仓，只在高周期环境允许、低周期失败跌破结构成立、秒级价格或逐笔成交流启动的窗口生成一次开仓意图；使用最高 100 倍杠杆放大短期价格位移，开仓后按事件更新风险，并通过不可变交易所灾难止损与本地确定性主动退出限制失控路径。

#### 1.1 最终实验目标

- 初始实验票面权益 E0 = 10 USDT。

- 一轮最多允许一个产生非零成交的 EntryIntent。

- 只有 PositionClosureProtocol 产生最终 POSITION_FLAT 后，才写入 final_realized_ticket_equity。若 final_realized_ticket_equity >= 2 * starting_ticket_equity，本轮为 ROUND_SUCCESS；否则为 ROUND_FAILED。

- 无论成功或失败，本轮进入持久化 LOCKED，下一轮只能人工创建。

- 10 × 2^17 = 1,310,720 USDT仅表示数学路径。17 轮概率必须由单轮结果估计，不得用事件 Target-First Rate 直接替代。

#### 1.2 目标链条

最终目标必须通过以下逻辑桥梁逐层证明：

历史数据 → 特征 → MarketEpisode → EntryIntent → 路径标签 → H3 条件单轮代理概率 → F1 执行情景分布与无条件实盘单轮概率 → 极小资金执行校准 → 多轮概率与容量评估

任一中间层未通过，禁止向后推断。

#### 1.3 明确的非目标

- 不追求全年平滑收益、传统夏普率最大化或每日交易。

- 不保证 10 USDT 可以达到 100 万 USDT。

- 不尝试买到绝对最低点。

- V1.3.4 不研究做空、加仓、补仓、马丁或同轮追回。

- 不把“高确认”当作统计证据。

- 不用风险管理修复一个没有事件优势的信号。

- 不把历史成本情景写成真实可成交收益。

- 不在 V1.3.4 开发算法 2、自动 17 轮复利或 L2 策略。

#### 1.4 已接受与不可接受的风险

| 类别 | 处理 |
| --- | --- |
| 单张实验票可能大幅亏损或归零 | 已接受的赌博风险 |
| 连续 17 轮概率极低 | 已接受并必须报告 |
| 100x 导致价格 bp 被放大 | 已接受，研究统一使用价格 bp |
| 裸仓、重复仓、反向仓、错误 PnL、状态回退 | 不接受，属于工程缺陷 |
| 历史无 Quote/L2 造成执行证据不足 | 接受数据边界，但必须降级为 H3 |
| 无法确认订单时盲目重发 | 不接受，必须进入对账或依赖驻留保护 |

### 2. 证据等级

| 等级 | 数据与能力 | 可以证明 | 不能证明 |
| --- | --- | --- | --- |
| H1 | 1 秒 Contract Price + 分钟状态 | 粗路径、时间止损、候选事件 | 秒内先后、真实成交 |
| H2 | H1 + Binance 逐笔成交 | 秒内顺序、主动成交方向、精细 First Passage | 历史 Bid/Ask、真实滑点、历史部分成交 |
| H3 | H2 + 预注册成本/延迟/止损滑点情景 | 策略在保守代理条件下是否仍有研究价值 | 历史真实可成交净收益 |
| F1 | 前向 Quote/Mark/Depth/私有订单/自有成交 | 实际点差、延迟、部分成交、止损和执行偏差 | 未来长期稳定性 |

历史证据上限为 H3。影子、测试网和小额实盘必须明确标记为 F1；测试网仅验证协议和状态恢复，不用于校准正式市场流动性。

### 3. 历史数据能力边界

#### 3.1 已拥有或可补齐

- BTC/ETH 2020-01-01 至 2026-07-03 的秒级 Contract Price OHLCV。

- 分钟级 OHLCV、资金费、OI、爆仓、Mark、Index、Premium 等状态数据。

- Binance 逐笔成交，作为唯一计划补齐的历史微观结构数据。

#### 3.2 历史不可补齐

- BookTicker/Bid/Ask 与真实点差。

- 秒级或 Tick 级 Mark Price。

- L2 盘口、撤单、补单、排队和流动性冲击。

- 本地接收延迟、订单确认延迟。

- 自有订单、部分成交、拒单和真实止损滑点。

#### 3.3 数据边界硬规则

- 历史模式中的 reference_ask、spread_bps、historical_recv_latency、actual_partial_fill_probability 必须为 NULL，不得填 0。

- 历史滑点、点差和延迟只能存储为 cost_scenario_id 及情景参数。

- H1/H2 reclaim 和 invalidation 使用 Contract Price/Trade reference，不得使用伪造的 executable Bid/Ask。

- 历史不得使用盘口失衡、撤单、补单、吸收或秒级 Mark 精确触发。

- F1 才允许使用 Quote、Mark、Depth 和自有执行字段。

## 第二篇　V1.3.4 系统与事件规格

### 4. 冻结范围

| 维度 | V1.3.4 决策 | 状态 |
| --- | --- | --- |
| 交易所 | Binance USDⓈ-M | FROZEN |
| 标的 | BTCUSDT、ETHUSDT 分开研究；一次仅启用一个 | FROZEN |
| 方向 | 只做多 | FROZEN |
| 策略家族 | 关键低点被扫后收回并启动 | FROZEN 到规则家族 |
| 杠杆 | 研究用价格 bp；实验上限 100x | FROZEN 上限 |
| 保证金 | Isolated；禁止 Cross | FROZEN |
| 持仓 | 单仓；禁止加仓、补仓 | FROZEN |
| 开仓 | 带最高可接受价格的 LIMIT IOC | BASELINE |
| 灾难保护 | Binance Algo STOP_MARKET，closePosition=true，不可变 | FROZEN；workingType 为 BASELINE |
| 本地保护 | ExitCoordinator 发出主动 reduce-only 退出 | FROZEN |
| 一轮 | 最多一个非零成交 EntryIntent | FROZEN |
| 算法 2 | 不进入 V1.3.4 | DEPRECATED FOR V1.3.4 |

### 5. 配置与规则优先级

- 交易所硬约束与安全不变量。

- 已批准的实盘风险配置，只能收紧。

- 策略版本默认值与配置哈希。

- 研究实验覆盖值，仅 research/backtest。

- 命令行临时参数，live/compound 禁用。

解析后生成唯一 effective_config.json；日志、订单和报告只能引用其哈希。

### 6. 收益、价格与权益口径

#### 6.1 字段定义

| 字段 | 定义 |
| --- | --- |
| reference_price | 产生决策时的参考价；历史为 Contract/Trade，前向可为 Ask/Bid |
| proxy_entry_price | H3 成本情景生成的代理入场成交价 |
| proxy_exit_price | H3 情景生成的代理退出成交价 |
| proxy_net_pnl | 由代理成交价、代理费用和资金费计算的历史情景净 PnL |
| estimated_exit_net_pnl | 持仓中基于当前可执行报价和预计费用的可退出净 PnL |
| realized_net_pnl | 只由真实成交均价、真实手续费和真实资金费计算 |
| scenario_net_expectancy | H3 情景下的事件平均净期望 |
| estimated_ticket_equity_if_flat | 退出过程中的票面权益估计；不得用于 ROUND_SUCCESS/ROUND_FAILED |
| price_return_bps | 相对指定价格源的标的位移；必须携带 valuation_price_type |
| MFE/MAE | 指定路径价格源下的最大有利/不利位移 |
| conditional_round_success_probability | H3 在预注册的成交、部分成交、成本和延迟情景成立条件下，事件完成单轮翻倍的代理概率。 |
| unconditional_live_round_success_probability | F1 基于真实执行情景经验分布加权得到的实盘无条件单轮概率；样本不足时不得声明稳定值。 |
| final_realized_ticket_equity | 仅在最终 POSITION_FLAT 后写入的本轮归属权益；轮次结算唯一依据 |

#### 6.2 禁止双扣滑点

真实模式中：

realized_net_pnl = realized_gross_pnl - actual_commission - actual_funding

真实成交均价已经包含滑点，不得再次扣除价格滑点。slippage_bps仅作为“参考价格与真实成交价的偏差统计”。

H3 模式中先用情景参数生成代理成交价，再计算 PnL；不得在代理成交价之外重复扣除同一滑点。

#### 6.3 10 USDT 简化算例

假设：E0=10、储备 R=2、使用保证金 M=8、杠杆 L=100、名义仓位 N=800、往返手续费 9bp、总滑点情景 2bp，且入场/退出名义价值近似相同。

| 项目 | 计算 | 结果 |
| --- | --- | --- |
| 名义仓位 | 8 × 100 | 800 USDT |
| 情景总成本 | 800 × 11/10000 | 0.88 USDT |
| 翻倍毛利润需求 | 10 + 0.88 | 10.88 USDT |
| 翻倍价格位移 | 10.88/800×10000 | 136 bp |
| 保证金毛 ROE | 10.88/8 | 136% |
| 保证金净 ROE | 10/8 | 125% |
| 25bp 止损票面损失 | 2.00+0.88 | 2.88 USDT |
| 25bp 止损净 ROE | -2.88/8 | -36% |
| +20% 净 ROE 激活 | (1.60+0.88)/800×10000 | 31 bp |

以上仅是固定名义价值的代理算例。真实目标必须根据实际成交量、入场均价、费率、退出费率、已付费用和剩余票面权益重新求解。

#### 6.4 部分成交目标位移

在同一简化成本比例下：

| 成交比例 | 名义仓位 | 完成整张票翻倍所需位移 |
| --- | --- | --- |
| 100% | 800 | 136.00 bp |
| 80% | 640 | 167.25 bp |
| 50% | 400 | 261.00 bp |
| 30% | 240 | 427.67 bp |

因此不再使用固定 80% 继续规则。

### 7. 账户隔离与一轮规则

#### 7.1 专用子账户

复利和小额实盘只允许使用专用 Binance 子账户。API 不得拥有提现权限或自动资金划转能力。启动必须断言：

```text
margin_mode == ISOLATED
multi_assets_margin == false
portfolio_margin == false
auto_add_margin == false
position_mode == ONE_WAY
no_existing_position
no_existing_entry_order
no_unknown_algo_order
wallet_balance within approved_range
```

任一断言失败，进入 BLOCKED。账户模式和权限无法通过 API/管理面确认时，不得启动。

#### 7.2 RoundState

- IOC 零成交：不计已成交交易，但 MarketEpisode 被消费；本轮保持未使用票状态，可等待新的 episode。

- 首次非零成交：has_nonzero_fill=true，本轮不得再接受第二个 EntryIntent。

- 退出过程中只能计算 estimated_ticket_equity_if_flat；该值用于风险和进度估计，不得写入 final_realized_ticket_equity，不得触发轮次结算。

- PositionClosureProtocol 产生最终 POSITION_FLAT 后，写入 final_realized_ticket_equity，再判定 ROUND_SUCCESS 或 ROUND_FAILED；两者均持久化并进入 LOCKED。

### 8. 仓位与强平缓冲

#### 8.1 仓位计算

```text
usable_margin = max(0, ticket_equity - required_reserve)
raw_notional = usable_margin * approved_leverage
quantity = floor_to_step(raw_notional / reference_price)
```

必须读取并冻结：tickSize、stepSize、minQty、maxQty、minNotional、当前最大杠杆和 leverage bracket。数量和价格使用 Decimal，不使用二进制 float。

#### 8.2 强平缓冲门

做多：

```text
liquidation_buffer_bps =
(initial_stop_price - liquidation_price) / entry_price * 10_000

required_liquidation_buffer_bps =
stop_trigger_to_fill_stress_bps
+ mark_contract_divergence_stress_bps
+ fixed_liquidation_safety_bps
```

必须满足：

liquidation_buffer_bps >= required_liquidation_buffer_bps

输入必须包括：liquidation_price、source_ts、leverage_bracket_id、maintenance_margin_rate、isolated_wallet、mark_price、position_qty。字段过期、仓位变化或档位变化后立即重算。门失败时允许降低仓位或杠杆，但必须执行 8.3 的完整 ReSizingRevalidationPipeline；任一门失败则拒绝开仓。禁止追加保证金。

各 stress 参数为 BASELINE，必须经 F1 校准。

#### 8.3 ReSizingRevalidationPipeline

以下任一输入变化时必须从头重跑：leverage、requested_quantity、actual_usable_margin、fee_reserve、expected_cost、entry_price、instrument_specification、liquidation_bracket。

```text
1. account and margin mode assertions
2. instrument precision and minimum filters
3. usable margin calculation
4. quantity calculation and rounding
5. expected entry notional
6. estimated fees and reserve sufficiency
7. liquidation price and liquidation buffer
8. initial stop validity
9. required_target_bps
10. max_target_bps_allowed_for_event
11. reward/risk and cost gate
12. EntryIntent fields and expiry refresh
13. final pre-submit quote/spread/freshness check
```

只有 all_entry_gates_passed=true 才能继续。通过后生成新的 intent_revision、effective_config_snapshot 和 sizing_snapshot；market_episode_id 不变。任一门失败执行 REJECT_ENTRY，禁止沿用旧 target_price、requested_quantity、成本、max_entry_price 或旧 EntryIntent。

### 9. 事件定义

#### 9.1 CanonicalKeyLevel

V1.3.4 首轮只允许三种来源分别研究：rolling_low_1m、rolling_low_5m、range_low。每个来源只能使用当时已经完成的数据，不允许右侧确认。

同一标的同时存在多个候选低点时：

- 将价格距离小于 key_level_merge_tolerance_bps 的候选归为一组；

- 按 priority_rank 升序选择；

- 同优先级选择 formed_at_ns 最早者；

- 再相同则选择稳定哈希最小者；

- 其他候选保留为 member_key_level_ids，不生成第二个 EntryIntent。

key_level_merge_tolerance_bps 和来源优先级为 BASELINE，必须写入实验 Manifest。

#### 9.2 Sweep、Reclaim、Hold

| 对象 | FROZEN 结构 | BASELINE 参数 |
| --- | --- | --- |
| sweep | Trade/Contract Price 首次低于 canonical level | 深度 2-25bp |
| reclaim | sweep 后参考价重新 >= level + reclaim_buffer | buffer 0-3bp；3-60 秒 |
| hold | reclaim 后连续窗口不低于 level - failure_buffer | 2-10 秒 |
| invalidation | 超时、重破失效价或数据不可用 | 具体阈值配置化 |

历史 H1/H2 的参考价为 Contract/Trade；F1 才能使用可执行 Quote。研究和实盘不得在同一字段中混用。

#### 9.3 MarketEpisode 身份、消费与 re-arm

```text
market_episode_id = hash(
  venue,
  instrument,
  canonical_key_level_id,
  sweep_episode_start_ns
)
```

market_episode_id不包含策略版本。

同一 canonical level 下，首次跌破开始 episode。episode 在以下任一条件成立时结束：成功生成 hold、结构失效、达到 max_episode_duration_seconds。同一 episode 内的二次跌破/收回只更新最深扫动，不生成新 episode。

已提交 EntryIntent 后，episode 标记 consumed=true，无论零成交、取消或失败均不得重试。

新的 episode 必须同时满足：前一 episode 已结束；距离前一 sweep_end_ns 不少于 min_episode_gap_seconds；价格已连续 rearm_above_level_seconds 位于 level 之上后再次从上向下穿越；关键位未过期。上述参数为 BASELINE。

#### 9.4 触发门控

| 门 | V1.3.4 定义 | 数据层级 |
| --- | --- | --- |
| G0 Data | 时间戳单调、无未处理缺口、数据年龄通过 | H1+ |
| G1 Context | 由预注册 context 函数输出 ALLOW_LONG | H1+ |
| G2 Structure | sweep→reclaim→hold 顺序成立 | H1+ |
| G3 Price | 1s/5s 价格速度规则通过，且无新结构低点 | H1+ |
| G4 Flow | 逐笔主动买卖差规则通过 | 仅 H2/F1 变体 |
| G5 Cost/Execution | H3 通过主成本情景；F1 通过 Quote/age/slippage 门 | H3/F1 |
| G6 Reachability | required_target_bps <= max_target_bps_allowed_for_event | H3/F1 |

V1_PRICE不含 G4；V1_FLOW含 G4。二者是注册的策略变体，不允许在实盘中临时增加 G4 后仍引用 V1_PRICE 历史结果。

max_target_bps_allowed_for_event为 RESEARCH；阶段 2/3 必须给出目标可达性分布和预注册阈值。

#### 9.5 intent_id

```text
intent_id = hash(market_episode_id, strategy_version, intent_sequence)
```

消费依据 market_episode_id。策略版本变化不得重新交易同一个 episode。

### 10. EntryIntent 与部分成交

#### 10.1 EntryIntent

历史和前向字段必须分离。reference_ask在历史中为 NULL。

#### 10.2 IOC 开仓

- 使用带 max_entry_price 的 LIMIT IOC（BASELINE）。

- 发送前重新校验 Quote 年龄、点差和价格偏离；不通过则不下单并消费 episode。

- 未成交部分由 IOC 终止，不追价重发。

- ENTRY_ACK或执行状态未知时按 client order ID 查询，不能更换 ID 盲目重发。

#### 10.3 首次非零成交

首次收到非零成交事件时立即：

- 持久化 fill，并按 venue_trade_id 去重；

- 首次确认非零成交时创建 position_instance_id，并设置 position_revision=1；同一 IOC 的后续部分成交只递增 position_revision；

- 状态进入 PROTECTING；

- 请求创建交易所驻留灾难止损；

- 在保护确认前禁止任何策略性等待和第二开仓。

#### 10.4 IOC 结束后的可达性判断

按实际数量、实际均价和已付费用计算：实际保证金、剩余储备、初始止损、强平缓冲、净保本价、目标价、required_target_bps。

继续持仓必须同时满足：

```text
actual_qty >= exchange_min_qty
remaining_reserve >= required_reserve
liquidation_buffer_bps >= required_liquidation_buffer_bps
required_target_bps <= max_target_bps_allowed_for_event
```

失败则由 ExitCoordinator 立即退出。固定 minimum_effective_fill_ratio=80% 已 DEPRECATED。

## 第三篇　研究方法与评价指标

### 11. 研究顺序

- 数据质量与无未来泄漏。

- 宽松候选事件总体。

- 条件随机基线。

- H1 粗路径。

- H2 逐笔顺序和成交流。

- H3 成本、延迟、止损滑点和部分成交可达性压力。

- 锁定历史重放。

- F1 前向 holdout。

在阶段 2 未证明事件增量前，不开发算法 2、完整生产部署或自动复利。

Stage 2 可以在独立、预注册、append-only 的生命周期 Task 中运行范围受限的条件 H3
代理，用于研究时间退出、理论完全平仓和单仓占用。该代理必须携带
`H3_HISTORICAL_CONDITIONAL_LIFECYCLE`，不得改写 H1/H2 路径，不得宣称真实成交、真实
强平、真实净收益或 Stage 3 PASS。

### 12. 路径引擎与标签

#### 12.1 离散事件顺序

统一回放引擎按以下顺序处理：

- exchange_event_ts；

- 同时间使用交易所序列/Trade ID；

- 仍无法排序时标记 AMBIGUOUS；

- H1 同秒同时触及不利和有利边界时，主结果按不利先发生，另报告乐观上界；

- 状态变更只在当前事件处理完成后生效。

移动保护是路径依赖规则，必须逐事件更新状态，不得仅比较静态 T_target 与 T_stop。

#### 12.2 标签层级

| 标签/事件 | 含义 |
| --- | --- |
| TARGET_TOUCHED | 参考路径触及目标阈值 |
| STOP_TRIGGERED | 当前保护/初始止损被触发 |
| TARGET_FIRST | 在当前路径规则下目标先于停止事件 |
| STOP_FIRST | 停止事件先于目标触及 |
| EXPIRED | 最大持仓时间结束 |
| AMBIGUOUS | 数据粒度无法确定顺序 |
| TARGET_EXIT_SUBMITTED | ExitCoordinator 已提交目标退出 |
| TARGET_EXIT_PARTIAL | 目标退出部分成交 |
| POSITION_FLAT | 零数量确认有效、全部相关 entry/exit/algo 订单确定终态、无 UNKNOWN、无新 fill、无可触发残余订单 |
| ROUND_SUCCESS | POSITION_FLAT 后 final_realized_ticket_equity 达标 |
| ROUND_FAILED | POSITION_FLAT 后 final_realized_ticket_equity 未达标或票失败 |

TARGET_TOUCHED/TARGET_FIRST 不能替代 ROUND_SUCCESS。

#### 12.3 历史与实盘触发分离

H1/H2/H3 使用 Contract Price/Trade 路径。F1 的灾难止损可使用配置的 workingType。若 F1 使用 MARK_PRICE，则它属于执行契约，不得把 H2 Contract Price 标签当作相同策略的精确执行标签；报告必须并列展示 Contract proxy 与实际 Algo 结果。

### 13. 条件随机基线与事件聚类

#### 13.1 基线匹配

预注册匹配变量：标的、年份/季度、1h 趋势状态、1m 波动分位、时段、距关键位距离。匹配失败时按预注册层级依次放宽，禁止在看到结果后选择最有利匹配方案。

#### 13.2 cluster_id

同一大行情中的相关 episode 使用 cluster_id聚合。BASELINE：同标的、同方向、时间间隔小于 cluster_gap_minutes 且共享同一高周期状态段的 episode 归入一簇。主置信区间以簇为重采样单位。

#### 13.3 数据切分

- 历史开发和验证采用滚动时间切分。

- purge >= 最大特征回看 + 最大 episode/持仓窗口。

- 验证期只允许接受、拒绝或不确定；修改规则形成新实验。

- 已经存在并可能被观察的历史后段只叫 LOCKED_HISTORICAL_REPLAY。

- 真正未知数据从 V1.3.4 代码、规则和配置哈希冻结后的下一条数据开始，称 FORWARD_HOLDOUT。

### 14. 成本与 H3

H3 至少预注册一个主情景和多个压力情景：手续费、入场滑点、退出滑点、止损尾部滑点、延迟。所有值是 scenario，不是历史真值。

#### 14.2 Stage 2 条件生命周期合同

Stage 2 Plan v1.3 的生命周期研究固定：

- 票面 10 USDT、保留 2 USDT、使用保证金 8 USDT、研究杠杆上限 100x；
- 最大生命周期 7 个完整 UTC 日；未完全平仓为右删失，不得当作胜负；
- landmark 为 5/8/15/25/60 分钟，8 分钟唯一 Primary；4h/24h/72h/7d 只报告存活；
- `NOT_ACTIVATED` 表示主 H3 情景下历史净 MFE 从未达到使用保证金的 20%；
- Primary near-zero band 为当前 `scenario_net_exitable_pnl` 占使用保证金的
  `[-5%, +5%]`，`±2%` 与 `±10%` 为强制敏感性报告；
- 主情景为往返费用 9bp、总情景滑点 2bp、延迟 250ms、100% 代理初始成交，并使用已
  发布的历史资金费事实；1.5x/2x 成本和 80%/50% 初始成交为压力情景；
- 资金费必须分轨：Primary 使用实际结算时点的有符号历史资金费；Stress 将正向支付放大
  到 1.5x/2x，负向资金费收入不得放大，并另报取消负向收入的保守情景；Stress 不得替代
  缺失的 Primary 历史事实；
- Stage 2 H3 价格路径使用 `CONTRACT_PRICE_H3_PROXY` 与 canonical Trades；不得描述为
  历史 Mark Price，F1/live `workingType` 仍由 U-001 和前向验证决定；
- T2 的 20bp crossing 只作辅助 First Passage，不触发继续持有策略的目标退出；目标退出
  发生在成本和累计资金费后的票面权益首次达到 20U。主成本、零累计资金费时约为 136bp，
  实际门槛必须随累计资金费动态重算，不得死写 136bp；
- `THEORETICAL_FULLY_FLAT` 只表示情景代理数量归零；`POSITION_FLAT` 仍保留给真实
  PositionClosureProtocol；
- `SCENARIO_LIQUIDATION_BOUNDARY_CROSSED` 只表示冻结情景边界被穿越，不是历史真实强平；
- Stage 2 的该边界固定为 Contract Price/Trade 代理路径上的净保证金耗尽：
  `scenario_net_pnl <= -8U`，等价于10U票面权益降至2U保留资金；不读取历史 Mark 或
  exchange leverage bracket，也不得描述为 Binance 真实强平；
- Primary 有任一 7 日仍未平仓样本时，结论必须是
  `INCONCLUSIVE_RIGHT_CENSORING`。

Primary 比较同一事件在 8 分钟条件成立后的两个预注册策略：立即情景退出，或继续持有至
目标、保护、结构、止损、理论完全平仓或右删失。正式支持继续持有必须同时满足：

```text
cluster_count >= 200
and ticket_equity_per_calendar_day_delta_ci_lower > 0
and conditional_ticket_double_probability_delta_ci_lower > 0
and primary_probability_ci_half_width_pp <= 7.5
and main_scenario_liquidation_or_reserve_breach_count == 0
and cost_1_5x_ticket_value_delta >= 0
and cost_1_5x_ticket_double_probability_delta >= 0
and primary_max_horizon_censored_count == 0
```

Target First 只作辅助指标。BTC 与 ETH 必须分开；单仓占用必须通过同一事件时间线的配对
策略回放计入，不能把长期占仓期间错过的新 episode 当作可同时交易。

#### 14.1 条件与无条件单轮概率

```text
conditional_round_success_probability = P(ROUND_SUCCESS | assumed_entry_fill_scenario, assumed_partial_fill_scenario, cost_scenario_id, latency_scenario_id)
```

H3 只能报告上述条件概率，不得输出 unconditional_live_round_success_probability。F1 获得真实执行分布后，才可估计：P_live(ROUND_SUCCESS) = Σ_s P(ROUND_SUCCESS | execution_scenario=s) × P_live(execution_scenario=s)。F1 样本不足时，只报告分情景条件概率、执行情景经验分布和不确定性区间。

报告必须输出：

- scenario_net_expectancy；

- Target/Stop/Expired/Ambiguous 分布；

- conditional_round_success_probability，并完整列出其成交、部分成交、成本与延迟条件；

- 事件频率和完成一轮的日历等待时间；

- 成本 1x/1.5x/2x 和延迟压力；

- 参数邻域，而非最好单点。

### 15. 研究门槛

BASELINE 通过线必须同时满足：

```text
independent_cluster_count >= 200
and primary_metric_ci_half_width <= 7.5 percentage points
```

此外必须：

- 主假设、主标的、主标签、主成本情景预注册；

- 所有尝试的事件版本进入台账；

- 主情景 scenario_net_expectancy > 0 且区间下界达到预注册标准；

- 2x 成本情景的数值失败线预注册，禁止使用“没有灾难性反转”等词；

- 多时期方向一致的具体阈值预注册；

- 报告每年独立簇数和事件等待时间；

- 事件优势必须能映射到“单轮一笔”的 H3 条件 ROUND 代理结果；不得将其解释为 F1 无条件实盘概率。

参数取值仍属 BASELINE/RESEARCH；通过线修改需新实验。

### 16. 防过拟合协议

- 不在验证失败后追加过滤器并继续使用同一验证结论。

- 不通过改 strategy_version 重置事件消费。

- 不只报告最佳参数；必须输出完整参数地形和失败实验。

- 一次实验只改变一个主要问题。

- H3 的多个成本情景不得挑选最有利者作为主结果。

- FORWARD_HOLDOUT中途不得用于调参。

- 研究日志记录探索路径、阈值数量和人工判断。

## 第四篇　执行契约与状态机

### 17. Binance 当前能力决策

截至 2026-07-11，官方 USDⓈ-M 文档提供 Algo 条件订单的新建、查询、取消、开放订单查询和 ALGO_UPDATE事件；新建支持 STOP_MARKET 等类型、workingType、priceProtect、closePosition、clientAlgoId。quantity不能与closePosition=true同时提交，reduceOnly不能与closePosition=true同时提交，也不能在 Hedge Mode 提交。官方 Algo 接口目录未提供未触发条件订单的修改接口，因此 V1.3.4 继续将条件单视为不可变。[B01-B05]

#### 17.1 默认灾难止损

| 参数 | V1.3.4 |
| --- | --- |
| algoType | CONDITIONAL |
| type | STOP_MARKET |
| side | SELL |
| positionSide | BOTH（One-way Mode） |
| closePosition | true |
| quantity | 不提交 |
| reduceOnly | 不提交 |
| workingType | MARK_PRICE（BASELINE，必须通过 Execution Spike/F1） |
| priceProtect | false（FROZEN 默认，避免价差门阻止灾难触发） |
| clientAlgoId | 稳定幂等 ID |

若 Execution Spike 证明某参数组合或账户环境不支持，live 保持 BLOCKED，必须形成 ADR；不得由 Codex 自行替换。

#### 17.2 保护架构

不可变交易所驻留灾难止损 + 本地确定性主动保护退出。

- 灾难止损创建后不承担阶梯移动职责。

- 激活线、阶梯保护、结构失效、时间止损和目标由本地纯函数产生 ExitDecision。

- 所有退出由 ExitCoordinator 执行。

- 灾难止损在交易所确认仓位为 0 前保持有效。

- POSITION_QTY_ZERO_CONFIRMED 成立后，由 ExitCoordinator 进入 RESIDUAL_ORDER_CLEANUP，取消并确认与当前 position_instance_id 相关的残余 Algo 保护单、普通开仓单及全部退出订单腿进入确定终态；仅在无 UNKNOWN、无可再次触发订单、无迟到增仓成交和无残余仓位时产生最终 POSITION_FLAT。

- 禁止先撤灾难止损再创建保护。

- 双保护切换为未来增强，状态 BLOCKED_BY_FORWARD_VALIDATION。

### 18. protection_sufficient

使用 closePosition=true 时，不比较保护数量。必须同时满足：

```text
algo exists
algo_status in configured_active_statuses
instrument == current_instrument
side == SELL
position_side == BOTH
working_type == configured_working_type
trigger_price is valid and rounded
a linked_position_instance_id == active_position_instance_id
algo not expired/rejected/canceled
liquidation safety gate passes
query result and ALGO_UPDATE do not conflict
```

私有流过期或查询冲突时进入 RECONCILING；无法确认保护且仓位>0时进入 EMERGENCY_EXIT。有效状态集合由 Execution Spike 根据官方事件枚举冻结。

### 19. ExitCoordinator

#### 19.1 核心对象

- position_instance_id：一次完整仓位生命周期的稳定 ID；首次确认非零成交时创建，持续到 POSITION_FLAT 最终事件成立后关闭。POSITION_QTY_ZERO_CONFIRMED 仅表示数量为零，不结束实例。

- position_revision：同一仓位实例内事实快照的单调版本。venue_position_qty、avg_entry_price、accumulated_entry_fee、保护状态、liquidation_price、exit_owner 或相关 venue facts 变化时递增；创建 active_exit_epoch 时按 ExitEpochBootstrapTransaction 原子递增一次。单纯创建同一 epoch 的后续订单腿不递增，订单腿版本使用 exit_epoch_revision。

- exit_epoch：属于一个 position_instance_id 的唯一退出会计周期。创建时与 position_revision 在同一事务内提交，created_against_position_revision 必须等于事务提交后的 revision；退出期间仓位事实变化时保持同一 epoch，进入 RECONCILING 并按最新 venue qty 更新剩余退出量。

- exit_owner：LOCAL_TARGET_EXIT / LOCAL_RISK_EXIT / LOCAL_EMERGENCY_EXIT / VENUE_DISASTER_STOP / RECOVERY_EXIT。

- ExitBootstrapMode：LOCAL_SUBMISSION 表示本地准备提交新的退出订单；VENUE_OBSERVED 表示接管交易所已经存在、已触发或已产生的外部退出事实。前者 requires_local_submission=true，后者=false。

- last_confirmed_venue_qty：带 source_ts、received_monotonic_ns、snapshot_id 和 position_revision 的交易所数量事实。ExitEpochBootstrapTransaction 使用该事实填充 initial_venue_qty。

- position_version：DEPRECATED，仅作为迁移读取字段；迁移时必须映射为 position_instance_id 与 position_revision，不得继续承载双重语义。

#### 19.1.1 ExitEpochBootstrapTransaction

ExitBootstrapMode = {LOCAL_SUBMISSION, VENUE_OBSERVED}。LOCAL_SUBMISSION 输入：expected_position_instance_id、expected_position_revision、current_confirmed_venue_qty、requested_exit_reason、requested_exit_owner、first_leg_type、first_leg_order_type、first_leg_requested_qty、first_leg_limit_price（nullable）。VENUE_OBSERVED 输入：expected_position_instance_id、expected_position_revision、latest_confirmed_venue_qty、observed_algo_id/venue_order_id、observed status、observed quantities/fees/timestamps，以及已有 active_exit_epoch（nullable）。

```text
ExitBootstrapMode = {LOCAL_SUBMISSION, VENUE_OBSERVED}

LOCAL_SUBMISSION — BEGIN ATOMIC TRANSACTION
assert stored_position_instance_id == expected_position_instance_id
assert stored_position_revision == expected_position_revision
now_wall_ns = local_utc_wall_clock_ns()
new_position_revision = expected_position_revision + 1
new_exit_epoch = next_exit_epoch(position_instance_id)
new_exit_order_leg_id = next_exit_order_leg_id(new_exit_epoch)
new_client_order_id = deterministic_client_order_id(new_exit_epoch, 1)
PositionState.position_instance_id = expected_position_instance_id
PositionState.position_revision = new_position_revision
PositionState.active_exit_epoch = new_exit_epoch
PositionState.exit_owner = requested_exit_owner
PositionState.updated_at_ns = now_wall_ns
ExitEpoch.exit_epoch = new_exit_epoch
ExitEpoch.position_instance_id = expected_position_instance_id
ExitEpoch.created_against_position_revision = new_position_revision
ExitEpoch.exit_epoch_revision = 1
ExitEpoch.bootstrap_mode = LOCAL_SUBMISSION
ExitEpoch.exit_owner = requested_exit_owner
ExitEpoch.previous_exit_owner = NULL
ExitEpoch.owner_transition_reason = NULL
ExitEpoch.initial_venue_qty = current_confirmed_venue_qty
ExitEpoch.current_remaining_qty = current_confirmed_venue_qty
ExitEpoch.realized_exit_qty = 0
ExitEpoch.realized_exit_value = 0
ExitEpoch.realized_exit_fee = 0
ExitEpoch.status = ACTIVE
ExitEpoch.created_at_ns = now_wall_ns
ExitEpoch.updated_at_ns = now_wall_ns
ExitOrderLeg.exit_order_leg_id = new_exit_order_leg_id
ExitOrderLeg.exit_epoch = new_exit_epoch
ExitOrderLeg.position_instance_id = expected_position_instance_id
ExitOrderLeg.leg_sequence = 1
ExitOrderLeg.leg_type = first_leg_type
ExitOrderLeg.exit_owner = requested_exit_owner
ExitOrderLeg.bootstrap_mode = LOCAL_SUBMISSION
ExitOrderLeg.order_origin = LOCAL
ExitOrderLeg.requires_local_submission = true
ExitOrderLeg.client_order_id_source = LOCAL
ExitOrderLeg.client_order_id = new_client_order_id
ExitOrderLeg.venue_order_id = NULL
ExitOrderLeg.algo_id = NULL
ExitOrderLeg.requested_qty = first_leg_requested_qty
ExitOrderLeg.submitted_qty = 0
ExitOrderLeg.filled_qty = 0
ExitOrderLeg.remaining_qty = first_leg_requested_qty
ExitOrderLeg.order_type = first_leg_order_type
ExitOrderLeg.limit_price = first_leg_limit_price
ExitOrderLeg.reduce_only = true
ExitOrderLeg.status = PENDING_SUBMIT
ExitOrderLeg.created_at_ns = now_wall_ns
ExitOrderLeg.submitted_at_ns = NULL
ExitOrderLeg.last_update_ns = now_wall_ns
ExitOrderLeg.terminal_at_ns = NULL
ExitOrderLeg.venue_event_ts_ns = NULL
ExitOrderLeg.venue_transaction_ts_ns = NULL
ExitOrderLeg.received_monotonic_ns = NULL
ExitOrderLeg.replacement_of_leg_id = NULL
ExitOrderLeg.fallback_reason = NULL
if first_leg_type is LOCAL_ACTIVE:
  ActiveLocalExitLeg.exit_epoch = new_exit_epoch
  ActiveLocalExitLeg.exit_order_leg_id = new_exit_order_leg_id
  ActiveLocalExitLeg.created_at_ns = now_wall_ns
COMMIT

VENUE_OBSERVED — BEGIN ATOMIC TRANSACTION
assert stored_position_instance_id == expected_position_instance_id
assert stored_position_revision == expected_position_revision
assert observed_algo_id IS NOT NULL or observed_venue_order_id IS NOT NULL
now_wall_ns = local_utc_wall_clock_ns()
new_position_revision = expected_position_revision + 1
if active_exit_epoch IS NULL:
  target_exit_epoch = next_exit_epoch(position_instance_id)
  target_exit_epoch_revision = 1
  create ExitEpoch with bootstrap_mode=VENUE_OBSERVED,
    created_against_position_revision=new_position_revision,
    exit_owner=VENUE_DISASTER_STOP,
    previous_exit_owner=NULL,
    owner_transition_reason=VENUE_STOP_OBSERVED,
    initial_venue_qty=latest_confirmed_venue_qty,
    current_remaining_qty=latest_confirmed_venue_qty,
    realized_exit_qty=observed_filled_qty,
    realized_exit_value=observed_filled_value,
    realized_exit_fee=observed_fee,
    status=RECONCILING,
    created_at_ns=now_wall_ns, updated_at_ns=now_wall_ns
else:
  target_exit_epoch = active_exit_epoch
  target_exit_epoch_revision = stored_exit_epoch_revision + 1
  update existing ExitEpoch: exit_epoch_revision=target_exit_epoch_revision,
    previous_exit_owner=current_exit_owner,
    exit_owner=VENUE_DISASTER_STOP,
    owner_transition_reason=VENUE_STOP_OBSERVED,
    current_remaining_qty=latest_confirmed_venue_qty,
    realized aggregates += newly observed fills/fees,
    status=RECONCILING, updated_at_ns=now_wall_ns
PositionState.position_revision = new_position_revision
PositionState.active_exit_epoch = target_exit_epoch
PositionState.exit_owner = VENUE_DISASTER_STOP
PositionState.updated_at_ns = now_wall_ns
upsert one VENUE_DISASTER_STOP ExitOrderLeg by (algo_id, venue_order_id):
  exit_order_leg_id = derived_internal_leg_id
  exit_epoch = target_exit_epoch
  position_instance_id = expected_position_instance_id
  leg_sequence = next_leg_sequence
  leg_type = VENUE_DISASTER_STOP
  exit_owner = VENUE_DISASTER_STOP
  bootstrap_mode = VENUE_OBSERVED
  order_origin = VENUE
  requires_local_submission = false
  client_order_id_source = VENUE if venue_client_order_id exists else NONE
  client_order_id = venue_client_order_id or NULL
  venue_order_id = observed_venue_order_id
  algo_id = observed_algo_id
  requested_qty = observed_requested_qty or NULL
  submitted_qty = observed_submitted_qty
  filled_qty = observed_filled_qty
  remaining_qty = max(0, observed_submitted_qty - observed_filled_qty)
  order_type = observed_order_type
  limit_price = observed_limit_price or NULL
  reduce_only = observed_reduce_only
  status = mapped_observed_status
  created_at_ns = observed_created_at_ns or now_wall_ns
  submitted_at_ns = observed_submitted_at_ns or NULL
  last_update_ns = observed_last_update_ns or now_wall_ns
  terminal_at_ns = observed_terminal_at_ns or NULL
  venue_event_ts_ns = observed_venue_event_ts_ns or NULL
  venue_transaction_ts_ns = observed_venue_transaction_ts_ns or NULL
  received_monotonic_ns = observed_receive_monotonic_ns or NULL
  replacement_of_leg_id = NULL
  fallback_reason = NULL
COMMIT
```

LOCAL_SUBMISSION 只有事务完整提交后，才允许读取已持久化 client_order_id 并发送交易所订单；恢复时 PENDING_SUBMIT 首腿只使用同一 client_order_id 查询或在确认交易所不存在后同 ID 重发。VENUE_OBSERVED 只登记交易所事实，严禁调用新建退出订单接口；重复事实按 venue_order_id/algo_id 去重。任一必填字段缺失时事务失败，记录 DATA_CONTRACT_INCOMPLETE；VENUE_OBSERVED 同时缺少 venue_order_id 与 algo_id 时进入 RECONCILING/INCIDENT_LOCK。ACTIVE ExitEpoch 不存在 ExitOrderLeg 属于数据损坏，reason=ACTIVE_EXIT_EPOCH_WITHOUT_LEG，进入 INCIDENT_LOCK 与 RECOVERING。

LOCAL_SUBMISSION 发送顺序冻结为：完整原子持久化 → 读取持久化 client_order_id → 发送交易所订单 → 更新订单腿状态。VENUE_OBSERVED 顺序为：接收/查询 venue fact → 原子登记 epoch/leg 或归入既有 epoch → 进入 RECONCILING；不得发送同一退出。金额和数量初始值使用 0；不存在/不适用的标识使用 NULL，不得使用空字符串或 0 伪装 venue_order_id/algo_id。created_at_ns、updated_at_ns、last_update_ns 使用本地 UTC wall clock；交易所事件时间分别写入 venue_event_ts_ns/venue_transaction_ts_ns；间隔和新鲜度使用 received_monotonic_ns。

- exit_owner 在同一 epoch 内切换时保持 exit_epoch 不变，position_revision 原子递增并记录 previous_exit_owner 与 owner_transition_reason。灾难止损事实到达且已有 epoch 时，使用 VENUE_OBSERVED 归入原 epoch；不得创建新 epoch 或本地重复提交。

#### 19.2 单一所有权

- 策略回调只能提交 ExitDecision，不能直接下单。

- 每个 position_instance_id 同时最多一个 active exit_epoch。

- 原退出订单为 NEW、PARTIALLY_FILLED 或 UNKNOWN 时，不创建新 epoch。

- 状态 UNKNOWN 时按同一 client ID 查询；禁止换 ID 盲重发。

- 重复 fill 以 venue_trade_id 去重；累计成交量只增不减。

- 旧 position_revision 的迟到事件不得覆盖新 revision。上一实例已确认 flat 后出现新的开仓成交时，不复用旧 instance；进入 RECOVERING/RECONCILING，并创建异常 position_instance_id。

#### 19.3 主动退出订单

| 原因 | 第一动作 | 后续动作 |
| --- | --- | --- |
| TARGET/TIME/STRUCTURE/PROTECTION | 在已提交的 exit_epoch 内创建 LOCAL_LIMIT_IOC ExitOrderLeg；使用当前 Bid 与最大滑点包络 | 仅当前一腿确定终态、latest_venue_qty>0 且无其他本地活动腿时，在同一 epoch 创建 LOCAL_MARKET_FALLBACK |
| EMERGENCY | 在同一 exit_epoch 创建 LOCAL_EMERGENCY_MARKET；若尚无 epoch，先完成原子创建事务 | 腿状态 UNKNOWN 时查询同一 client_order_id；禁止新腿和新 epoch |
| Quote stale/无可用 Bid | 在同一 exit_epoch 创建 LOCAL_EMERGENCY_MARKET；若尚无 epoch，先完成原子创建事务 | 同上 |
| 原生灾难止损触发 | 使用 VENUE_OBSERVED：归入已有 epoch，或创建接管/会计 epoch 与 VENUE_DISASTER_STOP 腿；不发送新订单 | 进入 RECONCILING；按 venue_order_id/algo_id 去重；禁止第二本地主动非终态腿 |

ExitIntent 只表达策略或风控请求，不对应具体交易所订单；ExitEpoch 表示完整退出会计周期；具体交易所订单统一建模为 ExitOrderLeg。LOCAL_SUBMISSION 退出使用本地原子持久化后提交。未触发灾难止损继续由 AlgoProtectionState 管理；进入 TRIGGERING/TRIGGERED 或查询到实际外部订单事实后，必须使用 VENUE_OBSERVED：有 active epoch 时归入原 epoch，无 active epoch 时创建接管与会计用 epoch/venue leg，均不得再次发送灾难止损订单。

```text
ExitOrderLeg states
NONTERMINAL_LOCAL_ACTIVE_STATES = {PENDING_SUBMIT, SUBMITTING, NEW, ACKED, PARTIALLY_FILLED, UNKNOWN}
TERMINAL_STATES = {FILLED, CANCELED, REJECTED, EXPIRED}
- LIMIT_IOC -> MARKET fallback reuses the same exit_epoch.
- UNKNOWN blocks every new local leg; changing client_order_id is forbidden.
- Every leg fill aggregates into ExitEpoch.realized_exit_qty/value/fee/current_remaining_qty.
- A local active leg is registered in ActiveLocalExitLeg; exit_epoch is its PRIMARY KEY.
```

“禁止第三个退出”统一解释为：禁止第三个独立 exit_epoch；禁止同一 exit_epoch 同时存在第二个本地主动非终态 ExitOrderLeg；允许前一主动腿确定终态后，使用 ExitLegCreationTransaction 在同一 epoch 创建顺序回退腿。

19.3.1 ExitLegCreationTransaction

适用范围：LIMIT IOC→MARKET fallback、风险退出升级、残仓关闭与恢复关闭。事务前置条件原子校验：stored_exit_epoch_revision == expected_exit_epoch_revision；ExitEpoch.status == ACTIVE；latest_confirmed_venue_qty > 0；previous_local_leg_is_terminal == true；no_nonterminal_local_active_leg == true；no_unknown_local_leg == true。灾难止损已明确触发时，先完成竞态消解。

BEGIN ATOMIC TRANSACTION
assert stored_exit_epoch_revision == expected_exit_epoch_revision
assert ExitEpoch.status == ACTIVE
assert latest_confirmed_venue_qty > 0
assert previous_local_leg_is_terminal == true
assert no_unknown_local_leg == true
assert no row in ActiveLocalExitLeg for exit_epoch
now_wall_ns = local_utc_wall_clock_ns()
new_exit_epoch_revision = expected_exit_epoch_revision + 1
new_leg_sequence = max(existing_leg_sequence) + 1
new_exit_order_leg_id = next_exit_order_leg_id(exit_epoch)
new_client_order_id = deterministic_client_order_id(exit_epoch, new_leg_sequence)
ExitEpoch.exit_epoch_revision = new_exit_epoch_revision
ExitEpoch.current_remaining_qty = latest_confirmed_venue_qty
ExitEpoch.updated_at_ns = now_wall_ns
ExitOrderLeg.exit_order_leg_id = new_exit_order_leg_id
ExitOrderLeg.exit_epoch = exit_epoch
ExitOrderLeg.position_instance_id = position_instance_id
ExitOrderLeg.leg_sequence = new_leg_sequence
ExitOrderLeg.leg_type = requested_leg_type
ExitOrderLeg.exit_owner = current_exit_owner
ExitOrderLeg.bootstrap_mode = LOCAL_SUBMISSION
ExitOrderLeg.order_origin = LOCAL
ExitOrderLeg.requires_local_submission = true
ExitOrderLeg.client_order_id_source = LOCAL
ExitOrderLeg.client_order_id = new_client_order_id
ExitOrderLeg.venue_order_id = NULL
ExitOrderLeg.algo_id = NULL
ExitOrderLeg.requested_qty = latest_confirmed_venue_qty
ExitOrderLeg.submitted_qty = 0
ExitOrderLeg.filled_qty = 0
ExitOrderLeg.remaining_qty = latest_confirmed_venue_qty
ExitOrderLeg.order_type = requested_order_type
ExitOrderLeg.limit_price = requested_limit_price or NULL
ExitOrderLeg.reduce_only = true
ExitOrderLeg.status = PENDING_SUBMIT
ExitOrderLeg.created_at_ns = now_wall_ns
ExitOrderLeg.submitted_at_ns = NULL
ExitOrderLeg.last_update_ns = now_wall_ns
ExitOrderLeg.terminal_at_ns = NULL
ExitOrderLeg.venue_event_ts_ns = NULL
ExitOrderLeg.venue_transaction_ts_ns = NULL
ExitOrderLeg.received_monotonic_ns = NULL
ExitOrderLeg.replacement_of_leg_id = previous_leg_id
ExitOrderLeg.fallback_reason = fallback_reason
ActiveLocalExitLeg.exit_epoch = exit_epoch
ActiveLocalExitLeg.exit_order_leg_id = new_exit_order_leg_id
ActiveLocalExitLeg.created_at_ns = now_wall_ns
COMMIT

数据库级并发约束采用独立 ActiveLocalExitLeg 表：exit_epoch 为 PRIMARY KEY，exit_order_leg_id 为 UNIQUE。前一活动腿进入确定终态与删除 ActiveLocalExitLeg、创建下一腿必须在同一事务中完成。乐观锁或唯一约束冲突时，不得创建订单腿、不得发送交易所订单；重新读取 epoch、订单腿和仓位事实并进入 RECONCILING。

事务提交后才允许发送交易所订单。下一腿 requested_qty 必须等于最新确认的 venue qty，不得沿用前一腿数量。前一腿 UNKNOWN、SUBMITTING、NEW、ACKED 或 PARTIALLY_FILLED 时，禁止创建 fallback、禁止换 client_order_id 重发、禁止创建新 exit_epoch。

#### 19.4 Exit Ownership and Race Resolution Table

| 当前退出所有者 | 灾难止损状态 | 本地主动 ExitOrderLeg 状态 | 交易所仓位 | 必须动作 |
| --- | --- | --- | --- | --- |
| NONE | TRIGGERED | NONE | >0 | 无 epoch：使用 VENUE_OBSERVED 原子登记接管 epoch 与已有灾难腿，不调用新建订单接口；有 epoch：归入原 epoch、更新 owner/revision；查询 actual order 与仓位。 |
| ACTIVE_EXIT | NEW/TRIGGERING | PARTIALLY_FILLED | >0 | 保持同一 exit_epoch 和当前本地主动腿；进入 RECONCILING；不得创建第二个本地主动非终态腿或新 epoch。 |
| ACTIVE_EXIT | TRIGGERED | PARTIALLY_FILLED | >0 | 灾难止损腿与主动腿成交均聚合到同一 ExitEpoch；以最新 venue facts 更新 remaining_qty；不得创建新 epoch。 |
| LOCAL_EMERGENCY_EXIT | TRIGGERED | UNKNOWN | >0 | 保持同一 exit_epoch；查询普通腿、Algo 与仓位；UNKNOWN 阻塞任何后续主动腿。 |
| 任意 | FINISHED | FILLED | 0 | 进入 ZERO_QTY_CONFIRMATION；双零快照通过后只产生 POSITION_QTY_ZERO_CONFIRMED，不直接宣告 flat。 |
| 任意 | 任意迟到事件 | 终态 | 0 confirmed | 若 POSITION_FLAT 已成立，仅更新订单腿终态、会计和审计；不得恢复持仓状态。 |
| 任意 | 任意 | 任意 | 负数或反向仓位 | INCIDENT_LOCK；按真实仓位创建异常实例并进入 RECOVERY_EXIT。 |

灾难止损已明确触发但仓位仍非零时，不盲目取消正在成交的主动 reduce-only 退出。只有交易所明确确认订单可安全取消且取消不会扩大剩余风险时才允许取消。任何取消失败或 UNKNOWN 均保持 RECONCILING，不得新建 exit_epoch。仓位归零后，取消所有仍可取消的残余退出/保护订单；取消结果 UNKNOWN 时不得宣布清理完成。

#### 19.5 REST 与私有流同时不可用

- 禁止新风险和盲目重复退出。

- 保持已确认的交易所灾难止损。

- 状态持久化为 EMERGENCY_EXIT，持续重连并告警。

- 只有在至少一个事实通道恢复后，才能查询仓位并决定是否发送主动退出。

- 不能以“理论仓位”猜测数量反复下单。

### 20. 状态机

#### 20.1 核心状态

IDLE, BLOCKED, CONTEXT_OK, ARMED, ENTRY_PENDING, PROTECTING, VALIDATING, PROTECTED, TARGET_EXIT_PENDING, EXIT_PENDING, RECONCILING, RECOVERING, COOLDOWN, LOCKED, EMERGENCY_EXIT

- EXIT_REVIEW是纯决策函数，不是持久状态。

- CLOSED 不使用。平仓闭环在 RECONCILING 内使用三个持久化子阶段：ZERO_QTY_CONFIRMATION、RESIDUAL_ORDER_CLEANUP、FINAL_FLAT_CONFIRMATION。POSITION_QTY_ZERO_CONFIRMED 与 POSITION_FLAT 是事件，不是顶层状态。

- PROTECTED包含利润扩张，不保留含义重叠的 EXPANDING。

#### 20.2 状态原则

| 状态 | 允许动作 | 禁止动作 |
| --- | --- | --- |
| IDLE | 评估 context | 下单 |
| BLOCKED | 健康检查、人工修复 | EntryIntent |
| CONTEXT_OK | 检测 key level | 下单 |
| ARMED | 更新 episode 和门控 | 第二 episode 并发下单 |
| ENTRY_PENDING | 处理 ACK/fill/cancel/query | 第二开仓 |
| PROTECTING | 创建/确认灾难止损或紧急退出 | 正常持仓等待 |
| VALIDATING | 更新路径、时间、结构 | 直接下退出单 |
| PROTECTED | 更新 MFE、保护决策、目标 | 直接下退出单 |
| TARGET_EXIT_PENDING | ExitCoordinator 管理目标退出 | 提前宣告成功 |
| EXIT_PENDING | ExitCoordinator 管理主动退出 | 新开仓 |
| RECONCILING | 按 reconcile_phase 查询事实；Stage A 确认零数量，Stage B 唯一执行残余清理，Stage C 只验证并产生 POSITION_FLAT | 产生新风险订单、Stage C执行常规清理、跳过Stage B或在UNKNOWN时宣告flat |
| RECOVERING | 重启恢复与保护验证 | 进入 IDLE 前开仓 |
| COOLDOWN | 等待冷却 | EntryIntent |
| LOCKED | 查询、撤残单、人工审计 | 自动解锁 |
| EMERGENCY_EXIT | 恢复事实通道、退出、告警 | 盲重发和开仓 |

#### 20.3 外部事件

必须覆盖：ENTRY_ACK, PARTIAL_FILL, FULL_FILL, ORDER_CANCEL_ACK, ORDER_REJECTED, ORDER_STATUS_UNKNOWN, ALGO_UPDATE, POSITION_SNAPSHOT, DUPLICATE_FILL, LATE_FILL, QUOTE_STALE, PRIVATE_STREAM_STALE, REST_UNAVAILABLE, PROCESS_RESTART, CIRCUIT_BREAKER_TRIGGERED。完整转换见附录 G。

### 21. 利润保护、时间与结构退出

#### 21.1 初始止损

初始止损使用结构失效位置加波动缓冲，并限制在 BASELINE 研究范围 15-35bp。它只有在强平缓冲门通过时才能开仓；15-35bp 本身不代表安全。

#### 21.2 激活与阶梯

BASELINE：净 MFE 20% 激活；50/70/85%阶梯。由于灾难止损不可变，所谓“锁定净 ROE”是本地主动退出阈值，正式名称为 estimated_protection_floor，不是成交保证。

激活状态粘滞：一旦达到激活，不因预计成本变化退回 VALIDATING。若 estimated_exit_net_pnl因点差扩大转负，ExitDecision 可立即触发，但不得降低既有风险约束。

#### 21.3 ExitDecision

纯函数输入：position snapshot、市场快照、成本估计、MFE/MAE、time_since_mfe、结构状态、配置。输出只能是：

- HOLD

- EXIT_TARGET

- EXIT_PROTECTION

- EXIT_TIME

- EXIT_STRUCTURE

- EXIT_EMERGENCY

失败动作均由 ExitCoordinator 执行。

#### 21.4 时间规则

5 分钟复核、8 分钟未激活退出、15/25 分钟停滞均为 BASELINE。阶段 2/3 根据 Time-to-Activation、Time-since-MFE 和条件期望决定。未验证前只能用于回放和联调，不进入 small-live。

### 22. 超时与 UNKNOWN

- -1006/-1007或响应超时表示执行状态未知，不能当作失败重发。[B06]

- entry_ack_timeout、algo_ack_timeout、reconcile_timeout为 BASELINE，不是服务保证。

- UNKNOWN 订单必须使用原 client ID 查询普通订单或 Algo 订单。

- 查询仍不可用：保持 RECONCILING/EMERGENCY_EXIT，不生成相同风险的新 ID。

- 用户流 listenKey 需要持续保活，过期/私有流 stale 立即禁止开仓并触发 REST 对账。[B07]

## 第五篇　工具链与工程规范

### 23. 工具链

| 层 | 工具/规则 |
| --- | --- |
| 数据 | Polars Lazy + Parquet，分区与数据质量标签 |
| 研究 | Python 3.12、Jupyter 仅展示，正式逻辑在 src |
| 回测 | NautilusTrader 或统一离散事件引擎；不得牺牲 V1.3.4 状态语义 |
| 执行 | BinanceExecutionPort抽象；Execution Spike 后选择 Nautilus 适配或官方接口薄适配器 |
| 配置 | Pydantic + YAML/JSON，有效配置快照 |
| 测试 | pytest + Hypothesis + replay + fault injection |
| 持久化 | SQLite/PostgreSQL 单机事务存储；append-only audit log |
| 代码质量 | uv、Ruff、mypy、CI |

若 Nautilus 当前适配器无法完整支持 Algo Service、ALGO_UPDATE 或恢复语义，实盘适配器必须使用 Binance 官方接口薄层；研究/策略纯函数不得因此改变。

### 24. 模块责任

```text
src/era100x/
  domain/           # 数据类、枚举、规则元数据
  data/             # 标准化、质量、聚合、Trades
  research/         # 事件、标签、基线、统计
  strategy/         # context/setup/trigger/ExitDecision 纯函数
  risk/             # sizing、liquidation gate、round
  execution/        # ExecutionPort、ExitCoordinator、AlgoProtection
  state/            # 状态机、持久化、recovery、breaker
  adapters/binance/ # 官方 REST/WS 映射
  analytics/        # 报告和审计
```

策略模块不得调用网络。适配器不得决定策略退出原因。ExitCoordinator 是唯一退出下单入口。

### 25. 关键数据契约

正式结构见附录 D/E。所有金额、价格、数量使用 Decimal；时间同时保存 exchange time、receive wall time、monotonic time。历史缺失字段为 NULL 并携带 data_quality和evidence_level。

### 26. 持久化与恢复

必须事务持久化：

LOCKED, ROUND_SUCCESS, ROUND_FAILED, DAILY_STOP, INCIDENT_LOCK, market_episode_consumed, active_position_instance_id, active_position_revision, active_exit_epoch, active_algo_protection, exit_epochs, exit_order_legs, active_local_exit_leg, flat_confirmation_state

启动顺序：

- 加载 breaker 和 RoundState；

- 验证配置哈希；

- 查询账户模式和余额；

- 查询仓位、普通订单、Algo订单和最近成交；

- 进入 RECOVERING；

- 恢复 position_instance_id、position_revision、exit_epoch 与 flat_confirmation_state；

- 验证 protection_sufficient；

- 清理或退出不一致事实；

- 连续健康窗口通过后才进入 IDLE。

读取失败、哈希不一致或事实不明确，一律 LOCKED。

### 27. 测试门禁

#### 27.1 单元与属性测试

- PnL 不双扣滑点。

- 目标价随数量单调：数量越小，required_target_bps 不下降。

- 保护充分性布尔规则。

- 同一 episode 不重复 EntryIntent。

- 同一 position_instance_id 只有一个 active exit_epoch；旧 revision 不得覆盖新 revision。

- fill 去重、累计成交不回退。

- 强平缓冲和数量/价格取整。

V1.3.4 最终定稿测试增量：

| Test ID | 断言 |
| --- | --- |
| T-PROB-001 | H3报告不得输出未附执行情景条件的无条件单轮成功概率。 |
| T-PROB-002 | F1样本不足时不得将条件概率加权结果声明为稳定实盘概率。 |
| T-POS-001 | 同一IOC三次部分成交只创建一个position_instance_id，revision连续递增。 |
| T-POS-002 | 旧revision迟到快照不得覆盖新revision。 |
| T-POS-003 | flat后迟到开仓成交进入RECOVERING并创建异常instance。 |
| T-FLAT-001 | 两次qty=0但source_ts相同不得确认flat。 |
| T-FLAT-002 | 两次零快照之间LATE_FILL使确认失效。 |
| T-FLAT-003 | 存在UNKNOWN entry order不得确认flat。 |
| T-FLAT-004 | 第二快照过期不得确认flat。 |
| T-EXIT-RACE-001 | 灾难止损与主动退出同时成交不得创建第三退出。 |
| T-EXIT-RACE-002 | flat后迟到退出只更新审计，不恢复持仓。 |
| T-EXIT-RACE-003 | 主动退出UNKNOWN且灾难止损触发时保持同一epoch并RECONCILING。 |
| T-EXIT-RACE-004 | 残余订单取消UNKNOWN不得宣布清理完成。 |
| T-SIZE-001 | 降低杠杆后required_target_bps超上限则拒绝。 |
| T-SIZE-002 | 降低仓位后低于最小名义则拒绝。 |
| T-SIZE-003 | 重新sizing生成新intent_revision但market_episode_id不变。 |
| T-SIZE-004 | 任一重验证门失败禁止提交旧EntryIntent。 |
| T-CLOSE-001 | 双零仓位快照通过但灾难止损仍为NEW：进入RESIDUAL_ORDER_CLEANUP，不得POSITION_FLAT。 |
| T-CLOSE-002 | 残余灾难止损取消UNKNOWN：保持RECONCILING/cleanup，不得判定轮结果。 |
| T-CLOSE-003 | 零数量确认后、清理完成前出现LATE_FILL：撤销确认并RECOVERING/RECONCILING。 |
| T-CLOSE-004 | 全部相关订单终态且无迟到成交：产生POSITION_FLAT，之后才判轮。 |
| T-CLOSE-005 | 仓位为0但存在UNKNOWN entry order：不得POSITION_FLAT。 |
| T-EPOCH-001 | exit_epoch创建与position_revision原子递增；created_against指向提交后revision。 |
| T-EPOCH-002 | 原子事务失败时不得发送退出订单。 |
| T-EPOCH-003 | 乐观锁revision冲突时不得创建epoch，进入RECONCILING。 |
| T-EPOCH-004 | exit_owner切换保持同一epoch，revision递增并记录transition。 |
| T-EPOCH-005 | 同一epoch创建后续订单腿不无理由递增position_revision。 |
| T-LEG-001 | LIMIT IOC终态且残仓>0时，允许在同一epoch创建MARKET回退腿。 |
| T-LEG-002 | LIMIT IOC为UNKNOWN时禁止MARKET回退腿。 |
| T-LEG-003 | 已有本地主动非终态腿时禁止第二个本地主动腿。 |
| T-LEG-004 | 灾难止损触发且主动腿部分成交时不得创建第三个exit_epoch。 |
| T-LEG-005 | 多个ExitOrderLeg成交聚合到同一epoch，不重复计算费用和PnL。 |
| T-LEG-006 | POSITION_FLAT后迟到订单腿事件只更新审计，不恢复持仓。 |
| T-LEG-007 | MARKET回退腿使用最新venue qty，不沿用前一腿requested_qty。 |
| T-LEG-008 | 前一腿非终态时用新client_order_id重发必须被拒绝。 |
| T-FREEZE-001 | 全文不存在“POSITION_FLAT 后再取消残余 Algo 单”的规则。 |
| T-FREEZE-002 | POSITION_QTY_ZERO_CONFIRMED 成立但残余 Algo 单仍为 NEW：不得写 final_realized_ticket_equity。 |
| T-FREEZE-003 | RESIDUAL_ORDER_CLEANUP 未完成：不得判定 ROUND_SUCCESS / ROUND_FAILED。 |
| T-FREEZE-004 | 最终 POSITION_FLAT 成立后才写入 final_realized_ticket_equity。 |
| T-BOOTSTRAP-001 | PositionState revision、ExitEpoch、第一 ExitOrderLeg 与 client_order_id 在同一事务提交。 |
| T-BOOTSTRAP-002 | ExitEpochBootstrapTransaction 失败时不得发送交易所订单。 |
| T-BOOTSTRAP-003 | 事务提交后进程崩溃，恢复使用已持久化 client_order_id 查询或同 ID 重发，不创建新 epoch。 |
| T-BOOTSTRAP-004 | ACTIVE ExitEpoch 无任何 ExitOrderLeg 时触发 ACTIVE_EXIT_EPOCH_WITHOUT_LEG 与 INCIDENT_LOCK。 |
| T-BOOTSTRAP-005 | 交易所订单发送前，对应 ExitOrderLeg 必须已持久化为 PENDING_SUBMIT。 |
| T-LEG-TX-001 | 两个并发回调创建 fallback 腿，只允许一个事务成功。 |
| T-LEG-TX-002 | exit_epoch_revision 乐观锁冲突时不得发送交易所订单。 |
| T-LEG-TX-003 | ActiveLocalExitLeg 主键约束阻止同一 epoch 出现两个本地主动非终态腿。 |
| T-LEG-TX-004 | 前一腿 UNKNOWN 时禁止创建下一腿。 |
| T-LEG-TX-005 | LIMIT IOC 终态后创建 MARKET fallback，复用同一 epoch 并递增 exit_epoch_revision。 |
| T-LEG-TX-006 | fallback requested_qty 等于最新确认 venue qty，不沿用前一腿数量。 |
| T-LEG-TX-007 | 同一 epoch 顺序腿成交聚合到同一退出会计，不重复计算 PnL 或费用。 |
| T-BOOT-MODE-001 | 收到VENUE_DISASTER_STOP事实且无active epoch：创建VENUE_OBSERVED epoch/腿，不调用新建订单接口。 |
| T-BOOT-MODE-002 | 已有active epoch时灾难止损事实归入原epoch，不创建新epoch。 |
| T-BOOT-MODE-003 | LOCAL_SUBMISSION第一腿先持久化PENDING_SUBMIT，再发送交易所订单。 |
| T-BOOT-MODE-004 | VENUE_OBSERVED腿状态来自venue fact，不得初始化为PENDING_SUBMIT。 |
| T-BOOT-MODE-005 | 同一灾难止损事实按venue_order_id/algo_id去重，不重复创建腿或epoch。 |
| T-CONTRACT-001 | ExitEpochBootstrapTransaction缺任一必填字段：事务失败且不得发送订单。 |
| T-CONTRACT-002 | ExitLegCreationTransaction缺任一必填字段：事务失败且不得发送订单。 |
| T-CONTRACT-003 | new_exit_order_leg_id必须写入ExitOrderLeg主键。 |
| T-CONTRACT-004 | 数量/金额初值为0；不存在的标识为NULL，不得空字符串或0伪装ID。 |
| T-CONTRACT-005 | VENUE_OBSERVED必须保存venue_order_id或algo_id，否则RECONCILING/INCIDENT_LOCK。 |
| T-INV-ID-001 | 全文所有INV-* ID全局唯一。 |
| T-INV-ID-002 | 每个INV-*只映射一个定义和对应测试。 |
| T-INV-ID-003 | 不存在重复INV-026。 |
| T-INV-ID-004 | INV-012使用final_realized_ticket_equity，不使用旧realized_ticket_equity。 |
| T-STAGE-001 | Stage B允许发送残余订单取消请求。 |
| T-STAGE-002 | Stage C不得发送任何常规清理请求。 |
| T-STAGE-003 | Stage B cleanup_complete=false时不得进入Stage C。 |
| T-STAGE-004 | Stage C验证失败时返回Stage B/RECONCILING/INCIDENT_LOCK，不直接POSITION_FLAT。 |
| T-STAGE-005 | Stage C全部验证通过才产生POSITION_FLAT并允许轮次结算。 |
| T-DOC-FINAL-001 | 主手册页码连续、无重复、无跳号。 |
| T-DOC-FINAL-002 | 不存在由多余分页符造成的大面积空白页。 |
| T-DOC-FINAL-003 | 表格、代码块、页眉页脚无裁切和重叠。 |
| T-DOC-FINAL-004 | 两份辅助文档页码正确。 |
| T-DOC-FINAL-005 | 分页压缩未改变正文规则含义。 |

#### 27.2 回放

- H1/H2 同秒歧义。

- 阶梯保护路径依赖。

- 目标触及但退出部分成交。

- Mark 与 Contract 不同触发路径在 F1 并列报告。

#### 27.3 故障注入

附录 K 的 20 个原故障场景、V1.3.1 验收测试、V1.3.2/V1.3.3 补丁测试和 V1.3.4 最终定稿测试全部必须通过，才允许测试网自动交易。任何 S0 测试失败阻止合并。

#### 27.4 Execution Capability Spike

最小验证：账户模式、IOC、部分成交、Algo 创建/查询/取消、ALGO_UPDATE、用户流过期、-1007 UNKNOWN、重启恢复、灾难止损与主动退出竞态。Spike 只验证接口和状态，不证明收益。

## 第六篇　阶段路线与验收门槛

### 28. 阶段 0：文档、公式和执行能力冻结

产物：V1.3.4、官方能力记录、Execution Spike、数据契约、PnL测试、状态转换和实验台账。

门槛： S0/S1条款转化为代码断言或明确 RESEARCH；Algo能力不明时 live BLOCKED；Codex 不需自行决定风险行为。

### 29. 阶段 1：数据基础

- 审计现有秒级/分钟数据。

- 补齐 BTC/ETH Binance Trades。

- 重聚合一致性、缺口、重复、单位和时区检查。

- 生成 Parquet catalog 和数据 manifest。

门槛： 重复构建 hash 一致；无未来泄漏；H1/H2字段能力标签正确；缺失 Quote 等字段为 NULL。

### 30. 阶段 2：事件研究

- CanonicalKeyLevel、MarketEpisode、sweep/reclaim/hold。

- 全候选事件，不受账户冲突影响。

- V1_PRICE；如 Trades 已齐，独立研究 V1_FLOW。

- 条件随机基线、聚类、路径和事件漏斗。

门槛： 最小簇数与CI精度同时满足；主假设通过预注册线；事件频率和等待时间与目标相容。

Plan v1.3 可增加限定的条件 H3 生命周期代理，用于时间退出和单仓机会成本研究。它只能
形成 Stage 2 研究证据，不替代 Stage 3 的完整 H3 成本、延迟、部分成交和状态机验收。

### 31. 阶段 3：H3 成本压力

- 主成本情景与压力情景。

- 延迟、止损尾部滑点、部分成交可达性。

- 离散状态机回放。

- 单事件到单轮一笔的 conditional_round_success_probability 桥梁。

门槛：主 H3 情景保留正向经济意义；conditional_round_success_probability 不是少数簇贡献；不得声称真实实盘收益或无条件实盘单轮概率。

Stage 2 条件生命周期 PASS 不能自动满足本阶段。Stage 3 仍需独立批准、完整参数地形、
成本校准、离散状态机回放和阶段验收。

### 32. 阶段 4：LOCKED_HISTORICAL_REPLAY

冻结代码、配置、数据和 Manifest hash 后，对锁定历史区间运行一次。失败则回到新实验，原区间不得再次称为样本外。

门槛： 无结构性反转；参数邻域稳定；所有失败实验归档。

### 33. 阶段 5：前向影子与 FORWARD_HOLDOUT

采集 Trades、BookTicker、Mark、Depth、私有普通订单和 Algo 事件；记录信号时、发送时、成交时快照。影子系统不下单或只运行已批准协议测试。

门槛：数据连续、事件在线/离线一致；F1 执行情景经验分布可与 H3 情景比较；holdout 未用于调参。只有样本量满足预注册门槛时，才允许估计 unconditional_live_round_success_probability；否则保持分情景报告。

### 34. 阶段 6：测试网协议验证

只验证订单、状态、恢复和事故路径；不使用测试网滑点证明正式市场可行。

门槛： 附录K全部通过；无无法解释的仓位/订单状态；重启和流过期可恢复或锁定。

### 35. 阶段 7：极小资金执行校准

固定极小名义仓位，不启用10 USDT单轮。验证真实手续费、滑点、Algo触发、部分成交、UNKNOWN和紧急退出。

门槛： protection_sufficient持续可验证；P0=0；真实成本落入批准压力范围或回写后H3仍通过。

### 36. 阶段 8：单轮10 USDT实验

- 一轮一笔非零成交。

- 最终 POSITION_FLAT 成立即结束本轮。

- 只统计 ROUND_SUCCESS/ROUND_FAILED。

- 不自动创建下一轮。

门槛： 完成预注册轮数和置信区间；执行缺陷与策略失败分开归因。

### 37. 阶段 9：复利实验评估

仅在单轮结果、事件频率、规模容量和账户杠杆档位分别通过后，决定是否创建多轮协议。V1.3.4 不实现自动17轮。

### 38. 阶段停止规则

任一条件停止：事件无条件优势；H3转负；逐笔路径方向崩溃；状态机出现裸仓/重复风险；F1成本超出压力范围；锁定历史失败；研究主要产物变为特征和报告而核心指标未改善。

## 第七篇　前向运行、极小实盘与单轮实验

### 39. 启动 SOP

- 验证批准的 git commit、依赖锁和配置哈希。

- 载入持久化 breaker/RoundState；失败即 LOCKED。

- 同步时钟并校验 server offset。

- 建立公共和私有流，确认 listenKey 保活。

- 查询账户模式、余额、仓位、普通订单、Algo订单、最近成交和 leverage bracket。

- 进入 RECOVERING 并完成一致性检查。

- 运行批准的能力探测，不改变生产仓位。

- 启动 reconciler、ExitCoordinator 和 audit store。

- 连续健康窗口通过后进入 IDLE。

### 40. 实时健康门

| 指标 | BASELINE | 动作 |
| --- | --- | --- |
| quote_age | >500ms | 阻止开仓；持仓按退出规则处理 |
| private_stream_age | >2s且有仓位 | RECONCILING；REST查询 |
| clock_offset | >100ms | BLOCKED |
| position_diff | 任意非零持续超时 | RECONCILING |
| algo_conflict | 查询与事件冲突 | RECONCILING |
| audit_write_failure | 持续失败 | 阻止开仓；有仓位告警 |

阈值为 BASELINE，F1校准后才能批准 small-live。

### 41. 平仓完成条件

平仓采用 PositionClosureProtocol，并在 RECONCILING 内持久化 reconcile_phase：ZERO_QTY_CONFIRMATION → RESIDUAL_ORDER_CLEANUP → FINAL_FLAT_CONFIRMATION。旧名 FlatConfirmationProtocol 标记为 DEPRECATED，仅映射到 ZERO_QTY_CONFIRMATION，不得覆盖全部闭环。

```text
Stage A: ZERO_QTY_CONFIRMATION
first_snapshot.venue_qty == 0
second_snapshot.venue_qty == 0
second_snapshot.source_ts > first_snapshot.source_ts
second_snapshot.received_monotonic_ns - first_snapshot.received_monotonic_ns >= flat_confirmation_interval_ms
current_monotonic_ns - second_snapshot.received_monotonic_ns <= max_position_snapshot_age_ms
no_new_entry_fill_between_snapshots == true
no_new_qty_increasing_event_between_snapshots == true
```

- 双快照通过后只产生 POSITION_QTY_ZERO_CONFIRMED，进入 RECONCILING.RESIDUAL_ORDER_CLEANUP。此时允许未触发灾难止损、待取消残余主动腿或状态尚未终结的相关订单存在；禁止判定轮结果、关闭仓位实例、进入 COOLDOWN/LOCKED 或允许新开仓。

- Stage B：RESIDUAL_ORDER_CLEANUP 是唯一允许执行常规残余订单清理的阶段。ExitCoordinator 枚举当前 position_instance_id 的全部开仓单、灾难止损腿、本地主动腿、目标/紧急/恢复腿和 UNKNOWN 相关订单；发送取消、查询终态、处理 ACK/REJECTED/EXPIRED/FILLED/UNKNOWN，并监控迟到成交。全部条件满足后写入 cleanup_complete=true；任何取消/查询 UNKNOWN 均保持 Stage B/RECONCILING，禁止新开仓，必要时 INCIDENT_LOCK。

- 清理期间若 ENTRY_FILL、LATE_FILL、非零仓位快照或任何数量增加事件使仓位重新非零，立即撤销 POSITION_QTY_ZERO_CONFIRMED，进入 RECOVERING/RECONCILING，并重新建立保护或退出。

- Stage C：FINAL_FLAT_CONFIRMATION 只验证，不发起常规取消、退出腿、exit_epoch 或残余清理动作。进入条件为 cleanup_complete=true；随后验证 position_qty_zero_confirmed=true、venue_position_qty=0、全部相关 entry/exit/algo order 确定终态、无 UNKNOWN、无新 fill、无可触发残余订单。全部通过才产生 POSITION_FLAT。验证发现清理事实失效时返回 Stage B；发现事实冲突/UNKNOWN 时进入 RECONCILING，数据损坏时 INCIDENT_LOCK。

- BASELINE：flat_confirmation_interval_ms=500，max_position_snapshot_age_ms=1000。F1 测量后仅可通过批准配置调整；Stage A 不满足时 reason=ZERO_QTY_CONFIRMATION_RESET，Stage B 未清理完成时 reason=RESIDUAL_ORDER_CLEANUP_PENDING。

POSITION_FLAT 成立后才关闭 position_instance_id，汇总 ExitEpoch 全部订单腿会计，写入 final_realized_ticket_equity，并判定 ROUND_SUCCESS/ROUND_FAILED；之后才进入 COOLDOWN 或持久化 LOCKED。退出过程中的估计只能写入 estimated_ticket_equity_if_flat。

### 42. 人工边界

允许：暂停、锁定、减少风险、紧急平仓、撤孤立残单、人工建立新Round。禁止：取消灾难止损后继续持仓、扩大止损、追加保证金、绕过BLOCK开仓、失败后自动追号、手动把ROUND_FAILED改为成功。

## 第八篇　事故处理与研发治理

### 43. 事故等级

| 等级 | 定义 | 动作 |
| --- | --- | --- |
| P0 | 真实仓位无有效灾难保护、反向仓、无法确认风险订单、无法退出 | 冻结入口、EMERGENCY_EXIT、人工接管、永久LOCKED待审计 |
| P1 | 短暂订单/仓位不一致但可恢复、重复请求、用户流过期 | 停止开仓、对账、当日停机 |
| P2 | 数据缺口、报告或告警错误，无仓位风险 | 阻止新事件并修复 |
| P3 | 非关键展示/性能问题 | 普通缺陷流程 |

### 44. P0原则

- 不以固定 sleep 代替状态确认。

- 通道全部不可用时不盲目多次发送退出，依赖已确认灾难止损并持续恢复事实通道。

- 任何恢复必须产生可重复回放测试。

- 未查明根因不得解除 INCIDENT_LOCK。

### 45. 研究治理

研究看板只回答：事件Lift、H3剩余优势、失败归因、下一实验是否证伪、是否推进阶段门槛。每次实验预注册主问题、数据、主指标、成本情景、通过线和不变项。所有尝试包括失败版本进入 Manifest。

### 46. 当前 Go/No-Go

| 阶段 | V1.3.4 发布时状态 |
| --- | --- |
| 数据/事件研究 | GO |
| H1/H2/H3 | CONDITIONAL GO，需按V1.3.4公式、闭环与标签实现 |
| Execution Spike | GO，限接口能力 |
| 前向影子 | CONDITIONAL GO，需Spike通过 |
| 测试网自动交易 | NO-GO，故障测试未通过前 |
| 极小资金 | NO-GO，F1与测试网未通过前 |
| 10 USDT单轮 | NO-GO，小额执行校准未通过前 |
| 复利 | NO-GO |

## 附录 A　规则元数据最小集

| 字段 | 要求 |
| --- | --- |
| rule_id | 永久唯一，不复用 |
| status | FROZEN/BASELINE/RESEARCH/DEPRECATED/BLOCKED_BY_FORWARD_VALIDATION |
| source | 经验、实验ID、Binance约束、事故ADR |
| owner | 研究/风险/执行/状态模块 |
| tests | 单元/回放/故障测试ID |
| effective_version | 首次生效版本 |
| live_override | 固定false，除非另有FROZEN规则 |
| inputs | 可得字段及数据等级 |
| check_timing | 启动/每事件/每秒/成交/重启 |
| failure_action | 唯一状态和reason_code |

核心规则登记表：

| rule_id | status | source | owner | tests | effective_version | live_override | failure_action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EXEC-NATIVE-STOP-IMMUTABLE | FROZEN | Binance B01-B05 + ADR-V13-001 | execution | T-ALG-001, FI-02, FI-03 | V1.3 | false | RECONCILING/EMERGENCY_EXIT |
| EXEC-EXIT-COORDINATOR-ONLY | FROZEN | 审计A002/A030 | state_machine | UT-EXIT-001, FI-04 | V1.3 | false | 拒绝直接退出并LOCKED |
| EXEC-UNKNOWN-NO-BLIND-RETRY | FROZEN | Binance B06 | execution | FI-03, FI-18 | V1.3 | false | RECONCILING |
| RISK-PROTECTION-SUFFICIENT | FROZEN | Binance B05 + ADR-V13-002 | risk | T-ALG-002, FI-06 | V1.3 | false | EMERGENCY_EXIT |
| RISK-LIQUIDATION-BUFFER | FROZEN | Binance B09 + 审计A010 | risk | T-LIQ-001, FI-16 | V1.3 | false | 拒绝开仓或EXIT_PENDING |
| ACCOUNT-DEDICATED-SUBACCOUNT | FROZEN | 审计A027/A028 | risk | T-ACC-001, T-ACC-002 | V1.3 | false | BLOCKED |
| ROUND-ONE-NONZERO-FILL | FROZEN | 审计A006 | round | T-RND-001 | V1.3 | false | ROUND_FAILED/LOCKED |
| ROUND-SUCCESS-FLAT-EQUITY | FROZEN | 审计A020 | round | FI-11, INV-012 | V1.3 | false | ROUND_FAILED/LOCKED |
| EVENT-CONSUME-MARKET-EPISODE | FROZEN | 审计A014 | research | UT-EVT-011, FI-14 | V1.3 | false | 拒绝EntryIntent |
| FILL-FIRST-NONZERO-PROTECT | FROZEN | 审计A015 | execution | FI-01, FI-02 | V1.3 | false | PROTECTING/EMERGENCY_EXIT |
| FILL-CONTINUE-BY-REACHABILITY | FROZEN | 审计A007 | risk | T-FILL-001, FI-10 | V1.3 | false | EXIT_PENDING |
| PNL-NO-DOUBLE-SLIPPAGE | FROZEN | 审计A004 | accounting | UT-PNL-015 | V1.3 | false | 阻止报告/发布 |
| DATA-HISTORICAL-NO-FAKE-EXECUTION | FROZEN | 数据能力边界 | data | UT-DATA-013 | V1.3 | false | 数据构建失败 |
| RESEARCH-LOCKED-REPLAY-ONCE | FROZEN | 审计A008 | research | T-RES-001 | V1.3 | false | 结果降级为探索性 |
| STATE-BREAKER-PERSIST | FROZEN | 审计A005/A046 | state_machine | FI-15 | V1.3 | false | LOCKED |
| STRATEGY-V1-PRICE-ONLY-HISTORICAL | FROZEN | 数据能力边界 | research | T-EVT-002 | V1.3 | false | 阻止混用V1_FLOW结论 |
| RESEARCH-H3-CONDITIONAL-ROUND-PROB | FROZEN | V1.3.1验收修复F1 | research | T-PROB-001, T-PROB-002 | V1.3.1 | false | 报告构建失败/结论降级 |
| STATE-POSITION-INSTANCE-REVISION | FROZEN | V1.3.1验收修复F2 | state_machine | T-POS-001~003 | V1.3.1 | false | RECONCILING |
| STATE-FLAT-CONFIRMATION-PROTOCOL | FROZEN | V1.3.1验收修复F3 | state_machine | T-FLAT-001~004 | V1.3.1 | false | RECONCILING |
| EXEC-EXIT-RACE-OWNERSHIP | FROZEN | V1.3.1验收修复F4 | execution | T-EXIT-RACE-001~004 | V1.3.1 | false | RECONCILING/INCIDENT_LOCK |
| RISK-RESIZING-FULL-REVALIDATION | FROZEN | V1.3.1验收修复F5 | risk | T-SIZE-001~004 | V1.3.1 | false | REJECT_ENTRY |
| CLOSE-THREE-STAGE | FROZEN | V1.3.2补丁P1 | execution | T-CLOSE-001~005 | V1.3.2 | false | RECONCILING/INCIDENT_LOCK |
| EXIT-EPOCH-ATOMIC-CREATE | FROZEN | V1.3.2补丁P2 | execution | T-EPOCH-001~005 | V1.3.2 | false | 回滚且不得下单 |
| EXIT-LEG-SINGLE-ACTIVE-LOCAL | FROZEN | V1.3.2补丁P3 | execution | T-LEG-001~008 | V1.3.2 | false | 拒绝新腿并RECONCILING |
| CLOSE-FINAL-FLAT-BEFORE-ROUND | FROZEN | V1.3.3冻结F1/F2 | round | T-FREEZE-001~004 | V1.3.3 | false | 保持RECONCILING，禁止判轮 |
| EXIT-EPOCH-BOOTSTRAP-ATOMIC | FROZEN | V1.3.3冻结F3 | execution | T-BOOTSTRAP-001~005 | V1.3.3 | false | 回滚且不得下单；数据损坏则INCIDENT_LOCK |
| EXIT-LEG-CREATION-ATOMIC | FROZEN | V1.3.3冻结F4 | execution | T-LEG-TX-001~007 | V1.3.3 | false | 拒绝新腿并RECONCILING |
| EXIT-LEG-DB-UNIQUE-GUARD | FROZEN | V1.3.3冻结F4 | persistence | T-LEG-TX-001, T-LEG-TX-003 | V1.3.3 | false | 事务失败且不得发送订单 |
| EXIT-BOOTSTRAP-MODE | FROZEN | V1.3.4定稿F1 | execution | T-BOOT-MODE-001~005 | V1.3.4 | false | 模式不匹配则RECONCILING/INCIDENT_LOCK；不得发送重复订单 |
| EXIT-TRANSACTION-FIELD-COMPLETE | FROZEN | V1.3.4定稿F2 | persistence | T-CONTRACT-001~005 | V1.3.4 | false | 回滚、不得发送订单、记录DATA_CONTRACT_INCOMPLETE |
| INVARIANT-ID-GLOBAL-UNIQUE | FROZEN | V1.3.4定稿F3 | governance | T-INV-ID-001~004 | V1.3.4 | false | 构建失败并阻止发布 |
| CLOSURE-STAGE-SINGLE-RESPONSIBILITY | FROZEN | V1.3.4定稿F4 | state_machine | T-STAGE-001~005 | V1.3.4 | false | 保持RECONCILING；禁止POSITION_FLAT |

## 附录 B　配置模板

```text
project:
  manual_version: "V1.3.4"
  strategy_version: "v1-price-0.1.0"
  mode: "research"

venue:
  name: "BINANCE_USDM"
  margin_mode: "ISOLATED"
  position_mode: "ONE_WAY"
  multi_assets_margin: false
  portfolio_margin: false
  auto_add_margin: false

round:
  starting_ticket_equity: "10.00"
  reserve: "2.00"
  max_nonzero_filled_intents: 1
  success_equity_multiple: "2.0"

risk:
  max_leverage: 100
  initial_stop_min_bps: 15       # BASELINE
  initial_stop_max_bps: 35       # BASELINE
  stop_trigger_to_fill_stress_bps: 10  # BASELINE
  mark_contract_divergence_stress_bps: 5
  fixed_liquidation_safety_bps: 10

protection:
  native_algo_type: "STOP_MARKET"
  close_position: true
  working_type: "MARK_PRICE"     # BASELINE, F1 required
  price_protect: false
  mutable_native_stop: false

execution:
  entry_order: "LIMIT_IOC"
  normal_exit: "LIMIT_IOC_THEN_MARKET"
  exit_epoch_bootstrap: "ATOMIC_MODED_WITH_FIRST_LEG_BEFORE_ORDER_SEND"
  local_bootstrap_mode: "LOCAL_SUBMISSION"
  venue_observed_bootstrap_mode: "VENUE_OBSERVED"
  exit_leg_creation: "ATOMIC_EXPECTED_EPOCH_REVISION"
  active_local_leg_guard: "ACTIVE_LOCAL_EXIT_LEG_PRIMARY_KEY"
  max_local_nonterminal_exit_legs: 1
  closure_protocol: "THREE_STAGE_RECONCILING"
  emergency_exit: "MARKET_REDUCE_ONLY"
  max_quote_age_ms: 500
  flat_confirmation_interval_ms: 500  # BASELINE
  max_position_snapshot_age_ms: 1000   # BASELINE
  unknown_status_action: "RECONCILE_NO_BLIND_RETRY"

research:
  historical_conclusion_cap: "H3"
  min_independent_clusters: 200
  max_primary_ci_half_width_pp: 7.5
  locked_historical_replay_once: true
  forward_holdout_required: true

historical_data:
  contract_1s: true
  trade_ticks: true
  quote_ticks: false
  mark_1s: false
  l2: false
  own_execution: false
```

## 附录 C　数据字典与证据字段

| 字段 | 历史 | F1 | 规则 |
| --- | --- | --- | --- |
| reference_price | Contract/Trade | Quote/Trade | 必须有type |
| reference_ask | NULL | Decimal | 历史禁止填0 |
| spread_bps | NULL | float | H3使用scenario字段 |
| receive_latency_ms | NULL | float | 历史禁止伪造 |
| actual_fill_price | NULL | Decimal | 仅真实执行 |
| scenario_slippage_bps | float | 可对照 | 不称真实滑点 |
| data_quality | required | required | OK/GAP/STALE/UNKNOWN |
| evidence_level | H1/H2/H3 | F1 | 每行/每报告携带 |
| cost_scenario_id | H3 required | nullable | 情景可复现 |

## 附录 D　事件数据契约

```text
CanonicalKeyLevel
  key_level_id: str
  instrument_id: str
  source_type: enum
  source_timeframe: enum
  level_price: Decimal
  formed_at_ns: int
  valid_from_ns: int
  expires_at_ns: int
  normalization_rule: str
  priority_rank: int
  member_key_level_ids: list[str]
  config_hash: str

MarketEpisode
  market_episode_id: str
  canonical_key_level_id: str
  sweep_start_ns: int
  sweep_end_ns: int | null
  max_sweep_depth_bps: float
  reclaim_ts_ns: int | null
  hold_completed_ts_ns: int | null
  episode_status: enum
  consumed: bool
  consumed_by_intent_id: str | null
  rearm_eligible_at_ns: int | null

EntryIntent
  intent_id: str
  intent_revision: int
  market_episode_id: str
  instrument_id: str
  side: BUY
  signal_ts_event_ns: int
  expires_at_ns: int
  reference_price: Decimal
  reference_price_type: enum
  reference_ask: Decimal | null
  live_quote_snapshot_id: str | null
  expected_cost_scenario_id: str | null
  invalidation_price: Decimal
  max_entry_price: Decimal | null
  requested_quantity: Decimal
  sizing_snapshot_id: str
  effective_config_snapshot_hash: str
  max_target_bps_allowed_for_event: float
  data_evidence_level: enum
  gate_snapshot: map
  config_hash: str
  strategy_version: str
```

## 附录 E　订单、Algo与Round数据契约

```text
PositionState
  position_instance_id: str
  position_revision: int
  active_exit_epoch: int | null
  exit_owner: enum | null
  reconcile_phase: NONE | ZERO_QTY_CONFIRMATION | RESIDUAL_ORDER_CLEANUP | FINAL_FLAT_CONFIRMATION
  position_qty_zero_confirmed_at_ns: int | null
  cleanup_complete: bool
  updated_at_ns: int

PositionSnapshot
  position_instance_id: str
  position_revision: int
  instrument_id: str
  venue_position_qty: Decimal
  avg_entry_price: Decimal
  accumulated_entry_fee: Decimal
  protected_state: enum
  liquidation_price: Decimal | null
  snapshot_id: str
  source_ts_ns: int
  received_monotonic_ns: int

AlgoProtectionState
  client_algo_id: str
  algo_id: int | null
  instrument_id: str
  position_side: BOTH
  side: SELL
  algo_status: str
  working_type: MARK_PRICE | CONTRACT_PRICE
  trigger_price: Decimal
  close_position: bool
  quantity: Decimal | null
  price_protect: bool
  created_at_ns: int
  last_update_ns: int
  linked_position_instance_id: str
  protection_checked_revision: int
  source: QUERY | ALGO_UPDATE

ExitIntent
  exit_intent_id: str
  position_instance_id: str
  expected_position_revision: int
  requested_exit_owner: enum
  requested_exit_reason: str
  requested_at_ns: int
  status: RECEIVED | ACCEPTED | REJECTED

ExitBootstrapMode
  values: LOCAL_SUBMISSION | VENUE_OBSERVED

ExitEpoch
  exit_epoch: int
  position_instance_id: str
  created_against_position_revision: int
  exit_epoch_revision: int
  bootstrap_mode: LOCAL_SUBMISSION | VENUE_OBSERVED
  exit_owner: enum
  previous_exit_owner: enum | null
  owner_transition_reason: str | null
  initial_venue_qty: Decimal
  current_remaining_qty: Decimal
  realized_exit_qty: Decimal
  realized_exit_value: Decimal
  realized_exit_fee: Decimal
  status: ACTIVE | RECONCILING | CLEANUP | COMPLETED | INCIDENT_LOCKED
  created_at_ns: int
  updated_at_ns: int

ExitOrderLeg
  exit_order_leg_id: str
  position_instance_id: str
  exit_epoch: int
  leg_sequence: int
  leg_type: LOCAL_LIMIT_IOC | LOCAL_MARKET_FALLBACK | LOCAL_EMERGENCY_MARKET | VENUE_DISASTER_STOP | RECOVERY_CLOSE | RESIDUAL_DUST_CLOSE
  exit_owner: enum
  bootstrap_mode: LOCAL_SUBMISSION | VENUE_OBSERVED
  order_origin: LOCAL | VENUE
  requires_local_submission: bool
  client_order_id_source: LOCAL | VENUE | NONE
  client_order_id: str | null
  venue_order_id: str | null
  algo_id: int | null
  requested_qty: Decimal | null
  submitted_qty: Decimal
  filled_qty: Decimal
  remaining_qty: Decimal
  order_type: enum
  limit_price: Decimal | null
  reduce_only: bool
  status: PENDING_SUBMIT | SUBMITTING | NEW | ACKED | PARTIALLY_FILLED | FILLED | CANCELED | REJECTED | EXPIRED | UNKNOWN
  created_at_ns: int                 # local UTC wall clock
  submitted_at_ns: int | null        # local UTC send time
  last_update_ns: int                # local UTC wall clock
  terminal_at_ns: int | null         # local UTC wall clock
  venue_event_ts_ns: int | null      # exchange event time
  venue_transaction_ts_ns: int | null# exchange transaction time
  received_monotonic_ns: int | null  # local monotonic receive time
  replacement_of_leg_id: str | null
  fallback_reason: str | null

ActiveLocalExitLeg
  exit_epoch: int PRIMARY KEY
  exit_order_leg_id: str UNIQUE
  created_at_ns: int

StateTransition
  transition_id: str
  position_instance_id: str | null
  position_revision_before: int | null
  position_revision_after: int | null
  exit_epoch: int | null
  exit_epoch_revision: int | null
  exit_order_leg_id: str | null
  reconcile_phase_before: enum | null
  reconcile_phase_after: enum | null
  from_state: enum
  to_state: enum
  reason_code: str
  event_ts_ns: int

IncidentBundle
  incident_id: str
  position_instance_id: str | null
  latest_position_revision: int | null
  active_exit_epoch: int | null
  exit_owner: enum | null
  position_snapshots: list[PositionSnapshot]
  exit_epochs: list[ExitEpoch]
  exit_order_legs: list[ExitOrderLeg]
  active_local_exit_leg: ActiveLocalExitLeg | null
  algo_states: list[AlgoProtectionState]
  closure_protocol_state: map | null
  config_hash: str

RoundState
  round_id: str
  starting_ticket_equity: Decimal
  current_realized_equity: Decimal
  estimated_ticket_equity_if_flat: Decimal | null
  final_realized_ticket_equity: Decimal | null
  entry_intent_count: int
  has_nonzero_fill: bool
  round_status: enum
  round_started_at: int
  round_ended_at: int | null
  round_result_reason: str | null

CircuitBreakerState
  breaker_type: enum
  effective_from: int
  trading_date: date
  round_id: str | null
  reason_code: str
  config_hash: str
  manual_release_required: bool
  released_by: str | null
  released_at: int | null
```

## 附录 F　PnL公式

历史代理多头：

```text
proxy_entry = reference_entry * (1 + entry_scenario_bps/10000)
proxy_exit  = trigger_or_reference_exit * (1 - exit_scenario_bps/10000)
proxy_gross_pnl = qty * (proxy_exit - proxy_entry)
proxy_net_pnl = proxy_gross_pnl - proxy_entry_fee - proxy_exit_fee - proxy_funding
```

真实多头：

```text
realized_gross_pnl = sum(exit_price*exit_qty) - sum(entry_price*entry_qty)
realized_net_pnl = realized_gross_pnl - actual_commission - actual_funding
```

真实成交价格已经包含价格滑点；realized_net_pnl不得再减slippage。若手续费以非USDT资产收取，必须先按账单入账时的兑换价值转换为票面计价货币。

票面权益：

```text
assert external_cash_flow_since_round_start == 0
estimated_ticket_equity_if_flat = starting_ticket_equity + current_realized_net_pnl + estimated_remaining_exit_net_pnl
assert position_state == POSITION_FLAT
final_realized_ticket_equity = starting_ticket_equity + cumulative_realized_net_pnl
```

2 USDT储备仍属于 starting_ticket_equity，只是未用于开仓保证金，不得在轮开始时预先列为损失。estimated_ticket_equity_if_flat 仅为退出中间估计。ROUND_SUCCESS 只在 POSITION_FLAT、残余普通订单和 Algo 保护均完成清理、且 final_realized_ticket_equity >= 2 * starting_ticket_equity 时成立。

目标退出价（线性合约、单次平均价简化）：

```text
P_exit = [G + q*P_entry*(1+f_entry) + funding] / [q*(1-f_exit)]
```

其中G为本轮仍需净利润，q为实际成交数量，P_entry为真实加权均价，f_entry/f_exit为实际或当前账户费率。部分成交后必须使用实际q、已付费用和剩余目标重新计算；真实成交价模式不再扣入场滑点。

开仓前代理目标位移：

```text
required_target_bps =
  (remaining_net_profit_target + estimated_remaining_cost)
  / actual_position_notional * 10_000
```

若required_target_bps > max_target_bps_allowed_for_event，部分仓不得继续持有。

## 附录 G　关键状态转换表

全局原则：任何没有列出的“状态×事件”组合默认不得产生交易所写操作；记录UNHANDLED_EVENT并进入RECONCILING，若无仓且仅为重复只读事件则保持原状态。

| 当前状态 | 外部事件 | 校验条件 | 允许动作 | 禁止动作 | 下一状态 | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| IDLE | context allow | 无breaker、账户/数据健康 | 建立context | 下单 | CONTEXT_OK | CONTEXT_ALLOWED |
| 任意无仓 | breaker/配置/数据失败 | - | 持久化阻塞 | EntryIntent | BLOCKED | STARTUP_BLOCKED |
| BLOCKED | 健康恢复 | 人工释放且启动断言全过 | 重新运行恢复流程 | 直接IDLE | RECOVERING | BLOCK_RELEASE_REQUESTED |
| CONTEXT_OK | setup valid | canonical level唯一 | 建立episode | 下单 | ARMED | EPISODE_ARMED |
| ARMED | gates pass | episode未消费、intent未过期 | 持久化intent并发送IOC | 第二个intent | ENTRY_PENDING | ENTRY_SUBMITTED |
| ARMED | QUOTE_STALE | F1 Quote超龄 | 消费或按配置放弃episode | 使用旧Quote下单 | COOLDOWN/IDLE | QUOTE_STALE |
| ARMED | CIRCUIT_BREAKER_TRIGGERED | - | 持久化breaker | 下单 | LOCKED | BREAKER_TRIGGERED |
| ENTRY_PENDING | ENTRY_ACK | client_order_id匹配 | 记录ACK | 第二开仓单 | ENTRY_PENDING | ENTRY_ACKED |
| ENTRY_PENDING | PARTIAL_FILL | venue_trade_id新、qty>0 | 去重入账；首次非零fill创建position_instance_id/revision=1，后续fill递增revision；立刻创建灾难保护 | 等IOC结束后保护 | PROTECTING | PARTIAL_FILL_PROTECT |
| ENTRY_PENDING | FULL_FILL | venue_trade_id新 | 入账；确认IOC终态；创建保护 | 第二开仓单 | PROTECTING | FULL_FILL_PROTECT |
| ENTRY_PENDING | ORDER_CANCEL_ACK | 已有非零fill | 停止等待剩余量；按最终事实重算 | 把取消当无仓 | PROTECTING/RECONCILING | ENTRY_REMAINDER_CANCELED |
| ENTRY_PENDING | ORDER_CANCEL_ACK | 零fill且终态 | 消费episode；不追价 | 新ID重下 | COOLDOWN/IDLE | IOC_ZERO_FILL |
| ENTRY_PENDING | ORDER_REJECTED | 交易所明确未接受且零fill | 记录失败并消费episode | 同episode重发 | COOLDOWN/LOCKED | ENTRY_REJECTED |
| ENTRY_PENDING | ORDER_STATUS_UNKNOWN | client ID固定 | 查询订单/成交/仓位；不换ID | 盲重发 | RECONCILING | ORDER_STATE_UNKNOWN |
| 任意 | DUPLICATE_FILL | venue_trade_id已见 | 忽略经济入账；记录重复 | 重复增加数量/PnL | 原状态 | DUPLICATE_EVENT |
| 任意 | LATE_FILL | trade_id新且与已终结开仓关联 | 若旧实例已确认flat，进入RECOVERING并创建异常position_instance_id；否则递增当前revision并立即保护/紧急退出 | 忽略迟到fill | PROTECTING/EMERGENCY_EXIT | LATE_ENTRY_FILL |
| PROTECTING | ALGO_UPDATE/查询有效 | linked_position_instance_id匹配，protection_checked_revision为当前revision且protection_sufficient | 持久化Algo；计算部分成交可达性 | 撤销保护 | VALIDATING/EXIT_PENDING | PROTECTION_CONFIRMED |
| PROTECTING | ALGO rejected/expired/canceled | venue qty>0 | ExitCoordinator紧急退出 | 继续持仓 | EMERGENCY_EXIT | PROTECTION_MISSING |
| PROTECTING | ORDER_STATUS_UNKNOWN | Algo client ID固定 | 同ID查询；保持UNKNOWN | 新ID重复建Algo | RECONCILING | ALGO_STATE_UNKNOWN |
| VALIDATING | activation | 首次达到，粘滞 | 记录activated | 回退未激活 | PROTECTED | ACTIVATED |
| VALIDATING | 时间/结构/风险退出 | ExitDecision唯一 | 调用 ExitEpochBootstrapTransaction；同一事务持久化 position revision、ExitEpoch、第一 ExitOrderLeg 与 client_order_id；提交后发送首腿 | 事务前下单、epoch与第一腿分步落库或生成新client_order_id | EXIT_PENDING | ACTIVATION_TIMEOUT/STRUCTURE/LIQUIDATION |
| PROTECTED | target decision | 当前position_instance_id无active exit_epoch | 调用 ExitEpochBootstrapTransaction；同一事务持久化 position revision、ExitEpoch、第一 ExitOrderLeg 与 client_order_id；提交后发送首腿 | 事务前下单、epoch与第一腿分步落库或生成新client_order_id | TARGET_EXIT_PENDING | TARGET_EXIT |
| PROTECTED | protection/time/structure | 当前position_instance_id无active exit_epoch | 调用 ExitEpochBootstrapTransaction；同一事务持久化 position revision、ExitEpoch、第一 ExitOrderLeg 与 client_order_id；提交后发送首腿 | 事务前下单、epoch与第一腿分步落库或生成新client_order_id | EXIT_PENDING | EXIT_DECISION |
| TARGET_EXIT_PENDING | PARTIAL_FILL | trade_id新 | 按trade_id入账到当前ExitOrderLeg和ExitEpoch；对账残仓；本地腿非终态时不得创建回退腿 | 提前ROUND_SUCCESS | TARGET_EXIT_PENDING | TARGET_PARTIAL |
| TARGET_EXIT_PENDING | FULL_FILL | 最新venue qty待确认 | 查询仓位和活动单 | 仅凭fill宣告flat | RECONCILING | TARGET_FILL_RECONCILE |
| EXIT_PENDING | PARTIAL_FILL | trade_id新 | 入账当前ExitOrderLeg；venue qty变化递增position_revision；保持同一epoch并进入RECONCILING | 新epoch或并发第二本地主动腿 | EXIT_PENDING/RECONCILING | EXIT_PARTIAL |
| EXIT_PENDING | FULL_FILL | - | 查询仓位和活动单 | 直接COOLDOWN | RECONCILING | EXIT_FILL_RECONCILE |
| EXIT_PENDING | ORDER_STATUS_UNKNOWN | client ID固定 | 查询同一ExitOrderLeg/client_order_id；阻塞后续腿 | 新ID退出或MARKET回退 | RECONCILING | EXIT_UNKNOWN |
| 任意持仓 | ALGO_UPDATE TRIGGERING/TRIGGERED | position_instance_id匹配 | 使用VENUE_OBSERVED：无epoch则原子创建接管epoch与venue腿；有epoch则归入原epoch并更新owner/revision；不调用新建退出订单接口 | LOCAL_SUBMISSION重复发送灾难止损、创建新epoch或将venue腿设为PENDING_SUBMIT | RECONCILING | NATIVE_STOP_TRIGGERED |
| 任意持仓 | PRIVATE_STREAM_STALE | REST可用 | 停止新风险；REST对账 | 假设订单未变化 | RECONCILING | PRIVATE_STREAM_STALE |
| 任意持仓 | REST_UNAVAILABLE | 私有流有效且保护有效 | 禁止新风险；保持保护并告警 | 猜仓位发送多单 | EMERGENCY_EXIT/RECONCILING | REST_UNAVAILABLE |
| 任意持仓 | REST_UNAVAILABLE + PRIVATE_STREAM_STALE | 灾难保护最后确认有效 | 不盲发；持续恢复通道和P0告警 | 猜数量重复市价 | EMERGENCY_EXIT | FACT_CHANNELS_DOWN |
| RECONCILING | POSITION_SNAPSHOT qty>0 | source_ts/received_monotonic_ns不旧于当前position_revision基准 | 递增或确认position_revision；核验保护/退出；旧revision不得覆盖新revision | 旧快照覆盖新事实 | PROTECTING/VALIDATING/PROTECTED/EXIT_PENDING | POSITION_RECONCILED |
| RECONCILING | POSITION_SNAPSHOT qty=0 | 不得以单次快照直接完成闭环 | 路由到ZERO_QTY_CONFIRMATION子阶段 | 关闭instance或判轮 | RECONCILING.ZERO_QTY_CONFIRMATION | ZERO_QTY_CONFIRMATION_STARTED |
| 任意 | PROCESS_RESTART | - | 载入持久状态、breaker、episode、position instance/revision、exit epoch并查询Venue | 默认IDLE | RECOVERING | PROCESS_RESTART |
| RECOVERING | facts一致且无仓 | breaker允许 | 健康观察窗 | 自动开仓 | IDLE/LOCKED | RECOVERY_COMPLETE |
| RECOVERING | 有仓且保护有效 | position_instance_id与position_revision恢复 | 恢复持仓状态；禁止新仓 | 重置episode/round | VALIDATING/PROTECTED/EXIT_PENDING | POSITION_RECOVERED |
| RECOVERING | 有仓无保护 | - | ExitCoordinator紧急退出 | 继续持仓 | EMERGENCY_EXIT | RECOVERY_UNPROTECTED |
| COOLDOWN | timer elapsed | round未结束且breaker允许；仅研究/非单轮模式 | 返回IDLE | 绕过一轮规则 | IDLE/LOCKED | COOLDOWN_COMPLETE |
| LOCKED | PROCESS_RESTART | 持久breaker存在 | 保持锁定 | 默认IDLE | LOCKED | LOCK_PERSISTED |
| 任意 | CIRCUIT_BREAKER_TRIGGERED | - | 持久化breaker；停止新风险 | 清除已有灾难保护 | LOCKED/EXIT_PENDING | BREAKER_TRIGGERED |
| RECONCILING | POSITION_SNAPSHOT qty=0（第一快照） | 快照新鲜、instance匹配且reconcile_phase=ZERO_QTY_CONFIRMATION | 保存first_snapshot；不取消灾难止损、不宣告flat | 宣告flat | RECONCILING.ZERO_QTY_CONFIRMATION | ZERO_QTY_CONFIRMATION_STARTED |
| RECONCILING | POSITION_SNAPSHOT qty=0（第二快照） | 双快照时序/年龄/无数量增加事件通过 | 产生POSITION_QTY_ZERO_CONFIRMED；进入残余订单清理 | 关闭instance、判轮或跳过订单清理 | RECONCILING.RESIDUAL_ORDER_CLEANUP | POSITION_QTY_ZERO_CONFIRMED |
| RECONCILING | ENTRY_FILL/LATE_FILL/非零快照/事实倒退 | ZERO_QTY_CONFIRMATION或RESIDUAL_ORDER_CLEANUP进行中 | 撤销零数量确认；递增revision或创建异常instance；重新对账 | 继续使用旧零快照 | PROTECTING/RECONCILING | FLAT_CONFIRMATION_RESET |
| ARMED | RESIZING_REQUIRED | 尚未发送订单且episode未过期 | 完整运行ReSizingRevalidationPipeline；生成新intent_revision/sizing_snapshot | 沿用旧EntryIntent | ARMED/COOLDOWN | RESIZING_REVALIDATED/RESIZING_REVALIDATION_FAILED |
| EXIT_PENDING/TARGET_EXIT_PENDING | ALGO TRIGGERED + active exit | 同一position_instance_id | 保持同一exit_epoch；更新exit_owner并进入对账 | 创建第三退出 | RECONCILING | EXIT_RACE_RECONCILE |
| RECONCILING | 迟到退出事件且flat已确认 | trade/order属于已关闭instance | 只更新会计、订单终态与审计 | 恢复持仓状态 | LOCKED/COOLDOWN | LATE_EXIT_AFTER_FLAT |
| 任意需退出状态 | EXIT_DECISION | 无active exit_epoch且expected revision匹配 | 使用LOCAL_SUBMISSION；完整原子初始化PositionState、ExitEpoch、第一ExitOrderLeg和client_order_id；提交后发送PENDING_SUBMIT首腿 | 字段不完整、先发送后落库或使用VENUE_OBSERVED状态发送 | EXIT_PENDING/TARGET_EXIT_PENDING | EXIT_EPOCH_CREATED |
| 任意需退出状态 | EXIT_EPOCH_REVISION_CONFLICT | stored revision != expected | 不得创建epoch或下单；重新读取事实 | 用旧revision强行写入 | RECONCILING | EXIT_EPOCH_REVISION_CONFLICT |
| EXIT_PENDING/TARGET_EXIT_PENDING | LOCAL_LEG_TERMINAL_WITH_REMAINDER | 前腿终态、latest venue qty>0、无UNKNOWN、ActiveLocalExitLeg为空、expected_exit_epoch_revision匹配、epoch ACTIVE | 调用ExitLegCreationTransaction；完整初始化并原子递增exit_epoch_revision、创建LOCAL/PENDING_SUBMIT腿与ActiveLocalExitLeg；提交后发送 | 新epoch、沿用旧requested_qty、应用层先查后写或并发第二本地主动腿 | EXIT_PENDING | EXIT_LEG_FALLBACK_CREATED |
| EXIT_PENDING/TARGET_EXIT_PENDING | LOCAL_LEG_UNKNOWN | 当前本地主动腿UNKNOWN | 同client ID查询并阻塞新腿 | 换ID创建MARKET腿 | RECONCILING | EXIT_LEG_UNKNOWN |
| RECONCILING.RESIDUAL_ORDER_CLEANUP | CLEANUP_START | POSITION_QTY_ZERO_CONFIRMED=true | 枚举并取消所有可取消相关entry/exit/algo腿；查询每个终态 | 判轮或允许开仓 | RECONCILING.RESIDUAL_ORDER_CLEANUP | RESIDUAL_ORDER_CLEANUP_STARTED |
| RECONCILING.RESIDUAL_ORDER_CLEANUP | ORDER_CANCEL_UNKNOWN | 任一相关订单UNKNOWN | 保持清理和锁定；同ID查询；必要时INCIDENT_LOCK | 宣告flat或新ID重试 | RECONCILING.RESIDUAL_ORDER_CLEANUP | RESIDUAL_ORDER_CLEANUP_UNKNOWN |
| RECONCILING.RESIDUAL_ORDER_CLEANUP | CLEANUP_COMPLETE | 全部相关订单确定终态、无UNKNOWN/可触发残单、零数量确认仍有效 | 写cleanup_complete=true，进入FINAL_FLAT_CONFIRMATION；不再发送清理动作 | 直接POSITION_FLAT、判轮或在Stage C继续常规清理 | RECONCILING.FINAL_FLAT_CONFIRMATION | RESIDUAL_ORDER_CLEANUP_COMPLETED |
| RECONCILING.RESIDUAL_ORDER_CLEANUP | LATE_FILL/QTY_INCREASE | trade_id新或venue qty>0 | 撤销POSITION_QTY_ZERO_CONFIRMED；恢复/重新对账并保护或退出 | 继续清理并宣告flat | RECOVERING/RECONCILING | ZERO_QTY_CONFIRMATION_INVALIDATED |
| RECOVERING | ACTIVE_EXIT_EPOCH_WITHOUT_LEG | active_exit_epoch存在且无任何ExitOrderLeg | INCIDENT_LOCK；查询交易所订单/仓位；禁止补建无来源订单腿 | 创建新epoch、新第一腿或开仓 | RECOVERING | ACTIVE_EXIT_EPOCH_WITHOUT_LEG |
| EXIT_PENDING/TARGET_EXIT_PENDING | EXIT_LEG_CREATION_REQUEST | expected_exit_epoch_revision匹配且ActiveLocalExitLeg为空 | 运行ExitLegCreationTransaction；提交后发送已持久化腿 | 非原子创建、并发第二腿或先发送后落库 | EXIT_PENDING/TARGET_EXIT_PENDING | EXIT_LEG_CREATED |
| EXIT_PENDING/TARGET_EXIT_PENDING | EXIT_LEG_REVISION/UNIQUE_CONFLICT | revision冲突或ActiveLocalExitLeg主键冲突 | 不得创建或发送订单；重新读取事实并进入对账 | 重试插入、换ID或新epoch | RECONCILING | EXIT_LEG_REVISION_CONFLICT |
| RECONCILING.FINAL_FLAT_CONFIRMATION | FINAL_FLAT_VALIDATE | cleanup_complete=true，qty=0，全部相关订单终态，无UNKNOWN/迟到fill/可触发残单 | 只读验证；通过后产生POSITION_FLAT、关闭instance、汇总epoch会计、写final_realized_ticket_equity并判轮 | 发送取消/退出订单、创建腿/epoch或自行修复 | LOCKED/COOLDOWN | POSITION_FLAT_CONFIRMED |
| RECONCILING.FINAL_FLAT_CONFIRMATION | FINAL_FLAT_VALIDATION_FAILED | Stage C任一验证失败 | 按原因返回Stage B、RECONCILING或INCIDENT_LOCK | 直接产生POSITION_FLAT | RECONCILING.RESIDUAL_ORDER_CLEANUP/RECONCILING/LOCKED | FINAL_FLAT_VALIDATION_FAILED |
| 任意持仓 | VENUE_DISASTER_STOP_OBSERVED | position_instance_id匹配且venue_order_id或algo_id存在 | 使用VENUE_OBSERVED归入现有epoch或创建接管epoch/venue腿；不提交订单 | 使用LOCAL_SUBMISSION、重复发送或伪造client_order_id | RECONCILING | VENUE_STOP_OBSERVED |
| 任意需退出状态 | BOOTSTRAP_DATA_CONTRACT_INCOMPLETE | 任一必填字段缺失 | 回滚事务、不得发送订单、RECONCILING/INCIDENT_LOCK | 猜测默认ID或发送订单 | RECONCILING/LOCKED | DATA_CONTRACT_INCOMPLETE |

## 附录 H　系统不变量

| ID | 不变量 | 输入字段 | 检测时机 | 失败动作 | 测试 |
| --- | --- | --- | --- | --- | --- |
| INV-001 | 账户最多一个策略仓位 | venue positions, account_id, instrument | 每订单/快照/启动 | 拒绝并LOCKED | UT-INV-001 |
| INV-002 | 非零仓位有有效灾难保护或处于持久化紧急状态 | venue_qty, AlgoProtectionState, persisted_state | fill/Algo/每秒/重启 | EMERGENCY_EXIT | FI-02, FI-06 |
| INV-003 | 本地主动保护阈值不向不利方向放宽 | previous_floor, candidate_floor, side | 每ExitDecision | 拒绝变更并记录 | UT-INV-003 |
| INV-004 | 主动退出必须reduce-only且由ExitCoordinator创建 | order.reduce_only, exit_intent_id, exit_owner | 每退出下单 | 拒绝订单并LOCKED | UT-EXIT-001 |
| INV-005 | consumed market_episode不得再开仓 | market_episode_id, consumed, intent_id | 每EntryIntent | 拒绝 | FI-14 |
| INV-006 | 数据/配置/账户未知不得ENTRY_PENDING | data_quality, config_hash, account assertions | 每触发/启动 | BLOCKED | UT-INV-006 |
| INV-007 | flat确认后不得残留可触发Algo或开仓单 | venue_qty, open orders, Algo status | 每次flat候选/重启 | RECONCILING | FI-05 |
| INV-008 | 交易所事实优先，但旧position_revision或旧快照不得覆盖新revision | snapshot source_ts/version, position_instance_id, position_revision | 每快照 | 丢弃旧快照或RECONCILING | FI-12 |
| INV-009 | 同一position_instance_id最多一个active exit_epoch | position_instance_id, position_revision, exit_epoch, exit status | 每退出事件 | 拒绝新epoch | FI-04 |
| INV-010 | 任何真实非零仓位必须有保护，或处于持久化EMERGENCY_EXIT/RECONCILING | venue_qty, protection_sufficient, persisted_state | 每fill/秒/重启 | 紧急状态 | FI-02 |
| INV-011 | market_episode消费不受strategy_version变化影响 | market_episode_id, strategy_version, consumed | 每意图 | 拒绝 | UT-EVT-011 |
| INV-012 | ROUND_SUCCESS仅在POSITION_FLAT、残单清理完成且final_realized_ticket_equity达标后成立 | position state, related orders, final_realized_ticket_equity | 轮结束候选 | ROUND_FAILED/LOCKED | FI-11 |
| INV-013 | 历史不得伪造Bid/Ask/延迟/部分成交/真实滑点 | evidence_level, nullable execution fields | 数据构建/报告 | 构建失败 | UT-DATA-013 |
| INV-014 | LOCKED、ROUND_FAILED、ROUND_SUCCESS和事故breaker跨重启保持 | persisted breaker/round state, config_hash | 启动/状态改变 | 保持LOCKED | FI-15 |
| INV-015 | 真实成交均价已计入PnL时不得二次扣价格滑点 | pnl_mode, fills, commission, funding, slippage field | PnL计算/报告 | 测试失败并阻止发布 | UT-PNL-015 |
| INV-016 | 普通订单或Algo状态UNKNOWN时不得换ID盲重发相同风险订单 | client_order_id/client_algo_id, status, query result | 超时/错误码 | RECONCILING | FI-03, FI-18 |
| INV-017 | POSITION_QTY_ZERO_CONFIRMED不等于POSITION_FLAT；必须完成残余订单清理 | reconcile_phase, qty snapshots, related orders | 每次零仓候选/重启 | 保持RECONCILING，禁止判轮 | T-CLOSE-001~004 |
| INV-018 | 任一当前实例相关可触发订单为UNKNOWN时不得POSITION_FLAT或判轮 | entry/exit/algo leg status, instance ID | 清理/flat候选 | RESIDUAL_ORDER_CLEANUP或INCIDENT_LOCK | T-CLOSE-002, T-CLOSE-005 |
| INV-019 | 创建active_exit_epoch与递增position_revision必须在同一原子事务 | PositionState, ExitEpoch, expected revision | 每次epoch创建 | 回滚且不得下单；RECONCILING | T-EPOCH-001~003 |
| INV-020 | ExitEpoch.created_against_position_revision等于创建事务提交后的PositionState.position_revision | epoch, position state | 事务提交/恢复 | INCIDENT_LOCK并恢复 | T-EPOCH-001 |
| INV-021 | 同一exit_epoch同时最多一个本地主动非终态ExitOrderLeg | epoch legs, leg status | 每次腿创建/订单更新 | 拒绝新腿并RECONCILING | T-LEG-002~003, T-LEG-008 |
| INV-022 | LIMIT到MARKET回退复用同一epoch，且前一主动腿必须确定终态 | epoch, previous leg, latest venue qty | fallback创建前 | 拒绝fallback | T-LEG-001~002, T-LEG-007 |
| INV-023 | 全部退出订单腿成交聚合到同一ExitEpoch会计，不按腿重复PnL/费用/轮次 | fills, trade IDs, epoch aggregates | 每fill/轮结束 | 停止发布、RECONCILING | T-LEG-005 |
| INV-024 | 灾难止损、主动退出和紧急退出竞态不得创建新epoch；除非旧实例已POSITION_FLAT且出现新真实实例 | instance, epoch, owner, legs, venue qty | 每Algo/退出/迟到事件 | RECONCILING或INCIDENT_LOCK | T-LEG-004, T-EXIT-RACE-001~004 |
| INV-025 | 同一IOC多次部分成交只对应一个position_instance_id，position_revision单调递增 | intent/order IDs, trade IDs, instance, revision | 每fill/快照/恢复 | 拒绝状态回退并RECONCILING | T-POS-001~003 |
| INV-026 | 任何仓位或杠杆调整后完整重跑全部开仓门并生成新intent_revision | sizing inputs, gates, intent revision, episode | 每re-sizing和提交前 | REJECT_ENTRY | T-SIZE-001~004 |
| INV-027 | 任何position_instance_id只有在POSITION_FLAT后才能写final_realized_ticket_equity并判ROUND_SUCCESS/ROUND_FAILED | position state, closure facts, final equity | 轮次结算候选 | 保持RECONCILING，禁止判轮 | T-FREEZE-002~004 |
| INV-028 | POSITION_QTY_ZERO_CONFIRMED后必须先完成RESIDUAL_ORDER_CLEANUP，不得直接POSITION_FLAT | reconcile_phase, related orders | 零数量确认后 | 保持清理阶段 | T-FREEZE-001~003 |
| INV-029 | ExitEpoch、提交后position_revision、第一ExitOrderLeg与client_order_id必须同一原子事务持久化 | PositionState, ExitEpoch, first leg | 每次bootstrap | 回滚且不得下单 | T-BOOTSTRAP-001~003 |
| INV-030 | 任何ACTIVE ExitEpoch至少关联一条已持久化ExitOrderLeg | epoch status, leg count | 启动/恢复/每次epoch更新 | ACTIVE_EXIT_EPOCH_WITHOUT_LEG；INCIDENT_LOCK | T-BOOTSTRAP-004 |
| INV-031 | 交易所订单只能在对应ExitOrderLeg以PENDING_SUBMIT持久化成功后发送 | leg status, client_order_id | 每次order send | 拒绝发送并INCIDENT_LOCK | T-BOOTSTRAP-005 |
| INV-032 | 同一exit_epoch最多一个本地主动非终态腿，且由ActiveLocalExitLeg主键原子保证 | ActiveLocalExitLeg, leg status | 每次腿创建/终态迁移 | 事务失败且RECONCILING | T-LEG-TX-001, T-LEG-TX-003 |
| INV-033 | 后续ExitOrderLeg创建必须递增exit_epoch_revision并校验expected revision | epoch revision, leg sequence | 每次后续腿创建 | 拒绝创建和发送；RECONCILING | T-LEG-TX-002, T-LEG-TX-005 |
| INV-034 | 任一本地主动腿为UNKNOWN时不得创建新腿、换ID重发或创建新epoch | leg status, client_order_id | UNKNOWN/创建候选 | 同ID查询并RECONCILING | T-LEG-TX-004 |
| INV-035 | ROUND结果不得在POSITION_QTY_ZERO_CONFIRMED、RESIDUAL_ORDER_CLEANUP或RECONCILING阶段产生 | reconcile_phase, round status | 每次轮状态写入 | 拒绝写入并INCIDENT_LOCK | T-FREEZE-002~004 |
| INV-036 | 灾难止损已由交易所触发/观察时必须使用VENUE_OBSERVED登记，不得再次发送同一退出 | bootstrap_mode, venue_order_id, algo_id, active_exit_epoch | ALGO_UPDATE/查询恢复 | RECONCILING/INCIDENT_LOCK，拒绝本地提交 | T-BOOT-MODE-001~005 |
| INV-037 | LOCAL_SUBMISSION第一ExitOrderLeg必须完整持久化为PENDING_SUBMIT后才能发送 | bootstrap_mode, leg status, client_order_id | 每次本地退出发送前 | 拒绝发送并INCIDENT_LOCK | T-BOOT-MODE-003, T-CONTRACT-001 |
| INV-038 | VENUE_OBSERVED不得产生本地提交；订单腿状态必须来自交易所事实映射 | bootstrap_mode, order_origin, mapped status | 每次venue fact接管 | RECONCILING/INCIDENT_LOCK | T-BOOT-MODE-001~005 |
| INV-039 | ExitEpochBootstrapTransaction与ExitLegCreationTransaction全部必填字段在提交前完整初始化 | transaction payload, non-null constraints, defaults | 每次事务提交 | 回滚、不得发送、DATA_CONTRACT_INCOMPLETE | T-CONTRACT-001~005 |
| INV-040 | 系统不变量ID全局唯一，定义、测试、日志和事故引用唯一映射 | invariant registry, references | 构建/发布 | 构建失败并阻止发布 | T-INV-ID-001~004 |
| INV-041 | Stage B唯一执行残余订单清理；Stage C只读验证并产生POSITION_FLAT | reconcile_phase, attempted action, cleanup_complete | 每次closure action/state transition | 拒绝动作并保持RECONCILING；必要时INCIDENT_LOCK | T-STAGE-001~005 |

## 附录 I　Reason Code

| 类别 | Code | 动作 |
| --- | --- | --- |
| 数据 | DATA_STALE / SEQUENCE_GAP / QUOTE_STALE | BLOCK或退出评估 |
| 事件 | NO_KEY_LEVEL / SWEEP_RANGE / RECLAIM_TIMEOUT / REBREAK | 不开仓 |
| 成本 | COST_SCENARIO_FAIL / TARGET_UNREACHABLE / RESIZING_REVALIDATION_FAILED | 不开仓或退出部分仓 |
| 执行 | ORDER_STATE_UNKNOWN / ALGO_STATE_UNKNOWN / EXIT_STATE_UNKNOWN / EXIT_RACE_RECONCILE / RESIDUAL_ORDER_UNKNOWN | RECONCILING |
| 保护 | PROTECTION_MISSING / LIQUIDATION_BUFFER_FAIL | EMERGENCY/拒绝开仓 |
| 轮次 | ROUND_SUCCESS / ROUND_FAILED / FINAL_TICKET_EQUITY_BEFORE_FLAT | 仅POSITION_FLAT后结算；否则RECONCILING/INCIDENT_LOCK |
| 恢复 | RECOVERY_CONFLICT / PERSISTENCE_FAILURE / POSITION_REVISION_STALE / LATE_FILL_NEW_INSTANCE / FLAT_CONFIRMATION_RESET | LOCKED |
| 账户 | ACCOUNT_MODE_INVALID / WRONG_SUBACCOUNT | BLOCKED |
| 系统 | PRIVATE_STREAM_STALE / REST_UNAVAILABLE | RECONCILING/EMERGENCY |
| 平仓闭环 | ZERO_QTY_CONFIRMATION_STARTED / POSITION_QTY_ZERO_CONFIRMED / RESIDUAL_ORDER_CLEANUP_STARTED / RESIDUAL_ORDER_CLEANUP_UNKNOWN / POSITION_FLAT_CONFIRMED / RESIDUAL_ORDER_CLEANUP_COMPLETED / FINAL_FLAT_VALIDATION_FAILED / STAGE_C_CLEANUP_ACTION_FORBIDDEN | Stage B执行清理；Stage C只验证；失败保持RECONCILING或INCIDENT_LOCK |
| 退出周期 | EXIT_EPOCH_CREATED / EXIT_EPOCH_REVISION_CONFLICT / EXIT_OWNER_TRANSITION / EXIT_LEG_UNKNOWN / ACTIVE_LOCAL_LEG_EXISTS / EXIT_LEG_FALLBACK_CREATED / ACTIVE_EXIT_EPOCH_WITHOUT_LEG / EXIT_LEG_REVISION_CONFLICT / LOCAL_ACTIVE_LEG_UNIQUE_CONFLICT / EXIT_LEG_CREATED / BOOTSTRAP_MODE_MISMATCH / VENUE_STOP_OBSERVED / DATA_CONTRACT_INCOMPLETE | 按bootstrap模式原子登记；VENUE_OBSERVED不发送；字段不完整则回滚并RECONCILING/INCIDENT_LOCK |
| 退出会计 | EXIT_ACCOUNTING_CONFLICT / DUPLICATE_LEG_FILL | 停止发布结果并RECONCILING/INCIDENT_LOCK |

## 附录 J　实验 Manifest

```text
experiment_id
strategy_variant
primary_hypothesis
primary_instrument
frozen_data_ranges
locked_historical_replay_range
forward_holdout_start
feature_config_hash
event_config_hash
cost_scenario_id
primary_metric
probability_metric_name
execution_scenario_definition
execution_scenario_distribution_source
cluster_definition
pass_rule
fail_rule
all_parameter_values_attempted
code_commit
data_manifest_hash
result
researcher_decision
```

## 附录 K　故障注入场景

每个场景必须在测试Manifest中保存九个字段：test_id、initial_state、persisted_state、venue_facts、incoming_event、expected_action、forbidden_action、expected_next_state、expected_reason_code。下表使用合并列，但每个单元格保留字段标签，不得省略。

| test_id | initial_state / persisted_state | venue_facts | incoming_event | expected_action / forbidden_action | expected_next_state / reason_code |
| --- | --- | --- | --- | --- | --- |
| FI-01 | initial=ENTRY_PENDING; persisted=intent+order | IOC已报30% fill；仓位快照50% | cancel ACK延迟/新fill | expected=三事实对账，非零仓立即保护，按最终qty重算; forbidden=按30%继续 | RECONCILING / PARTIAL_FILL_CONFLICT |
| FI-02 | initial=PROTECTING; persisted=position_instance_id/revision | 非零仓，尚无已确认Algo | WebSocket断线 | expected=同clientAlgoId查询，不能确认则ExitCoordinator emergency; forbidden=等待不处理 | RECONCILING或EMERGENCY_EXIT / PROTECTION_MISSING |
| FI-03 | initial=PROTECTING; persisted=client_algo_id | Algo创建可能已被接受 | 请求超时UNKNOWN | expected=同ID查询; forbidden=新ID重发 | RECONCILING / ALGO_STATE_UNKNOWN |
| FI-04 | initial=EXIT_PENDING; persisted=position_instance_id+active exit_epoch+active local leg | 原生止损与主动退出均有成交 | ALGO_UPDATE+fill并发 | expected=灾难腿与主动腿成交归集同一epoch；不得创建第二本地主动腿或新epoch；forbidden=第三epoch/并发local leg | RECONCILING / NATIVE_ACTIVE_RACE |
| FI-05 | initial=EXIT_PENDING; persisted=round未完成 | 本地qty=0，venue有dust | POSITION_SNAPSHOT | expected=进入ZERO_QTY_CONFIRMATION；dust非零则继续退出；forbidden=单次零快照或本地qty宣告ROUND_SUCCESS | EXIT_PENDING / RESIDUAL_POSITION |
| FI-06 | initial=RECOVERING; persisted=旧position_instance_id/revision | 1仓位+2个Algo止损 | PROCESS_RESTART事实查询 | expected=禁止开仓，识别有效保护；无法证明则退出; forbidden=任意保留后IDLE | RECOVERING/EMERGENCY_EXIT / PROTECTION_CONFLICT |
| FI-07 | initial=VALIDATING; persisted=workingType=MARK_PRICE | Mark触发，Contract未触及 | ALGO_UPDATE TRIGGERED | expected=接受Algo事实并记录双价格; forbidden=用Contract否认 | RECONCILING / MARK_TRIGGERED |
| FI-08 | initial=PROTECTED; persisted=activated=true | 点差扩大，estimated_exit_net_pnl转负 | QUOTE_UPDATE | expected=激活不回退，产生保护退出; forbidden=降低保护阈值 | EXIT_PENDING / EXECUTABLE_PNL_NEGATIVE |
| FI-09 | initial=ARMED; persisted=EntryIntent未发单 | IOC前点差扩大/Quote超龄 | QUOTE_UPDATE | expected=发送前重校验，放弃并消费episode; forbidden=使用旧Quote追价 | COOLDOWN / SPREAD_TOO_WIDE |
| FI-10 | initial=PROTECTING; persisted=actual_qty | required_target_bps超上限 | IOC终态 | expected=ExitCoordinator退出; forbidden=固定80%继续 | EXIT_PENDING / TARGET_UNREACHABLE |
| FI-11 | initial=TARGET_EXIT_PENDING; persisted=position_instance_id+exit_epoch+current leg | 目标退出部分成交，残仓反转 | PARTIAL_FILL+Quote | expected=当前腿入账；前腿终态且残仓>0时通过ExitLegCreationTransaction同epoch顺序fallback；仅POSITION_FLAT后写final_realized_ticket_equity并判轮; forbidden=提前成功、新epoch或非原子fallback | TARGET_EXIT_PENDING / TARGET_PARTIAL |
| FI-12 | initial=任意持仓; persisted=seen_trade_ids+position_instance_id+position_revision | 重复/乱序fill | DUPLICATE_FILL/LATE_ORDER_EVENT | expected=trade_id去重、同一实例revision只增不减；forbidden=重复记账或旧revision覆盖 | 原状态或RECONCILING / DUPLICATE_EVENT |
| FI-13 | initial=ARMED; persisted=clock health | 本地时钟偏移800ms | CLOCK_HEALTH_FAIL | expected=BLOCK并同步; forbidden=下单 | BLOCKED / CLOCK_OFFSET |
| FI-14 | initial=ARMED; persisted=未消费episode | 两个key level同秒触发 | MULTI_LEVEL_TRIGGER | expected=归一化选择唯一canonical episode; forbidden=两个intent | ENTRY_PENDING或IDLE / MULTI_LEVEL_RESOLVED |
| FI-15 | initial=LOCKED; persisted=breaker+round result | 进程重启 | PROCESS_RESTART | expected=恢复LOCKED; forbidden=默认IDLE | LOCKED / LOCK_PERSISTED |
| FI-16 | initial=VALIDATING; persisted=旧bracket_id | leverage bracket变化 | POSITION_RISK_UPDATE | expected=重算强平门，不足则退出; forbidden=使用旧liq价 | EXIT_PENDING / BRACKET_CHANGED |
| FI-17 | initial=PROTECTED; persisted=protection floor | 止损成交越过保护价数十bp | EXIT_FILL | expected=实际成交聚合至当前ExitEpoch；进入ZERO_QTY_CONFIRMATION/cleanup；最终POSITION_FLAT后写final_realized_ticket_equity并判轮; forbidden=按保护价记账、重复费用、清理后置或提前结算 | LOCKED / STOP_SLIPPAGE_TAIL |
| FI-18 | initial=任意持仓; persisted=最近有效灾难保护 | REST与私有流均不可用 | FACT_CHANNELS_DOWN | expected=不盲发，依赖驻留保护，重连并P0告警; forbidden=猜数量重复市价 | EMERGENCY_EXIT / FACT_CHANNELS_DOWN |
| FI-19 | initial=RECONCILING; persisted=exit_owner=VENUE_DISASTER_STOP+exit_epoch+disaster leg | Algo已触发但actual order未完成 | ALGO_UPDATE TRIGGERING/TRIGGERED | expected=使用VENUE_OBSERVED保持/接管同一epoch与灾难腿，查询actualOrder/仓位，不调用新建订单接口；forbidden=LOCAL_SUBMISSION、新epoch、第二本地主动腿或换ID | RECONCILING / ALGO_TRIGGER_IN_PROGRESS |
| FI-20 | initial=RECONCILING.RESIDUAL_ORDER_CLEANUP或POSITION_FLAT; persisted=closure phase+旧instance | 平仓后出现新开仓fill | LATE_FILL | expected=若仅qty-zero确认则撤销确认并恢复；若最终flat后新开仓fill则创建异常instance并RECOVERING；forbidden=忽略fill或复用旧instance | PROTECTING/EMERGENCY_EXIT / LATE_ENTRY_FILL |

## 附录 L　阶段验收清单

- 阶段0：官方能力记录、Spike、PnL、状态机、数据契约通过。

- 阶段1：Trades完整性、聚合一致性和能力标签通过。

- 阶段2：事件总体、基线、簇数与CI同时通过。
- 阶段2生命周期扩展：旧路径不变、配对策略、单仓机会成本、右删失和条件 H3 解释通过。

- 阶段3：H3主/压力情景和 conditional_round_success_probability 桥梁通过；未输出无条件实盘概率。

- 阶段4：锁定历史单次重放通过。

- 阶段5：FORWARD_HOLDOUT完整、未调参。

- 阶段6：FI-01至FI-20全部通过；测试网仅协议。

- 阶段7：真实成本和保护可靠性通过。

- 阶段8：单轮协议批准并持久LOCKED。

- 阶段9：另行决策，不在V1.3.4自动实现。

## 附录 M　V1.2 → V1.3、V1.3 → V1.3.1、V1.3.1 → V1.3.2、V1.3.2 → V1.3.3 及 V1.3.3 → V1.3.4 变更记录

| Change ID | 原章节 | 原规则 | 问题 | V1.3 / V1.3.1 / V1.3.2 / V1.3.3 / V1.3.4 处理 | 新章节 | 状态 | 测试 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C-001/A001 | §9.3/§12.2 | 原生条件单原单修改 | 当前Algo接口未提供修改路径 | 删除；不可变灾难止损+本地主动退出 | §17.2 | FROZEN | T-ALG-001 |
| C-002/A002 | §10-14 | UNKNOWN后直接清仓 | 无退出所有权和并发栅栏 | ExitCoordinator+position_instance_id+position_revision+exit_epoch | §19 | FROZEN | FI-04 |
| C-003/A003 | §9.2/INV-002 | 仓位数量等于保护数量 | 与closePosition语义冲突 | protection_sufficient按Algo状态/方向/版本判断 | §18 | FROZEN | T-ALG-002 |
| C-004/A004 | §6/公式 | 实际成交后再扣滑点 | 可能双扣 | 拆proxy/estimated/realized并禁止双扣 | §6/附录F | FROZEN | UT-PNL-015 |
| C-005/A005 | §10 | BLOCKED等状态缺失 | Codex需自行补状态 | 增加BLOCKED/RECONCILING/RECOVERING/TARGET_EXIT_PENDING | §20/附录G | FROZEN | T-SM-001 |
| C-006/A006 | §1/研究指标 | 事件到17轮无桥梁 | 单事件不等于单轮 | 一轮一笔，flat后按票面判定 | §1.1/§7.2 | FROZEN | T-RND-001 |
| C-007/A007 | §9.4 | 80%部分成交继续 | 无经济依据 | required_target_bps可达性三门 | §10.4 | FROZEN | FI-10 |
| C-008/A008 | §18.4/阶段5 | 历史后段为真正不可见测试 | 已可能被观察 | LOCKED_HISTORICAL_REPLAY+FORWARD_HOLDOUT | §13.3/阶段4-5 | FROZEN | T-RES-001 |
| C-009/A009 | §8 | 明显改善/目标空间等 | 不可编码 | CanonicalKeyLevel/MarketEpisode/布尔门及RESEARCH参数 | §9 | FROZEN+RESEARCH | FI-14 |
| C-010/A010 | §7/§9.3 | 强平只写留缓冲 | 无数值门 | liquidation_buffer_bps公式和时效字段 | §8.2 | FROZEN+BASELINE | FI-16 |
| C-011/A011 | §8.5 | 历史reclaim用executable_price | 历史无Bid/Ask | H1/H2用Contract/Trade；Quote字段NULL | §3.3/§9.2 | FROZEN | UT-DATA-013 |
| C-012/A012 | §8.6 G4 | 有数据才开启同一策略 | 历史/实盘规则漂移 | V1_PRICE与V1_FLOW注册为不同变体 | §9.4 | FROZEN | T-EVT-002 |
| C-013/A013 | §8.6 G6 | 赔率门无公式 | 开发者猜测 | required_target_bps与max_target比较；上限为RESEARCH | §10.4 | RESEARCH | FI-10 |
| C-014/A014 | §8.7 | event_id含strategy_version | 版本可绕过消费 | market_episode_id不含版本；intent_id含版本 | §9.3/§9.5 | FROZEN | INV-011 |
| C-015/A015 | §9.2/§9.4 | IOC结束后才保护 | 部分成交裸仓 | 首次非零fill立即PROTECTING | §10.3 | FROZEN | FI-01 |
| C-016/A016 | §9.4 | 超时可按失败处理 | -1006/-1007可能UNKNOWN | 同ID查询、保持RECONCILING、不盲重发 | §22 | FROZEN | FI-03 |
| C-017/A017 | §9.4/异常 | 查询失败仍“按交易所仓位清仓” | 事实通道不可用无法知数量 | 保留驻留保护、禁止猜数量、多通道恢复 | §19.4 | FROZEN | FI-18 |
| C-018/A018 | 移动保护 | 候选价穿越市场立即退出 | 退出类型/尾部无定义 | ExitDecision→ExitCoordinator；正常/紧急订单路径冻结 | §19.3/§21.3 | FROZEN | T-EXIT-002 |
| C-019/A019 | 路径标签 | 静态T_target/T_stop | trailing路径依赖不可复现 | 统一离散事件引擎逐事件更新状态 | §12.1 | FROZEN | T-LBL-001 |
| C-020/A020 | 标签/目标 | TARGET_FIRST即成功 | 目标触及不等于票面翻倍 | TARGET_与ROUND_分层；flat+权益达标才成功 | §12.2/§41 | FROZEN | FI-11 |
| C-021/A021 | 事件统计 | 事件聚类窗口未定义 | 置信区间虚窄 | cluster_id规则、窗口和主键进入Manifest | §13.2 | BASELINE | T-RES-002 |
| C-022/A022 | 研究门槛 | 多次试验无族级控制 | 研究者自由度膨胀 | 主假设预注册+完整试验台账 | §15-16 | FROZEN | T-RES-003 |
| C-023/A023 | 研究门槛 | 簇数或CI满足其一 | 小样本可通过 | 两者必须同时满足 | §15 | BASELINE | T-RES-004 |
| C-024/A024 | H3压力 | “2倍成本不得灾难性反转” | 无数值定义 | 主/1.5x/2x情景全报告；主情景下界>0，压力不得被隐藏 | §14-15 | BASELINE | T-COST-001 |
| C-025/A025 | 指标 | H3称Net Expectancy | 情景被误写为真实成本 | 改scenario_net_expectancy | §6.1/§14 | FROZEN | T-REP-001 |
| C-026/A026 | 价格口径 | price_return_bps隐含Mark | Contract/Mark/成交混用 | valuation_price_type必填，历史与F1分离 | §6.1/§12.3 | FROZEN | T-PNL-002 |
| C-027/A027 | §7.1 | 独立账户或子账户 | 隔离过宽 | 复利只允许专用子账户 | §7.1 | FROZEN | T-ACC-001 |
| C-028/A028 | 账户设置 | 只声明不补保证金 | 未核验Multi-Assets/auto add等 | 启动硬断言并失败BLOCKED | §7.1/§39 | FROZEN | T-ACC-002 |
| C-029/A029 | 对账 | 交易所事实覆盖本地 | 旧快照可覆盖新事实 | 快照时戳/事实版本门和position_instance_id/revision | §19/附录G-H | FROZEN | T-REC-001 |
| C-030/A030 | 退出 | reduce-only被当并发控制 | 不能解决竞态 | reduce-only仅参数；ExitCoordinator负责并发 | §19 | FROZEN | T-EXIT-003 |
| V131-001 | §14/阶段3/附录N | H3单轮概率表述未区分执行条件 | 历史缺少真实执行分布 | H3改conditional_round_success_probability；F1才估计无条件概率 | §14.1/阶段3/附录N | FROZEN | T-PROB-001~002 |
| V131-002 | §10.3/§19/附录E | position_version双重语义 | 部分成交与迟到事件归属不明 | 拆分position_instance_id与position_revision；旧字段DEPRECATED | §10.3/§19/附录E | FROZEN | T-POS-001~003 |
| V131-003 | §41/附录G-H | 连续两次零仓位未定义事实间隔 | 缓存快照可误判flat | 新增FlatConfirmationProtocol与BASELINE时限 | §41/附录G-H | FROZEN+BASELINE | T-FLAT-001~004 |
| V131-004 | §19/附录G-K | 灾难止损与主动退出竞态偏原则化 | 可能重复退出或错误所有权 | 新增退出所有权与竞态表；禁止第三退出 | §19.4/附录G-K | FROZEN | T-EXIT-RACE-001~004 |
| V131-005 | §8.2/EntryIntent | 降仓/降杠杆只重算强平门 | 旧目标和成本可能被沿用 | 新增ReSizingRevalidationPipeline与intent_revision | §8.3/附录D-H | FROZEN | T-SIZE-001~004 |
| V131-006 | 两份辅助文档页脚 | 第二页显示22 | 重复PAGE字段 | 重建单一自动PAGE字段 | 交付附件 | FROZEN | T-DOC-001~003 |
| V132-001 | §41/附录G-H | 双零快照与残余订单终态互相等待 | 灾难止损保留到qty=0但flat要求先终态，可能死锁 | 拆为ZERO_QTY_CONFIRMATION、RESIDUAL_ORDER_CLEANUP、FINAL_FLAT_CONFIRMATION；仅POSITION_FLAT后判轮 | §41/附录E/G/H/K | FROZEN | T-CLOSE-001~005 |
| V132-002 | §19/附录E/G/H | exit_epoch针对旧revision创建后再递增revision | created_against立即过期 | ExitEpochCreationTransaction原子递增revision并创建epoch；乐观锁冲突不下单 | §19.1.1/附录E/G/H | FROZEN | T-EPOCH-001~005 |
| V132-003 | §19.3/附录E/G/H/K | ExitIntent同时表达退出周期与具体订单 | LIMIT IOC→MARKET及灾难止损多腿语义不清 | 新增ExitEpoch与ExitOrderLeg；同epoch顺序回退、最多一个本地主动非终态腿、统一会计 | §19.3/附录E/G/H/K | FROZEN | T-LEG-001~008 |
| V133-001 | §17.2/§41/附录G-H | flat后再取消残余Algo单 | 与三阶段闭环时序冲突 | 残余Algo/普通订单在RESIDUAL_ORDER_CLEANUP内、POSITION_FLAT前清理并确认终态 | §17.2/§41/附录G-H | FROZEN | T-FREEZE-001 |
| V133-002 | §1.1/§7.2/§41/附录E-F | 仓位数量为0后可立即结算 | 可能绕过残单UNKNOWN和迟到成交 | 仅POSITION_FLAT后写final_realized_ticket_equity并判轮；中间值改estimated_ticket_equity_if_flat | §7.2/§41/附录E-F | FROZEN | T-FREEZE-002~004 |
| V133-003 | §19.1.1/附录E/G/H | ExitEpoch事务后再创建第一订单腿 | 崩溃可产生无腿active epoch | ExitEpochBootstrapTransaction同事务创建revision、epoch、第一腿和client_order_id | §19.1.1/附录E/G-H | FROZEN | T-BOOTSTRAP-001~005 |
| V133-004 | §19.3/附录E/G/H | 后续腿仅由应用层检查单活动腿 | 并发回调可重复创建fallback | ExitLegCreationTransaction+exit_epoch_revision乐观锁+ActiveLocalExitLeg主键约束 | §19.3.1/附录E/G-H | FROZEN | T-LEG-TX-001~007 |
| V134-001 | §19.1.1/§19.3/附录E/G/H | 灾难止损触发复用通用bootstrap | venue既有事实可能被误当本地待提交订单 | 拆分LOCAL_SUBMISSION与VENUE_OBSERVED；后者只接管/会计，不发送订单 | §19.1.1/§19.3/附录E/G-H | FROZEN | T-BOOT-MODE-001~005 |
| V134-002 | §19.1.1/§19.3.1/附录E | 两个原子事务字段初始化不完整 | Codex可能猜测NULL/0、ID和时间语义 | 补齐PositionState、ExitEpoch、ExitOrderLeg、ActiveLocalExitLeg全部必填字段和默认值 | §19.1.1/§19.3.1/附录E | FROZEN | T-CONTRACT-001~005 |
| V134-003 | 附录H/INV-012 | INV编号重复且使用旧realized_ticket_equity | 引用歧义和轮次字段混用 | 重排INV-025~035为唯一序列；INV-012统一final_realized_ticket_equity；新增唯一性门 | 附录H | FROZEN | T-INV-ID-001~004 |
| V134-004 | §41/附录G-H | Stage C仍含“完成清理”语义 | Stage B/C执行权重叠 | Stage B唯一执行清理并产生cleanup_complete；Stage C只验证并产生POSITION_FLAT | §41/附录G-H | FROZEN | T-STAGE-001~005 |
| V134-005 | 全篇版式 | 附录之间存在明显空白分页 | 阅读连续性差 | 仅删除目标附录多余分页前置并调整分页属性，不改正文 | 版式 | FROZEN | T-DOC-FINAL-001~005 |

上述S0/S1建议均已采用或经语义修正后采用；没有保留“已知问题但无替代方案”的S0/S1条款。参数最优性、Mark/Contract选择和适配器能力保留在附录N，属于RESEARCH或BLOCKED_BY_FORWARD_VALIDATION，不由Codex自行决定。

## 附录 N　当前未解决问题

本清单只保留无法在当前文档修订中由历史数据、当前接口文档或确定性工程规则解决的问题。V1.3.4 已冻结 LOCAL_SUBMISSION/VENUE_OBSERVED、两个原子事务完整字段、不变量唯一编号、Stage B/Stage C 单一职责和最终版式，不再将其列为 TODO。

| ID | 未决问题 | 状态 | 所需证据 | 解决阶段 | 阻塞范围 |
| --- | --- | --- | --- | --- | --- |
| U-001 | 灾难止损最终使用MARK_PRICE还是CONTRACT_PRICE | BLOCKED_BY_FORWARD_VALIDATION | Algo触发、Mark/Contract偏离、退出时间线 | Execution Spike+F1 | small-live |
| U-002 | Algo active status映射和适配器事件完整性 | BLOCKED_BY_FORWARD_VALIDATION | create/query/cancel/ALGO_UPDATE/restart | Spike | 影子自动状态 |
| U-003 | Nautilus Binance适配是否完整覆盖当前Algo Service | BLOCKED_BY_FORWARD_VALIDATION | 固定版本集成测试 | Spike | 执行适配选型 |
| U-004 | 正常退出LIMIT IOC后MARKET回退的时限和滑点包络 | BLOCKED_BY_FORWARD_VALIDATION | 影子和极小资金订单时间线 | F1/小额 | small-live |
| U-005 | stop_trigger_to_fill_stress_bps | BASELINE→F1 | 止损尾部滑点分位和极端样本 | 小额校准 | 100x开仓门 |
| U-006 | mark_contract_divergence_stress_bps | BASELINE→F1 | 前向Mark/Contract同步 | 前向影子 | 100x开仓门 |
| U-007 | key level优先级、合并容差、episode间隔与re-arm | RESEARCH | 条件基线、簇稳定性、样本外 | 阶段2 | 事件冻结 |
| U-008 | max_target_bps_allowed_for_event | RESEARCH | H1/H2/H3路径实验 | 阶段2-3 | 部分成交条件 |
| U-009 | 15-35bp止损范围 | RESEARCH | MAE/MFE、H3、F1尾部 | 阶段2-3/F1 | small-live |
| U-010 | +20%净ROE激活和阶梯参数 | RESEARCH；Stage 2 lifecycle Primary 已预注册 +20% 筛选但不冻结实盘规则 | 路径依赖回放和锁定历史重放 | 阶段2-4 | 持仓规则 |
| U-011 | 5/8分钟及15/25分钟退出 | RESEARCH；Stage 2 lifecycle 使用 8 分钟 Primary 比较但不自动修改规则 | Time-to-Activation/Time-since-MFE统计 | 阶段2-3 | 持仓规则 |
| U-012 | H3主成本、延迟和止损尾部情景 | RESEARCH | F1执行分布回校 | 阶段3/5/7 | H3解释范围 |
| U-013 | F1无条件单轮成功概率是否足以支持多轮 | H3只能得到分执行情景的条件代理概率；F1执行分布和真实Round样本尚不足 | RESEARCH / BLOCKED_BY_FORWARD_VALIDATION | 分情景条件概率、F1执行情景经验分布、预注册单轮实验区间 | 阶段5/7/8 |
| 阶段9 | 复利后期仓位容量、杠杆档位和订单冲击 | BLOCKED_BY_FORWARD_VALIDATION | 分规模执行和bracket研究 | 阶段9 | 多轮复利 |

已经冻结而不属于未决问题：条件灾难止损不直接改单；所有退出经过ExitCoordinator；UNKNOWN不得换ID盲重发；真实成交PnL不二次扣滑点；一轮最多一个非零成交EntryIntent；部分成交按可达性判断；ROUND_SUCCESS必须在PositionClosureProtocol产生最终POSITION_FLAT、清理完成且票面达标；market_episode消费不依赖strategy_version；LOCKED和轮结果跨重启；历史执行字段不得伪造；position_instance_id/revision语义、退出竞态和re-sizing全门复核均已确定。 V1.3.2 进一步冻结：POSITION_QTY_ZERO_CONFIRMED 与 POSITION_FLAT 分离；残余订单清理为独立阶段；exit_epoch 与 position_revision 原子创建；一个 exit_epoch 可含顺序 ExitOrderLeg，但最多一个本地主动非终态腿。 V1.3.3 进一步冻结：final_realized_ticket_equity 只能在 POSITION_FLAT 后写入；ExitEpochBootstrapTransaction 必须同时持久化第一 ExitOrderLeg 与 client_order_id；后续订单腿通过 ExitLegCreationTransaction、exit_epoch_revision 乐观锁和 ActiveLocalExitLeg 主键约束创建。 V1.3.4 进一步冻结：交易所既有灾难退出事实只用 VENUE_OBSERVED 接管；本地提交使用 LOCAL_SUBMISSION；原子事务字段和默认值完整；INV ID 全局唯一；Stage B 唯一清理，Stage C 只验证。

## Binance 官方能力决策记录

| Ref | 核验事实 | 官方URL | 核验日 |
| --- | --- | --- | --- |
| B01 | USDⓈ-M Algo条件单新建 /fapi/v1/algoOrder；支持STOP_MARKET等 | https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order | 2026-07-11 |
| B02 | Algo订单查询 /fapi/v1/algoOrder | https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Algo-Order | 2026-07-11 |
| B03 | Algo订单取消 /fapi/v1/algoOrder | https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Cancel-Algo-Order | 2026-07-11 |
| B04 | Algo事件 ALGO_UPDATE | https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update | 2026-07-11 |
| B05 | closePosition/quantity/reduceOnly/workingType/priceProtect限制 | https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order | 2026-07-11 |
| B06 | -1006/-1007执行状态未知；-1008与reduce-only说明 | https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code | 2026-07-11 |
| B07 | User Data Stream 60分钟、keepalive | https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams | 2026-07-11 |
| B08 | Multi-Assets和Position Mode查询 | https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Get-Current-Multi-Assets-Mode | 2026-07-11 |
| B09 | Notional与Leverage Brackets | https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Notional-and-Leverage-Brackets | 2026-07-11 |
| B10 | 数量步长、最小名义、Algo订单数量等过滤器 | https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition | 2026-07-11 |

> 交易所接口会变化。任何正式环境升级、SDK升级或官方变更后，Stage 0能力记录和Execution Spike必须重新运行。官方目录截至核验日未提供未触发Algo订单修改接口，因此V1.3.4继续将其视为不可变；若未来官方新增能力，不得自动启用，必须通过新版本ADR和故障测试。

- V1.3.4 最终定稿版结束。当前允许：事件研究、H1/H2/H3实现和最小 Execution Spike。当前禁止：测试网自动策略、极小资金、10 USDT单轮和复利。
