# Repository Instructions

## Source of Truth

`docs/spec/system_manual_v1.3.5_final.md` is the only current implementation authority. V1.2,
V1.3, V1.3.1, V1.3.2, V1.3.3, and V1.3.4 are archival only and must not drive new implementation.

## Rule Status

- `FROZEN`: implement exactly; Codex must not change it independently.
- `BASELINE`: starting configuration only; never describe it as optimal.
- `RESEARCH`: research workflow only; never hard-code it as a live rule.
- `DEPRECATED`: must not be reintroduced.
- `BLOCKED_BY_FORWARD_VALIDATION`: must remain disabled until forward validation passes.

## Non-negotiable Constraints

- Research BTC and ETH separately. V1 is long-only, isolated-margin, and single-position.
- No pyramiding, adding, or averaging down.
- Historical price/path supplementation may use Binance Trades only. CR-2026-038 narrowly permits
  BTCUSDT/ETHUSDT funding-rate acceptance from Binance official monthly `fundingRate` archives,
  with checksum verification, append-only evidence and no mutation of legacy sources. Never
  fabricate historical Bid, Ask, receive latency, partial fills, real slippage or funding.
- H1/H2/H3 must not be described as real live returns.
- Every exit must pass through `ExitCoordinator`.
- Never automatically connect real funds, enter testnet, enter tiny-live operation, or enter compounding experiments.
- Do not move to another stage before acceptance, and do not modify a `FROZEN` rule from a single backtest.

## Codex Work Rules

Before each task: read applicable `AGENTS.md` files and relevant manual sections; list applicable `rule_id` values; list allowed and forbidden files; provide an execution plan; and verify that the Stage, Plan, and Task are approved.

A bounded short rehearsal is an optional risk-control tool, not a default execution gate. Run one only when the user or an approved Task contract explicitly requires it, or when a targeted reproduction is needed to diagnose a failure. If a rehearsal is run, use real read-only inputs where available, write only to an isolated unpublished location, and exercise the relevant producer-to-consumer path. Any failure found by that rehearsal must be fixed and rechecked before the affected long task continues.

Every formal full-data Run must still bind a clean commit and human approval, preserve Authority-before-Run ordering, validate input and contract Hashes, hold the unique run lock, reconcile and Verify the complete range, preserve publication integrity and task boundaries, and fail closed on unknown missingness, unbound inputs or Hash drift. Removing the default seven-day rehearsal does not relax those gates or the Stage 3 lock.

After each task: run required validation commands; report actual modified files; update traceability; report incomplete work; distinguish tests actually run from tests not run; do not continue automatically; and never claim an unrun test passed.

For the Stage 2 progress Web UI, every newly added Plan, Task, or Task submodule must use the
Plan v1.3 observability standard: evidence-derived status, processed/total units, percentage,
elapsed time, throughput, ETA, current phase/subphase, heartbeat, Verify state, and automatic
left-rail projection. Do not replace these fields with a percentage-only card, hard-code PASS, or
leave obsolete evidence blocks between active Plan sections.

## Change Handling

Stop expanding implementation if the manual conflicts with official Binance facts, a `FROZEN` rule is not implementable, an upstream data contract must change, the Task scope is insufficient, research refutes an assumption, risk behavior must change, a real API is needed, or the next Stage is required. Record the matter in `docs/development/OPEN_QUESTIONS.md` or create a Change Request under `docs/development/changes/`.

## Code Exploration

- Prefer jCodeMunch MCP for repository code discovery: call `resolve_repo` first, index the
  repository when needed, inspect outlines before source, and retrieve only the relevant symbols.
- When the compact counter surface is active, use `jcodemunch_guide`, `menu`, `route`, or `order`
  to select and expose the needed repository tools before calling them.
- Prefer `search_symbols` or `search_text` over broad file reads during code exploration.
- Native file and shell tools remain allowed for edits, validation, non-code artifacts, exact
  line-oriented checks, or when jCodeMunch is unavailable or returns insufficient context.
- Re-index changed files before relying on stale symbol results.
