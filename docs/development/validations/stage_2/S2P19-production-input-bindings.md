# S2P19 production input binding 修复验证

- status: `EXACT-KEY OVERLAY IMPLEMENTED / VALIDATED / REAL PREPARE PENDING`
- date: `2026-07-29`
- plan: `stage_2_plan_v1.9`
- task: `S2P19-T11`
- stage3_locked: `true`

## 修复对象

原 `prepare` 要求操作员提供十二类 `path + binding_hash`，但没有 production builder，
也没有为所有 role 固定唯一推导算法。校验只确认 Hash 是64位十六进制字符串，无法证明
它来自对应正式证据。

修复后：

- `prepare` 不再接受 `--input-spec`；
- production rules 文件固定十二类来源、rule ID、历史对象身份和固定 seed；
- 数据对象的自 Hash 均重新计算，源文件 SHA-256 单独进入 inputs lock；
- Contract Price Catalog Hash 由实际完整周期分区清单计算；
- matching/placebo/bootstrap/event-card 四处 seed 必须一致；
- inputs lock 为每项保存 `binding_rule`，并保存 production rules Hash；
- `prepare` 完成后以及创建 Authority 前都重新推导十二类 Hash；
- 任意手填、源文件漂移、规则漂移或语义 Hash 漂移均失败关闭。

## 验证边界

本验证只覆盖实现、fixture 和静态 production 证据读取。真实 `prepare` 必须在新干净
commit 上单独执行。此修复不得创建 Authority、Run、正式 Manifest/Verify 或进入
Stage 3。

## 真实只读 production rehearsal

第一次 rehearsal 发现本地正式分区不是单一 Parquet 布局：大部分日期是 CSV，部分日期
是 Parquet，少数日期两者同时存在。最终合同不按扩展名或新旧时间任意选择，而是使用
密封 T10 当日 `source_file_sha256`；只接受与其唯一相等的物理文件。T10 来源 Hash 通过
Parquet row-group statistics 读取，不解码整日数据列。

最终 rehearsal 结果：

- Contract Price instrument-day：`4,752`；
- production binding role：`12`；
- production rules Hash：
  `2ceb7f0e1f9bbb2fc6945df2aaff23401ba66d686389b9007446325a89e7cdde`；
- Contract Price Catalog Hash：
  `7ed15851dfd89ce155c9f872f5ebf12fc625b3ceb883584aca7e8f6ee39ff1c6`；
- four-consumer fixed-seed Hash：
  `360e27be2a63e6950381f6e243c6b7a4076c43ec1c0ed0ca797d03dee9685df3`。

这是只读 rehearsal，不是正式 source audit，也没有生成 inputs lock。

## 首次真实 prepare 的失败关闭与 exact-key 修复

commit `650c18f3adfec395270c0f4be10f637d4a541a3c` 上的首次真实 `prepare`
在读取 `BTCUSDT/2022-03-01` 时失败关闭。4,752 个 Stage 1 Parquet 中只有该文件缺失
合法 footer；物理 SHA 为
`fec26189fce7720b11e2b7dda9d104cec331c8c05aec7db95940f6f3b95602c1`，
而 sealed receipt 要求
`fc0f50e0d92b46520644666b040512b19cafbbcf0d143f714d92b4525315c296`。
该次执行没有生成 inputs lock、Authority 或 Run。

CR-2026-043 / ADR-S2-020 的既有唯一 supplement 已在当前代码下重新 Verify：

- Acceptance Hash：
  `1d70dcc5db4cd7d1ddc1800975cdde69d70934208f9a5c3d31053aa93eb43fd6`；
- Acceptance 文件 SHA：
  `70a659bf24d723c943323331ed45cffa31ed48283c387ae54fcb27d951f70fd7`；
- rebuilt byte SHA 精确等于 sealed receipt：
  `fc0f50e0d92b46520644666b040512b19cafbbcf0d143f714d92b4525315c296`；
- logical SHA：
  `eee2263fe964b5dcfb8d7fd8e063a240442dc844cbd66e1025c7aa9202b6fd84`；
- rows：`4,610,393`；
- 官方 ZIP integrity：PASS；
- `legacy_partition_modified=false`。

Plan v1.9 production rules v1.1 现在固定该 exact key、Acceptance、官方 archive/checksum、
Stage 1 published/catalog roots。source audit v1.1 把路径、文件 SHA、Acceptance Hash、
instrument/date 和旧文件未修改标记写入自身 Hash；十二类 role 数保持不变。prepare、
run、resume 只在限定上下文启用该 overlay，退出时恢复环境并清空 Trade day cache。

## 验证结果

- production binding、source audit、T10 metadata 定向测试：PASS；
- 全仓 pytest：`872 passed in 233.94s`；
- Ruff：`All checks passed!`；
- Mypy：`Success: no issues found in 224 source files`；
- strict governance：PASS；
- strict traceability：PASS（33 rules、41 INV、18 contracts、52 reasons、10 gates）；
- `git diff --check`：PASS。

以上检查均已实际执行。真实 `prepare`、Authority、Run 和 Stage 3 均未执行。

## Exact-key overlay 修复后的验证

- source audit / solo runtime / supplement 定向测试：`78 passed in 0.75s`；
- 全仓 pytest：`874 passed in 40.67s`；
- Ruff：`All checks passed!`；
- Mypy strict：`Success: no issues found in 224 source files`；
- strict governance：PASS，Stage 3 locked；
- strict traceability：PASS（33 rules、41 INV、18 contracts、52 reasons、10 gates）；
- `git diff --check`：PASS；
- 真实单日 consumer 对账：
  - overlay 未绑定：原文件 `ArrowInvalid`；
  - overlay 绑定：`4,610,393` rows，partition Hash 精确为 sealed SHA；
  - overlay 退出：原文件再次 `ArrowInvalid`。

上一节末尾的“真实 prepare 未执行”是首次 builder 修复提交冻结前的历史验证事实。随后
commit `650c18f...` 上的真实 prepare 已执行但失败关闭；本次 exact-key 修复的真实
prepare 仍须等新干净 commit 冻结后执行。Authority、Run 和 Stage 3 始终未执行。
