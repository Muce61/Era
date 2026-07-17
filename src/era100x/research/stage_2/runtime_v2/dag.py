"""Content-addressed dependency keys for causal Runtime V2 build nodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from era100x.research.stage_2.runtime_v2.contracts import (
    EvidenceCapability,
    Instrument,
    require_sha256,
)
from era100x.research.stage_2.runtime_v2.models import metadata_sha256

NodeKind: TypeAlias = Literal[  # noqa: UP040
    "PRICE_FEATURE",
    "TRADE_PRIMITIVE",
    "EXACT_TRADE_WINDOW",
    "EVENT_FACT",
]
_NODE_KINDS = {"PRICE_FEATURE", "TRADE_PRIMITIVE", "EXACT_TRADE_WINDOW", "EVENT_FACT"}
_INSTRUMENTS = {"BTCUSDT", "ETHUSDT"}
_CAPABILITIES = {"H1", "H2"}


@dataclass(frozen=True, slots=True)
class ContentAddressedDAGNodeKey:
    """Complete semantic identity of one immutable logical build node.

    Physical paths, Parquet bytes, compression and worker assignment are
    deliberately absent.  Changing any semantic authority or any dependency
    produces a different key and therefore invalidates all dependent nodes.
    """

    node_kind: NodeKind
    definition_id: str
    definition_version: str
    definition_hash: str
    implementation_tree_hash: str
    config_hash: str
    schema_hash: str
    instrument: Instrument
    logical_utc_partition: str
    evidence_capability: EvidenceCapability
    availability_rule: str
    source_logical_hashes: tuple[str, ...]
    dependency_node_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.definition_id or not self.definition_version:
            raise ValueError("DAG node definition id and version are required")
        if not self.logical_utc_partition:
            raise ValueError("DAG node logical UTC partition is required")
        if not self.availability_rule:
            raise ValueError("DAG node causal availability rule is required")
        if self.node_kind not in _NODE_KINDS:
            raise ValueError("DAG node kind is not approved")
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("DAG node instrument is not approved")
        if self.evidence_capability not in _CAPABILITIES:
            raise ValueError("DAG node evidence capability is not approved")
        if self.node_kind in {"TRADE_PRIMITIVE", "EXACT_TRADE_WINDOW"}:
            if self.evidence_capability != "H2":
                raise ValueError("Trades-derived DAG nodes require H2 capability")
        for field_name, value in (
            ("definition_hash", self.definition_hash),
            ("implementation_tree_hash", self.implementation_tree_hash),
            ("config_hash", self.config_hash),
            ("schema_hash", self.schema_hash),
        ):
            require_sha256(value, field_name)
        if not self.source_logical_hashes:
            raise ValueError("DAG node requires at least one source logical hash")
        for digest in self.source_logical_hashes:
            require_sha256(digest, "source_logical_hash")
        for digest in self.dependency_node_keys:
            require_sha256(digest, "dependency_node_key")
        object.__setattr__(
            self,
            "source_logical_hashes",
            tuple(sorted(set(self.source_logical_hashes))),
        )
        object.__setattr__(
            self,
            "dependency_node_keys",
            tuple(sorted(set(self.dependency_node_keys))),
        )

    @property
    def value(self) -> str:
        """Return the physical-layout-independent SHA-256 node identity."""

        return str(
            metadata_sha256(
                {
                    "node_kind": self.node_kind,
                    "definition_id": self.definition_id,
                    "definition_version": self.definition_version,
                    "definition_hash": self.definition_hash,
                    "implementation_tree_hash": self.implementation_tree_hash,
                    "config_hash": self.config_hash,
                    "schema_hash": self.schema_hash,
                    "instrument": self.instrument,
                    "logical_utc_partition": self.logical_utc_partition,
                    "evidence_capability": self.evidence_capability,
                    "availability_rule": self.availability_rule,
                    "source_logical_hashes": self.source_logical_hashes,
                    "dependency_node_keys": self.dependency_node_keys,
                }
            )
        )


DAGNodeKey = ContentAddressedDAGNodeKey


def content_addressed_node_key(node: ContentAddressedDAGNodeKey) -> str:
    """Small functional surface for manifests and build schedulers."""

    return node.value
