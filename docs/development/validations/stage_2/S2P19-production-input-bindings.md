# S2P19 production input binding 修复验证

- status: `IMPLEMENTED / VALIDATED / REAL_PREPARE_NOT_EXECUTED`
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

## 验证结果

- production binding、source audit、T10 metadata 定向测试：PASS；
- 全仓 pytest：`872 passed in 233.94s`；
- Ruff：`All checks passed!`；
- Mypy：`Success: no issues found in 224 source files`；
- strict governance：PASS；
- strict traceability：PASS（33 rules、41 INV、18 contracts、52 reasons、10 gates）；
- `git diff --check`：PASS。

以上检查均已实际执行。真实 `prepare`、Authority、Run 和 Stage 3 均未执行。
