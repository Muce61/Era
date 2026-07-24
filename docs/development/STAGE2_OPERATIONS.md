# Stage 2 lightweight operations

`configs/governance/stage2_active_policy_v2.json` is the only machine-readable policy for new
Stage 2 Plan v1.3 runs. Runtime state comes from append-only approval receipts, Authorities,
checkpoints, task receipts, Manifests, Catalogs and Verify records. Historical governance files
remain readable evidence but cannot authorize a new run.

The single operator entrypoint is `scripts/run_stage2.py` with `status`, `rehearse`,
`record-approval`, `run`, `resume` and `verify`. A formal approval is stored outside Git and binds
the exact clean commit, Policy Hash and final-code rehearsal receipt. Recording approval does not
change the repository.

CR or ADR is required only for research semantics, frozen rules, data/source authority, risk
behavior, Stage boundaries or real-execution scope. Code fixes, UI fixes, adapter wiring,
performance work, receipt formatting and ordinary tests use normal commits and regression tests.

Every formal chain freezes a ChainAuthority before any Task Run ID. S2P13-T16 later freezes its
dynamic upstream Authority and TRAIN-only bins before its own Run ID. T17+ and Stage 3 remain
locked.
