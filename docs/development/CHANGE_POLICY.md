# Change Policy

## Levels

- `L0`: wording or layout only.
- `L1`: internal implementation without interface change.
- `L2`: data contract or module interface.
- `L3`: research method, label, or metric.
- `L4`: `FROZEN` risk or execution rule.

Flow: new fact → Change Request → impact analysis → decision → affected baseline invalidation → related Stage reopening → regression → re-acceptance.

Change Requests live in `changes/` and use `CR-YYYY-NNN.md`. Each must contain discovery, source, affected rules, current behavior, proposed behavior, change level, impact analysis, baselines to invalidate, regression scope, and decision status. L3 and L4 require explicit human approval; Codex must not resolve risk choices independently.
