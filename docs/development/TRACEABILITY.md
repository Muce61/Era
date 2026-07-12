# Specification Traceability

Model: formal rule → Stage → Task → implementation → tests → validation → current validity. The machine-readable complete catalogue is [`traceability/rules.yaml`](traceability/rules.yaml); every implementation/test path is explicitly PLANNED, not implemented.

## Stage 0 v1.0 Foundation Coverage

Stage 0 uses S0-T04 to catalogue all 32 formal rules and S0-T10 to enforce uniqueness/status/test ownership. S0-T07 owns the PnL foundation; S0-T08 owns Appendix C-E schema completeness; S0-T09 owns states and Reason Codes. Execution behavior remains assigned to later Stages and is not marked implemented by Stage 0. INV-001～INV-041 all include S0-T10 for registry/test-reference validation while retaining their behavioral Stage owner.

Stage 0 v1.0 is a valid PASSED baseline at validated implementation commit `692dd29`, with acceptance evidence in [`validations/stage_0_validation.md`](validations/stage_0_validation.md). The Stage 0 delivery rows below are effective. Entries assigned to Stage 1～9 remain PLANNED and are not promoted by this baseline. U-001～U-003 remain OPEN for their downstream scopes and do not invalidate the offline Stage 0 foundation baseline.

## Formal Rule Registry Coverage

| Rule ID | Rule Status | Source | Stage | Task | Implementation | Tests | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EXEC-NATIVE-STOP-IMMUTABLE | FROZEN | Appendix A; Binance B01-B05 + ADR-V13-001 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXEC-EXIT-COORDINATOR-ONLY | FROZEN | Appendix A; 审计A002/A030 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXEC-UNKNOWN-NO-BLIND-RETRY | FROZEN | Appendix A; Binance B06 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| RISK-PROTECTION-SUFFICIENT | FROZEN | Appendix A; Binance B05 + ADR-V13-002 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| RISK-LIQUIDATION-BUFFER | FROZEN | Appendix A; Binance B09 + 审计A010 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| ACCOUNT-DEDICATED-SUBACCOUNT | FROZEN | Appendix A; 审计A027/A028 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| ROUND-ONE-NONZERO-FILL | FROZEN | Appendix A; 审计A006 | S8 | S8-T01 | PLANNED | PLANNED | PLANNED |
| ROUND-SUCCESS-FLAT-EQUITY | FROZEN | Appendix A; 审计A020 | S9 | S9-T01 | PLANNED | PLANNED | PLANNED |
| EVENT-CONSUME-MARKET-EPISODE | FROZEN | Appendix A; 审计A014 | S2 | S2-T01 | PLANNED | PLANNED | PLANNED |
| FILL-FIRST-NONZERO-PROTECT | FROZEN | Appendix A; 审计A015 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| FILL-CONTINUE-BY-REACHABILITY | FROZEN | Appendix A; 审计A007 | S3 | S3-T01 | PLANNED | PLANNED | PLANNED |
| PNL-NO-DOUBLE-SLIPPAGE | FROZEN | Appendix A; 审计A004 | S3 | S3-T01 | PLANNED | PLANNED | PLANNED |
| DATA-HISTORICAL-NO-FAKE-EXECUTION | FROZEN | Appendix A; 数据能力边界 | S5 | S5-T01 | PLANNED | PLANNED | PLANNED |
| RESEARCH-LOCKED-REPLAY-ONCE | FROZEN | Appendix A; 审计A008 | S4 | S4-T01 | PLANNED | PLANNED | PLANNED |
| STATE-BREAKER-PERSIST | FROZEN | Appendix A; 审计A005/A046 | S8 | S8-T01 | PLANNED | PLANNED | PLANNED |
| STRATEGY-V1-PRICE-ONLY-HISTORICAL | FROZEN | Appendix A; 数据能力边界 | S2 | S2-T01 | PLANNED | PLANNED | PLANNED |
| RESEARCH-H3-CONDITIONAL-ROUND-PROB | FROZEN | Appendix A; V1.3.1验收修复F1 | S9 | S9-T01 | PLANNED | PLANNED | PLANNED |
| STATE-POSITION-INSTANCE-REVISION | FROZEN | Appendix A; V1.3.1验收修复F2 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| STATE-FLAT-CONFIRMATION-PROTOCOL | FROZEN | Appendix A; V1.3.1验收修复F3 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXEC-EXIT-RACE-OWNERSHIP | FROZEN | Appendix A; V1.3.1验收修复F4 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| RISK-RESIZING-FULL-REVALIDATION | FROZEN | Appendix A; V1.3.1验收修复F5 | S7 | S7-T01 | PLANNED | PLANNED | PLANNED |
| CLOSE-THREE-STAGE | FROZEN | Appendix A; V1.3.2补丁P1 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-EPOCH-ATOMIC-CREATE | FROZEN | Appendix A; V1.3.2补丁P2 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-LEG-SINGLE-ACTIVE-LOCAL | FROZEN | Appendix A; V1.3.2补丁P3 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| CLOSE-FINAL-FLAT-BEFORE-ROUND | FROZEN | Appendix A; V1.3.3冻结F1/F2 | S8 | S8-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-EPOCH-BOOTSTRAP-ATOMIC | FROZEN | Appendix A; V1.3.3冻结F3 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-LEG-CREATION-ATOMIC | FROZEN | Appendix A; V1.3.3冻结F4 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-LEG-DB-UNIQUE-GUARD | FROZEN | Appendix A; V1.3.3冻结F4 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-BOOTSTRAP-MODE | FROZEN | Appendix A; V1.3.4定稿F1 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| EXIT-TRANSACTION-FIELD-COMPLETE | FROZEN | Appendix A; V1.3.4定稿F2 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |
| INVARIANT-ID-GLOBAL-UNIQUE | FROZEN | Appendix A; V1.3.4定稿F3 | S0 | S0-T04, S0-T10 | PLANNED | PLANNED | PLANNED |
| CLOSURE-STAGE-SINGLE-RESPONSIBILITY | FROZEN | Appendix A; V1.3.4定稿F4 | S6 | S6-T01 | PLANNED | PLANNED | PLANNED |

