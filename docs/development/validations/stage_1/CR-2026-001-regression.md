# CR-2026-001 Trade Identity v2 Regression Validation

- Scope: S1-T02/T05/T07/T08/T09/T12 v1.1; S1-T06/T10/T11 regression; S1-T14 v1.5 builder implementation
- Rules: DATA-HISTORICAL-NO-FAKE-EXECUTION, STRATEGY-V1-PRICE-ONLY-HISTORICAL, INV-013, Stage 1 gate
- Conclusion: PASS for code/schema remediation; S1-T14 full-data run remains IN_PROGRESS

## Evidence

- Decimal-equivalent text produces the same canonical SHA-256.
- Exact canonical duplicates fold deterministically.
- Same venue ID with different facts is retained and marked as one conflict group.
- Stable order and logical hash use `(ts_event_ns, venue_trade_id, canonical_trade_id)`.
- Official monthly/daily conflict-set match passes and mismatch fails.
- Kline regression counts both different facts once; BTC/ETH isolation and historical NULL boundaries remain enforced.
- Prior 134/162 run is INVALIDATED; no published dataset exists and its staging is forbidden for reuse.

## Modified implementation

`src/era100x/data/schema/`, `normalize/`, `quality/`, `storage/`, `aggregate/`, `full_build/`; matching tests and Stage 1 configuration/governance.

## Commands

- `uv run python scripts/run_quality_gate.py`: PASS; Ruff format/lint, mypy strict, Traceability strict and full pytest `110 passed`.
- `uv run python scripts/check_contract_coverage.py`: PASS; Appendix C-E `15/15`.
- `git diff --check`: PASS.
- Targeted v2 suite: PASS; `28 passed` before the final added lineage/external-sort regression, with the final full suite authoritative.

A PASS here never means S1-T14 data completion or Stage 1 acceptance.
