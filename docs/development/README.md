# Development Governance

This directory controls planning, execution, acceptance, freezing, invalidation, and reopening. `ROADMAP.md` defines the template; `STAGE_REGISTRY.md` indexes approved lifecycle state; `CURRENT_STAGE.md` is the single current-pointer; `TRACEABILITY.md` links rules to evidence; `CHANGE_POLICY.md`, `OPEN_QUESTIONS.md`, and `DECISIONS.md` govern change; `BASELINES.md` records immutable references.

Codex may update registries, traceability, validation evidence, and approved plan/task records only inside an authorized Task. Human approval is mandatory for Stage approval, Stage transition, acceptance, baseline promotion/invalidation, L3/L4 decisions, real API use, and any move toward forward or live operation.

Flow: draft plan → human approval → scoped Task execution → validation and review → acceptance → baseline. New facts use a Change Request and impact analysis; affected baselines are invalidated before reopening and regression.

V1.3.4 Stage 0～9 Plan v0.1 and their Task files now exist as `DRAFT`. They are planning artifacts only. `CURRENT_STAGE.md` remains the authoritative indicator that no Stage, Plan, or Task is active, and Stage 0 requires human review and approval before any implementation.
