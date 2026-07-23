# ADR-S2-013 — Machine-readable current governance state controls write operations

## Status

APPROVED — current-state authority and fail-closed operation gate

## Context

Era keeps immutable historical evidence and append-only governance records, but the latest operational
truth is projected into multiple Markdown files. Those records can legitimately retain historical
status, yet code needs one unambiguous answer to a narrower question: what is permitted now?

S2-T15 is currently stopped. No formal T15 result exists; OQ-S2-009, OQ-S2-010 and OQ-S2-011 remain
blocking; SRP-S2-001 is not executable; Stage 3 is locked. The previous T15 implementation still has
write-capable entry points built under CR-2026-026 through CR-2026-030, so relying on selected text
markers or an older PASS audit is insufficient.

## Decision

1. `configs/governance/current_development_state.json` is the sole machine-readable authority for
   current operation permission.
2. The file is strict, content-addressed and fail-closed. Unknown fields, missing fields, duplicate
   values, unknown operations, unsafe source paths or hash drift invalidate the state.
3. Markdown documents remain append-only governance and human-readable projections; they do not
   independently grant execution permission.
4. Every write-capable T15 path must call the shared operation gate before creating directories,
   files, Authority, bins, Run state or publication output.
5. An operation is allowed only when its exact stable operation ID appears in `allowed_operations`.
   Absence is denial; there is no implicit permission and no wildcard.
6. The current stopped state allows only read-only audit, verification of existing immutable evidence
   and read-only UI projection.
7. Changing current permission requires a separately approved governance change, synchronized source
   records, a new canonical state hash, tests and a clean commit. Editing one Markdown file or one
   command-line flag cannot unlock execution.

## Operation IDs

```text
READ_ONLY_AUDIT
VERIFY_EXISTING_EVIDENCE
READ_ONLY_UI
BUILD_AUDIT_SUPPLEMENT
FREEZE_AUTHORITY
FREEZE_BINS
PREFLIGHT
RUN
RESUME
PUBLISH
```

## Consequences

- Current T15 write attempts fail with `GOVERNANCE_CURRENT_TASK_STOPPED` and record the state hash and
  blocking questions.
- Direct Python calls are governed in addition to the public CLI.
- Existing immutable evidence remains readable and verifiable.
- Historical CR approvals are retained, but an old approval cannot override the newer current state.
- The gate does not decide research parameters, close OQ-S2-009/010/011, implement SRP, or authorize
  Stage 3.

## Rejected alternatives

- Treat `CURRENT_STAGE.md` alone as executable configuration: free-form text is not a strict runtime
  contract and can drift from other records.
- Check only the CLI: tests or another module could import a lower-level write function directly.
- Infer permission from the latest PASS audit: data integrity evidence does not itself authorize a new
  Authority or Run.
- Add `--force`: this would turn a governance block into an operator preference and is forbidden.
- Delete old failed or approved records: append-only history must remain available for audit.

## Verification

`python scripts/check_governance_state.py --strict` validates the state hash, exact stopped facts,
source-document projections and guard presence at every approved T15 write entry point. Directed tests
also prove that read-only operations pass while every current write/run operation raises before side
effects.
