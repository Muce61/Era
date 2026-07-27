# S2P16-T19 v1.0 — Evidence Synthesis and Gate Projection

## Metadata

- task_id: S2P16-T19
- task_version: 1.0
- stage_plan_version: 1.6
- status: APPROVED / IMPLEMENTATION AUTHORIZED / FORMAL RUN GATED
- approved_by: Muce
- approved_at: 2026-07-27
- dependencies: verified formal S2P13-T11, S2P13-T16, S2P14-T17 and S2P15-T18
- evidence_level: historical H2/H3 research synthesis

## Objective

Apply the preregistered Stage 2 gates to immutable formal evidence, publish complete evidence
cards and make a non-promoting Go/No-Go recommendation.

## Allowed paths

- `src/era100x/research/stage_2/acceptance/evidence_gate/**`
- `tests/research/stage_2/acceptance/evidence_gate/**`
- `scripts/run_stage2_evidence_gate.py`
- approved Plan/Task/CR/ADR/policy/config/validation and Traceability records
- read-only Stage 2 progress API/UI and tests
- append-only external `stage2-plan-v1.6` evidence

## Forbidden paths and actions

- `docs/spec/**`, Stage 1, T11/T16/T17/T18 evidence and trading/execution code
- T20/T21 or Stage 3 implementation/execution
- Trades reads, outcome recomputation, bootstrap/FDR recomputation, PnL or live-return claims
- Authority or Run creation before commit-bound approval

## Required validation

- `uv run python -m pytest tests/research/stage_2/acceptance/evidence_gate -q`
- `uv run python scripts/run_quality_gate.py`
- strict source audit, real format smoke, bounded-memory benchmark and browser UI check