Additional machine entries cover INV-001～INV-041, Appendix C/D/E/J contracts, Appendix I Reason Codes and all ten Appendix L Stage gates. DEPRECATED behavior is represented only by prevention/regression coverage and must not be implemented. BASELINE, RESEARCH and BLOCKED_BY_FORWARD_VALIDATION statuses remain unchanged.

## Stage 0 Task Delivery Status

| Task | Capability | Specification | Implementation | Tests | Validation | State |
| --- | --- | --- | --- | --- | --- | --- |
| S0-T01 | Python 3.12 project skeleton and import boundary | §23, §24, §28 | `pyproject.toml`, `src/era100x/__init__.py`, README development entry | `tests/test_package_import.py` | `validations/stage_0/S0-T01.md` | PASSED |
| S0-T02 | Locked Python toolchain and deterministic quality gate | §23, §27, §28 | `pyproject.toml`, `uv.lock`, `scripts/run_quality_gate.py` | collection, Ruff, mypy, pytest | `validations/stage_0/S0-T02.md` | PASSED |
| S0-T05 | Decimal, timestamp-source and stable-ID primitives | §6, §19.1, §25, Appendix C-E | `src/era100x/foundation/types/` | `tests/foundation/types/` | `validations/stage_0/S0-T05.md` | PASSED |
| S0-T03 | Effective configuration resolution and deterministic snapshot | §5, Appendix B | `src/era100x/foundation/config/`, `configs/` | `tests/foundation/config/` | `validations/stage_0/S0-T03.md` | PASSED |
| S0-T04 | 32-rule metadata registry and status guard | Appendix A | `src/era100x/foundation/rules/`, `configs/rules/` | `tests/foundation/rules/` | `validations/stage_0/S0-T04.md` | PASSED |
| S0-T09 | Frozen state, closure-phase, decision and Reason Code vocabularies | §20-22, §41, Appendix G/I | `src/era100x/foundation/state/` | `tests/foundation/state/` | `validations/stage_0/S0-T09.md` | PASSED |
| S0-T06 | Deterministic manifests and append-only audit records | §16, §26, §45, Appendix J | `src/era100x/foundation/audit/` | `tests/foundation/audit/` | `validations/stage_0/S0-T06.md` | PASSED |
| S0-T07 | Decimal-only Appendix F PnL contracts | §6, §10.4, §14.1, Appendix F | `src/era100x/foundation/accounting/` | `tests/foundation/accounting/` | `validations/stage_0/S0-T07.md` | PASSED |
| S0-T08 | Appendix C-E strict schema skeletons | §18-20, §25-26, Appendix C-E | `src/era100x/contracts/` | `tests/contracts/`, `tests/test_package_import.py` | `validations/stage_0/S0-T08.md` | PASSED |
| S0-T10 | Strict traceability integrity checker | §27, Appendix A/C-E/G-H/I/K/L | `scripts/check_traceability.py` | `tests/governance/` | `validations/stage_0/S0-T10.md` | PASSED |
| S0-T11 | Read-only locked CI quality gate | §23, §27, §28 | `.github/workflows/quality.yml`, `scripts/run_quality_gate.py` | local gate and static workflow audit | `validations/stage_0/S0-T11.md` | PASSED |
| S0-T12 | Offline execution capability port and hard network denial | §17-18, §22-28, Appendix E/K/N | `src/era100x/spike/ports/`, `configs/spike/example.yaml` | `tests/spike/offline/` | `validations/stage_0/S0-T12.md` | PASSED |
| S0-T13 | Stage 0 evidence integration and final-approval gate | §27-28, §38, §46, Appendix A/L/N | governance validations only | full quality, scope and prerequisite audits | `validations/stage_0/S0-T13.md`, `validations/stage_0_validation.md` | PASSED |

S0-T01 carries no business `rule_id` and does not mark any FROZEN rule or INV as implemented. It provides only the package boundary required by later individually approved Stage 0 Tasks.

Stage 0 baseline validity: **VALID / PASSED**. Any later change to its code, configuration contracts, dependency lock, traceability catalogue, or validation evidence requires explicit invalidation or reopening under `CHANGE_POLICY.md`.
