# Repository Instructions

## Source of Truth

`docs/spec/system_manual_v1.3.4_final.md` is the only current implementation authority. V1.2, V1.3, V1.3.1, V1.3.2, and V1.3.3 are archival only and must not drive current implementation.

## Rule Status

- `FROZEN`: implement exactly; Codex must not change it independently.
- `BASELINE`: starting configuration only; never describe it as optimal.
- `RESEARCH`: research workflow only; never hard-code it as a live rule.
- `DEPRECATED`: must not be reintroduced.
- `BLOCKED_BY_FORWARD_VALIDATION`: must remain disabled until forward validation passes.

## Non-negotiable Constraints

- Research BTC and ETH separately. V1 is long-only, isolated-margin, and single-position.
- No pyramiding, adding, or averaging down.
- Historical supplementation may use Binance Trades only. Never fabricate historical Bid, Ask, receive latency, partial fills, or real slippage.
- H1/H2/H3 must not be described as real live returns.
- Every exit must pass through `ExitCoordinator`.
- Never automatically connect real funds, enter testnet, enter tiny-live operation, or enter compounding experiments.
- Do not move to another stage before acceptance, and do not modify a `FROZEN` rule from a single backtest.

## Codex Work Rules

Before each task: read applicable `AGENTS.md` files and relevant manual sections; list applicable `rule_id` values; list allowed and forbidden files; provide an execution plan; and verify that the Stage, Plan, and Task are approved.

Before every long-running or full-data task, first run a bounded short rehearsal over seven complete consecutive UTC days unless an approved task contract requires a stricter representative window. The rehearsal must use real read-only inputs where available, write only to an isolated unpublished location, and exercise the complete handoff path that the long task will use: computation, serialization, checkpoint or receipt creation, strict read-back by the next consumer, reconciliation, verification, and any read-only UI projection that is in scope. Record explicit simulated acceptance criteria before running it. A unit test, schema-only fixture, or successful producer write is not a substitute for the consumer read-back rehearsal.

Do not start or resume the long task until the short rehearsal has passed and its actual row counts, date range, output formats, hashes, read-back results, reconciliation, and limitations have been reported. Any formatting, schema, Decimal, timestamp, path, hash, checkpoint, receiver, or UI-projection failure in the rehearsal blocks the long task. Fix the problem, rerun the rehearsal from the beginning, and obtain any governance approval required by the changed code or contract. A seven-day rehearsal reduces execution risk but never proves that the full historical dataset will pass; full-data validation remains mandatory.

After each task: run required validation commands; report actual modified files; update traceability; report incomplete work; distinguish tests actually run from tests not run; do not continue automatically; and never claim an unrun test passed.

## Change Handling

Stop expanding implementation if the manual conflicts with official Binance facts, a `FROZEN` rule is not implementable, an upstream data contract must change, the Task scope is insufficient, research refutes an assumption, risk behavior must change, a real API is needed, or the next Stage is required. Record the matter in `docs/development/OPEN_QUESTIONS.md` or create a Change Request under `docs/development/changes/`.
