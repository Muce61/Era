"""Pure plugin protocols and their immutable approval descriptors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, Protocol, TypeAlias, runtime_checkable

from era100x.research.stage_2.runtime_v2.contracts import (
    EvidenceCapability,
    FeatureBatch,
    FeatureSource,
    HalfOpenTimeWindow,
    Instrument,
    require_sha256,
)
from era100x.research.stage_2.runtime_v2.models import metadata_sha256

RuntimeScalar: TypeAlias = Decimal | int | str | bool | None  # noqa: UP040
PluginKind: TypeAlias = Literal["SETUP", "CONTEXT"]  # noqa: UP040
_PLUGIN_KINDS = {"SETUP", "CONTEXT"}
_FEATURE_SOURCES = {"PRICE_FEATURE", "TRADE_PRIMITIVE", "EXACT_TRADE_ROWS", "EVENT_FACT"}
_CAPABILITIES = {"H1", "H2"}
_INSTRUMENTS = {"BTCUSDT", "ETHUSDT"}


@dataclass(frozen=True, slots=True)
class PluginAccessPolicy:
    """The only approved access policy for a Runtime V2 research plugin."""

    stage1_access: Literal["FORBIDDEN"] = "FORBIDDEN"
    filesystem_access: Literal["FORBIDDEN"] = "FORBIDDEN"
    network_access: Literal["FORBIDDEN"] = "FORBIDDEN"


@dataclass(frozen=True, slots=True)
class FeatureRequirement:
    definition_id: str
    definition_version: str
    definition_hash: str
    source: FeatureSource
    required_capability: EvidenceCapability
    lookback_ns: int = 0

    def __post_init__(self) -> None:
        if not self.definition_id or not self.definition_version:
            raise ValueError("feature requirement id and version are required")
        require_sha256(self.definition_hash, "definition_hash")
        if self.source not in _FEATURE_SOURCES:
            raise ValueError("feature requirement source is not approved")
        if self.required_capability not in _CAPABILITIES:
            raise ValueError("feature requirement capability is not approved")
        if self.lookback_ns < 0:
            raise ValueError("feature requirement lookback must be non-negative")
        if self.source in {"TRADE_PRIMITIVE", "EXACT_TRADE_ROWS"}:
            if self.required_capability != "H2":
                raise ValueError("Trades-derived requirements must declare H2 capability")


@dataclass(frozen=True, slots=True)
class RuntimePluginDescriptor:
    plugin_kind: PluginKind
    plugin_id: str
    plugin_version: str
    implementation_tree_hash: str
    output_schema_hash: str
    required_features: tuple[FeatureRequirement, ...]
    access_policy: PluginAccessPolicy = field(default_factory=PluginAccessPolicy)

    def __post_init__(self) -> None:
        if not self.plugin_id or not self.plugin_version:
            raise ValueError("plugin id and version are required")
        if self.plugin_kind not in _PLUGIN_KINDS:
            raise ValueError("plugin kind is not approved")
        require_sha256(self.implementation_tree_hash, "implementation_tree_hash")
        require_sha256(self.output_schema_hash, "output_schema_hash")
        if not self.required_features:
            raise ValueError("plugin descriptor requires Feature Definitions")
        keys = [(item.definition_id, item.definition_version) for item in self.required_features]
        if len(keys) != len(set(keys)):
            raise ValueError("plugin feature requirements must be unique")
        canonical = tuple(
            sorted(
                self.required_features,
                key=lambda item: (
                    item.source,
                    item.definition_id,
                    item.definition_version,
                    item.definition_hash,
                ),
            )
        )
        object.__setattr__(self, "required_features", canonical)

    @property
    def descriptor_hash(self) -> str:
        payload = {
            "plugin_kind": self.plugin_kind,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "implementation_tree_hash": self.implementation_tree_hash,
            "output_schema_hash": self.output_schema_hash,
            "required_features": [
                {
                    "definition_id": item.definition_id,
                    "definition_version": item.definition_version,
                    "definition_hash": item.definition_hash,
                    "source": item.source,
                    "required_capability": item.required_capability,
                    "lookback_ns": item.lookback_ns,
                }
                for item in self.required_features
            ],
            "access_policy": {
                "stage1_access": self.access_policy.stage1_access,
                "filesystem_access": self.access_policy.filesystem_access,
                "network_access": self.access_policy.network_access,
            },
        }
        return str(metadata_sha256(payload))


@dataclass(frozen=True, slots=True)
class RuntimePluginApproval:
    plugin_kind: PluginKind
    plugin_id: str
    plugin_version: str
    descriptor_hash: str
    implementation_tree_hash: str
    status: Literal["APPROVED"] = "APPROVED"

    def __post_init__(self) -> None:
        if self.plugin_kind not in _PLUGIN_KINDS:
            raise ValueError("plugin approval kind is not approved")
        if not self.plugin_id or not self.plugin_version:
            raise ValueError("plugin approval id and version are required")
        require_sha256(self.descriptor_hash, "descriptor_hash")
        require_sha256(self.implementation_tree_hash, "implementation_tree_hash")
        if self.status != "APPROVED":
            raise ValueError("runtime plugin approval must be APPROVED")

    @classmethod
    def from_descriptor(cls, descriptor: RuntimePluginDescriptor) -> RuntimePluginApproval:
        return cls(
            plugin_kind=descriptor.plugin_kind,
            plugin_id=descriptor.plugin_id,
            plugin_version=descriptor.plugin_version,
            descriptor_hash=descriptor.descriptor_hash,
            implementation_tree_hash=descriptor.implementation_tree_hash,
        )


@dataclass(frozen=True, slots=True)
class RuntimeVariantApproval:
    variant_id: str
    variant_version: str
    required_capability: EvidenceCapability
    required_feature_hashes: tuple[str, ...]
    status: Literal["APPROVED"] = "APPROVED"

    def __post_init__(self) -> None:
        if not self.variant_id or not self.variant_version:
            raise ValueError("variant id and version are required")
        if not self.required_feature_hashes:
            raise ValueError("variant must declare required Feature Definitions")
        if self.required_capability not in _CAPABILITIES:
            raise ValueError("variant evidence capability is not approved")
        if self.status != "APPROVED":
            raise ValueError("runtime variant approval must be APPROVED")
        for value in self.required_feature_hashes:
            require_sha256(value, "required_feature_hash")
        object.__setattr__(
            self,
            "required_feature_hashes",
            tuple(sorted(set(self.required_feature_hashes))),
        )


@dataclass(frozen=True, slots=True)
class PluginInvocation:
    """The complete plugin input surface; it intentionally contains no stores or paths."""

    instrument: Instrument
    owner_window: HalfOpenTimeWindow
    as_of_ns: int
    config_hash: str
    parameter_set_id: str
    batches: tuple[FeatureBatch, ...]
    parameters: Mapping[str, RuntimeScalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_sha256(self.config_hash, "config_hash")
        if self.instrument not in _INSTRUMENTS:
            raise ValueError("plugin invocation instrument is not approved")
        if not self.parameter_set_id:
            raise ValueError("parameter_set_id is required")
        if self.as_of_ns < self.owner_window.end_ns:
            raise ValueError("plugin invocation precedes its closed owner window")
        if not self.batches:
            raise ValueError("plugin invocation requires approved FeatureBatch inputs")
        seen: set[str] = set()
        for batch in self.batches:
            if batch.instrument != self.instrument:
                raise ValueError("plugin invocation cannot mix instruments")
            batch.require_available_as_of(self.as_of_ns)
            if batch.definition_hash in seen:
                raise ValueError("plugin invocation contains a duplicate Feature Definition")
            seen.add(batch.definition_hash)
        frozen_parameters: dict[str, RuntimeScalar] = {}
        if any(not isinstance(key, str) for key in self.parameters):
            raise TypeError("plugin parameter names must be strings")
        for key, value in sorted(self.parameters.items()):
            if not key:
                raise ValueError("plugin parameter names must be non-empty")
            if isinstance(value, float):
                raise TypeError("binary floats are forbidden in plugin parameters")
            if not isinstance(value, (Decimal, int, str, bool, type(None))):
                raise TypeError("plugin parameters must be scalar research values")
            if isinstance(value, Decimal) and not value.is_finite():
                raise ValueError("plugin Decimal parameters must be finite")
            frozen_parameters[key] = value
        object.__setattr__(self, "parameters", MappingProxyType(frozen_parameters))


@runtime_checkable
class ContextPlugin(Protocol):
    """Pure context function over already-authorized feature batches."""

    @property
    def descriptor(self) -> RuntimePluginDescriptor: ...

    def evaluate_context(self, invocation: PluginInvocation) -> FeatureBatch: ...


@runtime_checkable
class ResearchSetupPlugin(Protocol):
    """Pure event setup function; direct Stage 1/filesystem/network access is forbidden."""

    @property
    def descriptor(self) -> RuntimePluginDescriptor: ...

    def evaluate_setup(
        self, invocation: PluginInvocation, context: FeatureBatch
    ) -> FeatureBatch: ...
