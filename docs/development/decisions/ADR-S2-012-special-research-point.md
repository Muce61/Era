# ADR-S2-012 — 特异研究点使用默认继承和显式逐条豁免

## Status

APPROVED — 2026-07-23 by Muce; implementation authorized by CR-2026-035

## Context

严格预注册适合验证主假设，但也可能挡住发现新现象。完全关闭规则又会让探索结果混入正式
证据、破坏密封输入或绕过实盘安全门。当前正式规则注册表中的32条rule_id全部为FROZEN，
所以单个Task或Codex不能自行创造通用绕过机制。

## Proposed decision

建立隔离的 `SPECIAL_RESEARCH_POINT`：

1. 默认继承当前注册表的全部规则。
2. 研究点只对逐条声明、逐条批准的研究规则产生局部豁免。
3. 未声明规则和未来新增规则自动继续生效。
4. 数据真实性、密封成果、证据等级、阶段门、审计、实盘安全及非research-owner规则永不可
   豁免。
5. 豁免FROZEN研究规则不会修改原规则，只把当前输出降级为
   `EXPLORATORY_NONCOMPLIANT`，并禁止进入Authority、Task PASS、Stage Gate或实盘。
6. 任何值得正式验证的发现必须建立新CR/ADR/Task并在无豁免的正式合同下复验。

## Consequences

研究者可以明确探索“如果不遵守某个事件定义或时间规则会怎样”，同时系统仍能回答：究竟
放宽了什么、哪些规则仍生效、结果为什么不能直接进入正式结论。代价是每个研究点需要独立
Manifest、人工批准和隔离输出，且不能用通配符或事后追加豁免。

## Rejected alternatives

- 全局`free_mode=true`：无法知道具体关闭了哪些规则，也会让新增规则被静默绕过。
- 只记录仍遵守的规则：漏写规则会变成隐式豁免，方向与默认安全相反。
- 允许研究点直接修改FROZEN规则：会污染正式规则注册表和已通过证据。
- 允许探索输出原地升级为正式证据：会绕过预注册、holdout和人工Stage Gate。

## First classified point

`SRP-S2-001` classifies CR-2026-031/032 and ADR-S2-010/011 under this proposed decision. Its
missingness/raw-evidence layer has no exemption. Muce approved its three bounded lifecycle
exemptions at `2026-07-23T01:04:16Z`; they remain not executable. This demonstrates the intended
behavior: classification and exact exemption approval record the research boundary, while
framework implementation and OQ/Task gates remain separate.
