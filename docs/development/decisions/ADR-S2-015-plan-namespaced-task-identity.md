# ADR-S2-015 — Stage plan version is part of Task identity

## Status

APPROVED — 2026-07-23 by Muce

## Decision

Task identity is `(stage_plan_version, task_id)`. Plan v1.2 `S2-T11` through `S2-T20` remain
permanent historical identities. Plan v1.3 uses external IDs `S2P13-T11` through `S2P13-T21`.

Evidence paths, schemas, UI and orchestration must carry both `stage_plan_version` and `task_id`.
Readers must reject an unqualified alias when more than one Plan can match. No legacy artifact is
renamed, moved, overwritten or silently projected as a v1.3 result.
