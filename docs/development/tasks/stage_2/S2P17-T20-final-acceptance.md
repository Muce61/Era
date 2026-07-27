# S2P17-T20 v1.0 — Final Evidence Acceptance

## Metadata

- task_id: S2P17-T20
- task_version: 1.0
- stage_plan_version: 1.7
- status: FINAL FORMAL ENGINEERING / RECONCILIATION / VERIFY PASS / RESEARCH NO-GO
- approved_by: Muce
- approved_at: 2026-07-27
- dependencies: verified formal S2P13-T11, S2P13-T16, S2P14-T17, S2P15-T18 and S2P16-T19
- evidence_level: historical H2/H3 final evidence package

## Objective

Read and validate the immutable formal evidence chain, preserve the complete T19 gate and
parameter landscape, select six result-blind real evidence-card identities, and publish a
non-promoting Stage 2 NO-GO closure package.

## Allowed paths

- `src/era100x/research/stage_2/acceptance/final_acceptance/**`
- `src/era100x/research/stage_2/acceptance/canonical_json.py`
- `tests/research/stage_2/acceptance/**`
- `scripts/run_stage2_final_acceptance.py`
- approved Plan/Task/CR/ADR/policy/config/validation and Traceability records
- read-only Stage 2 progress API/UI and tests
- append-only external `stage2-plan-v1.7` evidence

## Forbidden paths and actions

- `docs/spec/**`, Stage 1, T11/T16/T17/T18/T19 evidence and trading/execution code
- T21 or Stage 3 implementation/execution
- Trades reads, path/outcome/bootstrap/gate recomputation, PnL or live-return claims
- Authority or Run creation before commit-bound approval

## Required validation

- `uv run python -m pytest tests/research/stage_2/acceptance -q`
- `uv run python scripts/run_quality_gate.py`
- strict source audit, real format smoke, canonical JSON compatibility and browser UI check
