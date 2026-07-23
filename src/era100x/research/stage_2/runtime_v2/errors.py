"""Fail-closed errors for the Stage 2 V2 artifact runtime."""

from __future__ import annotations


class RuntimeV2Error(RuntimeError):
    """Base class for governed V2 runtime failures."""


class ContractViolation(RuntimeV2Error):
    """A frozen model or semantic-data contract was violated."""


class SnapshotMismatch(ContractViolation):
    """Artifacts from different immutable snapshots were mixed."""


class CatalogIntegrityError(RuntimeV2Error):
    """Catalog metadata, references, or physical objects are inconsistent."""


class PublicationConflict(RuntimeV2Error):
    """Append-only publication encountered different bytes at an existing path."""
