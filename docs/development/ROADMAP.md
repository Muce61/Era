# Roadmap Template

## Purpose

Define the versioned Stage sequence after explicit human authorization. This file currently contains no Stage.

## Stage Lifecycle

`DRAFT → READY_FOR_APPROVAL → APPROVED → IN_PROGRESS → REVIEW → PASSED`

Exceptional states: `BLOCKED`, `INVALIDATED`, `REOPENED`, `SUPERSEDED`.

## Stage Record Template

- Stage identifier and title
- Plan version and dependencies
- In-scope and out-of-scope work
- Rule IDs and required baselines
- Deliverables, tests, acceptance gates, and rollback conditions
- Human approver and approval timestamp

Create a Stage only from an approved Stage-generation activity. Version plans immutably; supersede rather than overwrite approved versions. New facts invalidate affected baselines before a Stage is reopened and fully regressed.
